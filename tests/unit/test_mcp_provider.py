from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations
from pydantic import ValidationError

from app.domain.agent import ToolDefinition
from app.runtime.mcp import map_input_schema, validate_provider_url
from app.runtime.tools.registry import build_tools
from app.transport.schemas.legacy import ToolIn


def test_mcp_url_requires_https_and_explicit_host():
    assert (
        validate_provider_url("https://mcp.example.com/mcp", {"mcp.example.com"})
        == "mcp.example.com"
    )
    for url in (
        "http://mcp.example.com/mcp",
        "https://127.0.0.1/mcp",
        "https://user@mcp.example.com/mcp",
        "https://other.example.com/mcp",
    ):
        with pytest.raises(ValueError):
            validate_provider_url(url, {"mcp.example.com"})


def test_mcp_schema_mapping_rejects_external_refs_and_unknown_types():
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["query"],
        "additionalProperties": False,
    }
    model = map_input_schema(schema)
    assert model.model_json_schema()["properties"]["query"]["type"] == "string"
    assert model(query="a", limit=2).model_dump(exclude_none=True) == {"query": "a", "limit": 2}
    with pytest.raises(ValidationError):
        model(query="a", arbitrary="bad")
    with pytest.raises(ValueError):
        map_input_schema({"type": "object", "$ref": "https://evil.test/schema"})
    with pytest.raises(ValueError):
        map_input_schema({"type": "object", "properties": {"nested": {"type": "object"}}})


@pytest.mark.asyncio
async def test_mcp_tool_uses_frozen_schema_and_common_tool_interface(monkeypatch):
    calls = []

    async def fake_call(config, arguments, timeout):
        calls.append((config["remote_name"], arguments, timeout))
        return "found"

    monkeypatch.setattr("app.runtime.tools.registry.call_mcp_tool", fake_call)
    tool = build_tools(
        [
            ToolDefinition(
                name="lookup",
                type="MCP",
                effect_type="READ_ONLY",
                config={
                    "provider_id": "example",
                    "server_url": "https://mcp.example.com/mcp",
                    "remote_name": "search",
                    "timeout_seconds": 4,
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            )
        ]
    )[0]
    assert await tool.ainvoke({"query": "test"}) == "found"
    assert calls == [("search", {"query": "test"}, 4.0)]
    with pytest.raises(ValidationError):
        await tool.ainvoke({"unknown": "bad"})


@pytest.mark.asyncio
async def test_mcp_call_rechecks_readonly_identity_schema_and_output(monkeypatch):
    from app.runtime import mcp

    schema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    provider = {
        "url": "https://mcp.example.com/mcp",
        "token": "secret",
        "read_only_tools": ["search"],
    }
    monkeypatch.setattr(
        mcp,
        "get_settings",
        lambda: SimpleNamespace(
            mcp_providers={"example": provider}, mcp_allowed_hosts="mcp.example.com"
        ),
    )
    calls = []

    class Session:
        async def list_tools(self, cursor=None):
            return ListToolsResult(
                tools=[
                    Tool(
                        name="search",
                        inputSchema=schema,
                        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
                    )
                ]
            )

        async def call_tool(self, name, arguments, read_timeout_seconds):
            calls.append((name, arguments))
            return CallToolResult(content=[TextContent(type="text", text="result")])

    @asynccontextmanager
    async def session(_provider, _timeout):
        yield Session()

    monkeypatch.setattr(mcp, "_session", session)
    config = {
        "provider_id": "example",
        "server_url": provider["url"],
        "remote_name": "search",
        "input_schema": schema,
    }
    assert await mcp.call_tool(config, {"query": "hello"}, 5) == "result"
    assert calls == [("search", {"query": "hello"})]
    with pytest.raises(ValueError):
        await mcp.call_tool(
            {**config, "server_url": "https://other.example.com/mcp"}, {"query": "x"}, 5
        )
    with pytest.raises(ValueError):
        await mcp.call_tool({**config, "remote_name": "delete"}, {"query": "x"}, 5)


def test_mcp_admin_input_cannot_enable_write_effect():
    with pytest.raises(ValidationError):
        ToolIn(
            name="delete",
            type="MCP",
            effect_type="EXTERNAL_WRITE",
            config={"provider_id": "example", "remote_name": "delete"},
        )
