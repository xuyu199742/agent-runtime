"""受控的只读 MCP Provider；连接只来自部署时配置的可信服务。"""

import asyncio
import ipaddress
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import ConfigDict, create_model

from app.config import get_settings

MAX_SCHEMA_BYTES = 16384
MAX_RESULT_BYTES = 32768


def validate_provider_url(url: str, allowed_hosts: set[str]) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        is_ip = False
    else:
        is_ip = True
    if (
        parsed.scheme != "https"
        or not host
        or is_ip
        or host not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or parsed.port not in {None, 443}
    ):
        raise ValueError("MCP Server URL 不在受控 HTTPS 白名单")
    return host


def _has_ref(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in {"$ref", "$dynamicRef", "$id"} or _has_ref(item) for key, item in value.items()
        )
    return isinstance(value, list) and any(_has_ref(item) for item in value)


def map_input_schema(schema: dict):
    if not isinstance(schema, dict) or len(json.dumps(schema).encode()) > MAX_SCHEMA_BYTES:
        raise ValueError("MCP Tool schema 无效或过大")
    if _has_ref(schema):
        raise ValueError("MCP Tool schema 不支持外部引用")
    Draft202012Validator.check_schema(schema)
    props = schema.get("properties", {})
    required = schema.get("required", [])
    if (
        schema.get("type") != "object"
        or not isinstance(props, dict)
        or len(props) > 32
        or not isinstance(required, list)
        or any(name not in props for name in required)
    ):
        raise ValueError("MCP Tool 仅支持有界对象参数")
    type_map = {"string": str, "integer": int, "number": float, "boolean": bool, "array": list}
    fields = {}
    for name, spec in props.items():
        if not isinstance(name, str) or not name.isidentifier() or not isinstance(spec, dict):
            raise ValueError("MCP Tool 参数无效")
        kind = spec.get("type")
        if (
            kind not in type_map
            or _has_ref(spec)
            or kind == "array"
            and spec.get("items", {}).get("type") not in type_map
        ):
            raise ValueError("MCP Tool 参数类型不受支持")
        fields[name] = (
            type_map[kind] if name in required else type_map[kind] | None,
            ... if name in required else None,
        )
    return create_model("McpToolArgs", __config__=ConfigDict(extra="forbid"), **fields)


def _provider(provider_id: str, expected_url: str | None = None) -> dict:
    settings = get_settings()
    provider = settings.mcp_providers.get(provider_id)
    if not isinstance(provider, dict):
        raise ValueError("MCP Provider 未配置")  # noqa: TRY004
    url = provider.get("url")
    if not isinstance(url, str):
        raise ValueError("MCP Provider URL 无效")  # noqa: TRY004
    allowed_hosts = {
        host.strip().lower() for host in settings.mcp_allowed_hosts.split(",") if host.strip()
    }
    validate_provider_url(url, allowed_hosts)
    if expected_url is not None and url != expected_url:
        raise ValueError("MCP Provider 身份或地址已变化，拒绝恢复调用")
    if not isinstance(provider.get("read_only_tools"), list):
        raise ValueError("MCP Provider 缺少只读 Tool 白名单")  # noqa: TRY004
    return provider


@asynccontextmanager
async def _session(provider: dict, timeout: float):
    headers = {"Authorization": f"Bearer {provider['token']}"} if provider.get("token") else None
    async with (
        streamablehttp_client(
            provider["url"],
            headers=headers,
            timeout=timeout,
            sse_read_timeout=timeout,
        ) as (read, write, _session_id),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


async def _listed_tool(session, remote_name: str):
    cursor = None
    for _ in range(5):
        page = await session.list_tools(cursor=cursor)
        for tool in page.tools:
            if tool.name == remote_name:
                annotations = tool.annotations
                if (
                    annotations is None
                    or annotations.readOnlyHint is not True
                    or annotations.destructiveHint is True
                ):
                    raise ValueError("MCP Tool 未声明可信只读属性")
                map_input_schema(tool.inputSchema)
                return tool
        cursor = page.nextCursor
        if not cursor:
            break
    raise ValueError("MCP Tool 未发现")


async def discover_tool(provider_id: str, remote_name: str, timeout: float = 10) -> dict:
    provider = _provider(provider_id)
    if remote_name not in provider["read_only_tools"]:
        raise ValueError("MCP Tool 不在只读白名单")
    async with asyncio.timeout(timeout):
        async with _session(provider, timeout) as session:
            tool = await _listed_tool(session, remote_name)
            return {
                "provider_id": provider_id,
                "server_url": provider["url"],
                "remote_name": remote_name,
                "input_schema": tool.inputSchema,
                "description": tool.description or "",
            }


async def list_available_tools(provider_id: str, timeout: float = 10) -> list[dict]:
    provider = _provider(provider_id)
    allowed = set(provider["read_only_tools"])
    found = []
    async with asyncio.timeout(timeout):
        async with _session(provider, timeout) as session:
            cursor = None
            for _ in range(5):
                page = await session.list_tools(cursor=cursor)
                for tool in page.tools:
                    annotation = tool.annotations
                    if (
                        tool.name in allowed
                        and annotation is not None
                        and annotation.readOnlyHint is True
                        and annotation.destructiveHint is not True
                    ):
                        map_input_schema(tool.inputSchema)
                        found.append(
                            {
                                "name": tool.name,
                                "description": tool.description or "",
                                "input_schema": tool.inputSchema,
                            }
                        )
                cursor = page.nextCursor
                if not cursor:
                    break
    return found


async def call_tool(config: dict, arguments: dict, timeout: float) -> str:
    provider = _provider(config["provider_id"], config["server_url"])
    remote_name = config["remote_name"]
    if remote_name not in provider["read_only_tools"]:
        raise ValueError("MCP Tool 不在只读白名单")
    Draft202012Validator(config["input_schema"]).validate(arguments)
    async with asyncio.timeout(timeout):
        async with _session(provider, timeout) as session:
            live = await _listed_tool(session, remote_name)
            if live.inputSchema != config["input_schema"]:
                raise ValueError("MCP Tool schema 已变化，拒绝旧 Run 调用")
            result = await session.call_tool(
                remote_name, arguments, read_timeout_seconds=timedelta(seconds=timeout)
            )
    if result.isError:
        raise ValueError("MCP Tool 返回错误")
    parts = []
    for block in result.content:
        if block.type != "text":
            raise ValueError("MCP Tool 返回不支持的内容类型")
        parts.append(block.text)
    output = "\n".join(parts)
    if len(output.encode()) > MAX_RESULT_BYTES:
        raise ValueError("MCP Tool 结果超过大小限制")
    return output
