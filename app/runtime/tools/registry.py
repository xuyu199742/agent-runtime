from collections.abc import Sequence

from langchain_core.tools import BaseTool

from app.config import get_settings
from app.infrastructure.database import ToolDefinition
from app.runtime.tools.calculator import calculator
from app.runtime.tools.echo import echo
from app.runtime.tools.http_request import http_tool


class ToolConfigurationError(ValueError):
    pass


def build_tools(definitions: Sequence[ToolDefinition]) -> list[BaseTool]:
    native = {"echo": echo, "calculator": calculator}
    server_allowed_hosts = {
        host.strip().lower()
        for host in get_settings().http_tool_allowed_hosts.split(",")
        if host.strip()
    }
    result = []
    for definition in definitions:
        if not definition.enabled:
            raise ToolConfigurationError(f"工具未启用: {definition.name}")
        if definition.type == "NATIVE" and definition.name in native:
            result.append(native[definition.name])
        elif definition.type == "HTTP" and definition.name == "http_request":
            config = definition.config or {}
            requested_hosts = config.get("allowed_hosts", [])
            if not isinstance(requested_hosts, list) or not all(
                isinstance(host, str) for host in requested_hosts
            ):
                raise ToolConfigurationError("HTTP 工具白名单配置无效")
            allowed_hosts = server_allowed_hosts.intersection(
                host.lower() for host in requested_hosts
            )
            timeout = config.get("timeout_seconds", 10)
            if not allowed_hosts or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 30:
                raise ToolConfigurationError("HTTP 工具未设置有效的白名单与超时")
            result.append(http_tool(allowed_hosts, timeout_seconds=float(timeout)))
        else:
            raise ToolConfigurationError(f"不支持的工具配置: {definition.name}")
    return result
