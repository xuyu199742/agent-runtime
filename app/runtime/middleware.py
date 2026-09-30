import hashlib
import json

import structlog
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

log = structlog.get_logger()


class TracingMiddleware(AgentMiddleware):
    async def awrap_model_call(self, request, handler):
        log.info("模型调用开始")
        try:
            response = await handler(request)
        except Exception as exc:
            log.error("模型调用失败", error_type=type(exc).__name__)
            raise
        log.info("模型调用结束")
        return response


class ToolErrorMiddleware(AgentMiddleware):
    def __init__(self, store=None, run_id: str | None = None, policies: dict | None = None):
        self.store = store
        self.run_id = run_id
        self.policies = policies or {}

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        policy = self.policies.get(call["name"], {})
        failure_policy = policy.get("failure_policy", "RETURN_ERROR")
        if self.store is not None:
            args_hash = hashlib.sha256(
                json.dumps(call.get("args", {}), sort_keys=True, default=str).encode()
            ).hexdigest()
            record = await self.store.start(
                self.run_id,
                call["id"],
                call["name"],
                policy.get("effect_type", "READ_ONLY"),
                args_hash,
            )
            if record.status == "COMPLETED" and record.result_content is not None:
                return ToolMessage(
                    content=record.result_content, tool_call_id=call["id"], name=call["name"]
                )
        with structlog.contextvars.bound_contextvars(
            tool_name=call["name"], tool_call_id=call["id"]
        ):
            try:
                result = await handler(request)
                if isinstance(result, ToolMessage) and result.status == "error":
                    if failure_policy == "FAIL_RUN":
                        raise RuntimeError("Tool 调用失败")
                    if self.store is not None:
                        await self.store.finish(
                            self.run_id, call["id"], "FAILED", str(result.content), "TOOL_ERROR"
                        )
                    return result
                if self.store is not None:
                    await self.store.finish(
                        self.run_id,
                        call["id"],
                        "COMPLETED",
                        str(result.content) if isinstance(result, ToolMessage) else None,
                        None,
                    )
                return result
            except Exception as exc:
                log.warning("工具调用失败", error_type=type(exc).__name__)
                if self.store is not None:
                    await self.store.finish(self.run_id, call["id"], "FAILED", None, "TOOL_ERROR")
                if failure_policy == "FAIL_RUN":
                    raise
                return ToolMessage(
                    content="工具执行失败",
                    tool_call_id=call["id"],
                    name=call["name"],
                    status="error",
                )


class RunContextMiddleware(AgentMiddleware):
    async def abefore_agent(self, state, runtime):
        context = runtime.context or {}
        structlog.contextvars.bind_contextvars(
            **{
                key: value
                for key, value in context.items()
                if key in {"run_id", "session_id", "user_id"} and value is not None
            }
        )
