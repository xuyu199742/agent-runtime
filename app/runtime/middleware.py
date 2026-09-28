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
    async def awrap_tool_call(self, request, handler):
        try:
            return await handler(request)
        except Exception as exc:  # noqa: BLE001 - Tool 错误需转换为模型可见结果
            log.warning(
                "工具调用失败", tool_name=request.tool_call["name"], error_type=type(exc).__name__
            )
            return ToolMessage(
                content="工具执行失败",
                tool_call_id=request.tool_call["id"],
                name=request.tool_call["name"],
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
