from types import SimpleNamespace

import pytest

from app.application.execution_spec import build_execution_spec
from app.execution.config import resolve_execution_config
from app.runtime.tools.registry import build_tools
from app.skills.content import freeze_skill, read_skill_content


def test_skill_resource_rejects_path_traversal_and_scripts():
    for path in ("../secret", "/tmp/secret", "references/../secret", "scripts/run.py"):
        with pytest.raises(ValueError):
            freeze_skill("guide", "body", {path: "content"})


def test_skill_revision_is_frozen_in_run_and_loaded_on_demand():
    revision = SimpleNamespace(
        revision=1, body="v1 instruction", resources={"references/a.md": "v1"}
    )
    skill = SimpleNamespace(
        id="skill-1",
        name="guide",
        description="Guide",
        when_to_use="When asked",
        enabled=True,
        revisions=[revision],
    )
    agent = SimpleNamespace(
        id="agent-1",
        revision=1,
        system_prompt="System",
        max_model_calls=3,
        max_tool_calls=3,
        max_external_writes=0,
        max_duration_seconds=60,
        tools=[],
        skills=[skill],
    )
    model = SimpleNamespace(
        provider="openai",
        model_name="fake",
        base_url=None,
        api_key_encrypted=None,
        config={"context_window": 8192, "max_output_tokens": 1024},
    )
    draft = build_execution_spec(agent, model)
    assert draft.schema_version == 6
    assert "guide" in draft.snapshot["prompt"]["rendered"]
    assert "v1 instruction" not in draft.snapshot["prompt"]["rendered"]
    revision.body = "v2 instruction"
    revision.resources["references/a.md"] = "v2"
    config = resolve_execution_config(
        SimpleNamespace(schema_version=6, snapshot=draft.snapshot), None, None, None
    )
    assert read_skill_content(config.skills, "guide") == "v1 instruction"
    assert read_skill_content(config.skills, "guide", "references/a.md") == "v1"


@pytest.mark.asyncio
async def test_skill_tool_reads_only_frozen_content():
    frozen = freeze_skill("guide", "body", {"references/a.md": "detail"})
    from app.domain.agent import ToolDefinition

    tool = build_tools(
        [ToolDefinition(name="skill.read", type="NATIVE", config={"skills": [frozen]})]
    )[0]
    assert "body" in await tool.ainvoke({"name": "guide"})
    assert "detail" in await tool.ainvoke({"name": "guide", "resource": "references/a.md"})
    with pytest.raises(ValueError):
        await tool.ainvoke({"name": "guide", "resource": "../secret"})
