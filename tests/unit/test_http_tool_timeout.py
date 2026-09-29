import asyncio

import pytest

from app.runtime.tools import http_request


async def test_http_timeout_covers_dns_resolution(monkeypatch):
    async def slow_dns(_host):
        await asyncio.sleep(0.05)

    monkeypatch.setattr(http_request, "_check_public_host", slow_dns)
    tool = http_request.http_tool({"example.com"}, timeout_seconds=0.01)
    with pytest.raises(TimeoutError):
        await tool.ainvoke({"url": "https://example.com/"})
