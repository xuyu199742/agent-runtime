import asyncio
from collections.abc import Sequence

from langchain_core.tools import BaseTool, StructuredTool

from app.config import get_settings
from app.domain.agent import ToolDefinition
from app.runtime.tools.calculator import calculate, calculator
from app.runtime.tools.echo import echo
from app.runtime.tools.http_request import http_tool


class ToolConfigurationError(ValueError):
    pass


def tool_idempotency_key(run_id: str, tool_call_id: str) -> str:
    """未来写入型 Tool 的稳定调用键；由目标业务系统负责按键去重。"""
    return f"{run_id}:{tool_call_id}"


def build_calculator(description: str, timeout: float) -> BaseTool:
    async def invoke(expression: str) -> str:
        return await asyncio.wait_for(asyncio.to_thread(calculate, expression), timeout)

    return StructuredTool.from_function(
        coroutine=invoke, name="calculator", description=description or calculator.description
    )


def build_echo(description: str, timeout: float) -> BaseTool:
    async def invoke(text: str) -> str:
        return await asyncio.wait_for(asyncio.sleep(0, result=text), timeout)

    return StructuredTool.from_function(
        coroutine=invoke, name="echo", description=description or echo.description
    )


NATIVE_FACTORIES = {"calculator": build_calculator, "echo": build_echo}


def build_tools(definitions: Sequence[ToolDefinition]) -> list[BaseTool]:
    server_allowed_hosts = {
        host.strip().lower()
        for host in get_settings().http_tool_allowed_hosts.split(",")
        if host.strip()
    }
    result = []
    for definition in definitions:
        if not definition.enabled:
            raise ToolConfigurationError(f"工具未启用: {definition.name}")
        config = definition.config or {}
        timeout = config.get("timeout_seconds", 10)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= 30
        ):
            raise ToolConfigurationError("Tool 超时配置无效")
        if definition.type == "NATIVE" and definition.name in NATIVE_FACTORIES:
            result.append(NATIVE_FACTORIES[definition.name](definition.description, float(timeout)))
        elif definition.type == "HTTP" and definition.name == "http_request":
            policy = definition.policy or {}
            requested_hosts = policy.get("allowed_hosts", config.get("allowed_hosts", []))
            if not isinstance(requested_hosts, list) or not all(
                isinstance(host, str) for host in requested_hosts
            ):
                raise ToolConfigurationError("HTTP 工具白名单配置无效")
            allowed_hosts = server_allowed_hosts.intersection(
                host.lower() for host in requested_hosts
            )
            if not allowed_hosts or not 1 <= timeout <= 30:
                raise ToolConfigurationError("HTTP 工具未设置有效的白名单与超时")
            tool = http_tool(allowed_hosts, timeout_seconds=float(timeout))
            if definition.description:
                tool.description = definition.description
            result.append(tool)
        else:
            raise ToolConfigurationError(f"不支持的工具配置: {definition.name}")
    return result
