from types import SimpleNamespace

import pytest

from app.application.catalog import CatalogService
from app.domain.errors import Conflict


async def test_admin_tool_test_uses_factory_and_blocks_approval(monkeypatch):
    tool = SimpleNamespace(
        name="echo",
        type="NATIVE",
        description="回显",
        config={"timeout_seconds": 1},
        policy={},
        effect_type="READ_ONLY",
        enabled=True,
        archived_at=None,
    )
    catalog = CatalogService(None)

    async def get_tool(_tool_id):
        return tool

    monkeypatch.setattr(catalog, "get_tool", get_tool)
    assert await catalog.test_tool("echo-id", {"text": "hello"}) == {
        "success": True,
        "result": "hello",
    }
    tool.policy = {"requires_approval": True}
    with pytest.raises(Conflict):
        await catalog.test_tool("echo-id", {"text": "hello"})
