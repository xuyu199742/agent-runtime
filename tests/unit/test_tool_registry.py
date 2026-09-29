import asyncio
import time

import pytest

from app.persistence.database import ToolDefinition
from app.runtime.tools import registry


async def test_database_description_and_timeout_build_native_tool(monkeypatch):
    definition = ToolDefinition(
        name="calculator",
        type="NATIVE",
        description="数据库配置的计算说明",
        config={"timeout_seconds": 0.01},
        enabled=True,
    )

    def slow_calculate(_expression):
        time.sleep(0.05)
        return "2"

    monkeypatch.setattr(registry, "calculate", slow_calculate, raising=False)
    tool = registry.build_tools([definition])[0]
    assert tool.description == "数据库配置的计算说明"
    with pytest.raises(asyncio.TimeoutError):
        await tool.ainvoke({"expression": "1+1"})


def test_http_policy_hosts_participate_in_tool_build(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        registry, "get_settings", lambda: SimpleNamespace(http_tool_allowed_hosts="example.com")
    )
    definition = ToolDefinition(
        name="http_request",
        type="HTTP",
        description="只访问指定域名",
        config={},
        policy={"allowed_hosts": ["example.com"]},
        enabled=True,
    )
    tool = registry.build_tools([definition])[0]
    assert tool.name == "http_request"
    assert tool.description == "只访问指定域名"


def test_future_side_effect_tool_has_stable_invocation_key():
    assert registry.tool_idempotency_key("run-1", "call-2") == "run-1:call-2"
