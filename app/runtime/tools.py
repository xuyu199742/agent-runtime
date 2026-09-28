import ast
import asyncio
import ipaddress
import operator
import socket
from collections.abc import Sequence
from urllib.parse import urlparse

import httpx
from langchain_core.tools import BaseTool, StructuredTool, tool

from app.config import get_settings
from app.infrastructure.database import ToolDefinition

_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def calculate(expression: str) -> str:
    if len(expression) > 200:
        raise ValueError("表达式过长")

    def evaluate(node: ast.AST, depth: int = 0) -> float:
        if depth > 20:
            raise ValueError("表达式嵌套过深")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = float(node.value)
        elif isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            value = _OPERATORS[type(node.op)](
                evaluate(node.left, depth + 1), evaluate(node.right, depth + 1)
            )
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand, depth + 1) * (-1 if isinstance(node.op, ast.USub) else 1)
        else:
            raise ValueError("只支持数字与加减乘除")
        if abs(value) > 1e12:
            raise ValueError("计算结果超出范围")
        return value

    try:
        result = evaluate(ast.parse(expression, mode="eval").body)
    except (SyntaxError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError("表达式无效") from exc
    return str(int(result)) if result.is_integer() else str(result)


@tool
def echo(text: str) -> str:
    """原样返回输入文本。"""
    return text


@tool("calculator")
def calculator(expression: str) -> str:
    """计算仅含数字和加减乘除的算术表达式。"""
    return calculate(expression)


def calculator_tool() -> BaseTool:
    return calculator


async def _check_public_host(host: str) -> None:
    infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    if not infos or any(not ipaddress.ip_address(info[4][0]).is_global for info in infos):
        raise ValueError("目标地址不允许访问")


def http_tool(allowed_hosts: set[str], timeout_seconds: float = 10) -> BaseTool:
    async def http_request(url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or host not in allowed_hosts
            or parsed.username
            or parsed.password
        ):
            raise ValueError("HTTP Tool 只允许白名单中的 HTTPS 地址")
        await _check_public_host(host)
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout_seconds) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text[:20000]

    return StructuredTool.from_function(
        coroutine=http_request,
        name="http_request",
        description="通过 HTTPS GET 请求服务端允许的公开域名。",
    )


def build_tools(definitions: Sequence[ToolDefinition]) -> list[BaseTool]:
    native = {"echo": echo, "calculator": calculator}
    allowed_hosts = {
        host.strip().lower()
        for host in get_settings().http_tool_allowed_hosts.split(",")
        if host.strip()
    }
    result = []
    for definition in definitions:
        if not definition.enabled:
            raise ValueError(f"工具未启用: {definition.name}")
        if definition.type == "NATIVE" and definition.name in native:
            result.append(native[definition.name])
        elif definition.type == "HTTP" and definition.name == "http_request" and allowed_hosts:
            result.append(http_tool(allowed_hosts))
        else:
            raise ValueError(f"不支持的工具配置: {definition.name}")
    return result
