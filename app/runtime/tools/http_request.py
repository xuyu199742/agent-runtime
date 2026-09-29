import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from langchain_core.tools import BaseTool, StructuredTool


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
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=timeout_seconds, trust_env=False
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text[:20000]

    return StructuredTool.from_function(
        coroutine=http_request,
        name="http_request",
        description="通过 HTTPS GET 请求服务端允许的公开域名。",
    )
