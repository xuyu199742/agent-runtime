import hashlib
import json

import structlog
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.config import get_config

from app.context.errors import ContextLeaseLost
from app.persistence.repositories.traces import ExecutionRecorder
from app.runtime.effects.executor import EffectExecutor
from app.runtime.errors import PolicyDenied, ToolResultUnavailable, WriteNotAllowed
from app.runtime.policy import PolicyOutcome, evaluate_tool_policy

log = structlog.get_logger()


class PolicyMiddleware(AgentMiddleware):
    def __init__(self, session_factory=None, run_id=None, worker_id=None, policies=None):
        self.session_factory = session_factory
        self.run_id = run_id
        self.worker_id = worker_id
        self.policies = policies

    async def awrap_tool_call(self, request, handler):
        # 未注入快照的本地 Runtime 保留现有行为；Worker 总会提供冻结快照。
        if self.policies is None:
            return await handler(request)
        name = request.tool_call["name"]
        tool = self.policies.get(name)
        decision = evaluate_tool_policy(tool)
        if decision.outcome == PolicyOutcome.DENY:
            if self.session_factory is not None and self.run_id and self.worker_id:
                async with self.session_factory() as db:
                    recorder = ExecutionRecorder(db)
                    if (
                        await recorder.append(
                            self.run_id,
                            "policy.denied",
                            {
                                "name": name,
                                "reason_code": decision.reason_code,
                                "effect_type": (tool or {}).get("effect_type", "UNKNOWN"),
                            },
                            worker_id=self.worker_id,
                        )
                        is None
                    ):
                        raise ContextLeaseLost
                    await db.commit()
            raise PolicyDenied(decision.reason_code)
        return await handler(request)


class TracingMiddleware(AgentMiddleware):
    def __init__(self, model_call_journal=None):
        self.model_call_journal = model_call_journal

    async def awrap_model_call(self, request, handler):
        log.info("模型调用开始")
        execution_id = None
        if self.model_call_journal is not None:
            metadata = get_config().get("metadata") or {}
            graph_step = metadata.get("langgraph_step")
            if graph_step is None:
                raise RuntimeError("LangGraph Model Step 标识缺失")
            step_id = f"{self.model_call_journal.run_id}:model:{graph_step}"
            messages = (
                [request.system_message] if request.system_message is not None else []
            ) + list(request.messages)
            execution_id = await self.model_call_journal.start(step_id, "AGENT", messages)
        try:
            response = await handler(request)
        except Exception as exc:
            log.error("模型调用失败", error_type=type(exc).__name__)
            if execution_id is not None:
                await self.model_call_journal.fail(execution_id)
            raise
        if execution_id is not None:
            output = next(
                (item for item in reversed(response.result) if isinstance(item, AIMessage)), None
            )
            if output is None:
                raise RuntimeError("模型调用没有返回 AIMessage")
            await self.model_call_journal.complete(execution_id, output)
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
            if record.status == "COMPLETED":
                if record.result_content is None:
                    raise ToolResultUnavailable("已完成的 Tool 调用缺少可重放结果")
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
            except ContextLeaseLost:
                raise
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


class EffectSafetyMiddleware(AgentMiddleware):
    """仅拦截显式登记的外部写入，未知结果不交回模型继续执行。"""

    def __init__(self, store=None, run_id=None, worker_id=None, policies=None, providers=None):
        self.store = store
        self.run_id = run_id
        self.worker_id = worker_id
        self.policies = policies or {}
        self.providers = providers or {}

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        effect_type = self.policies.get(call["name"], {}).get("effect_type", "READ_ONLY")
        if effect_type == "READ_ONLY":
            return await handler(request)
        if effect_type != "EXTERNAL_WRITE":
            raise WriteNotAllowed("不支持的写入类型")
        if self.policies[call["name"]].get("policy", {}).get("write_allowed") is not True:
            raise WriteNotAllowed("写入 Tool 未获得显式授权")
        provider = self.providers.get(call["name"])
        if provider is None or self.store is None or self.run_id is None or self.worker_id is None:
            raise WriteNotAllowed("写入 Tool 未配置受控 Effect Provider")
        result = await EffectExecutor(self.store, provider).execute(
            self.run_id, self.worker_id, call.get("args", {}), call_id=call["id"]
        )
        return ToolMessage(content=result, tool_call_id=call["id"], name=call["name"])


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
