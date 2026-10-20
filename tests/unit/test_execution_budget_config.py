from types import SimpleNamespace

from app.application.execution_spec import build_execution_spec
from app.execution.config import resolve_execution_config


def test_new_run_freezes_execution_budget_and_tool_policy():
    agent = SimpleNamespace(
        id="agent-1",
        revision=1,
        system_prompt="测试",
        max_model_calls=5,
        max_tool_calls=2,
        max_external_writes=1,
        max_duration_seconds=90,
        tools=[
            SimpleNamespace(
                id="tool-1",
                name="echo",
                type="NATIVE",
                description="echo",
                config={},
                policy={"requires_approval": True},
                effect_type="READ_ONLY",
                failure_policy="RETURN_ERROR",
                enabled=True,
            )
        ],
    )
    model = SimpleNamespace(
        provider="openai",
        model_name="fake",
        base_url=None,
        api_key_encrypted=None,
        config={"context_window": 8192, "max_output_tokens": 1024},
    )
    draft = build_execution_spec(agent, model)
    assert draft.schema_version == 5
    assert draft.snapshot["working_context"] == {
        "strategy_version": 1,
        "recent_complete_turns": 1,
    }
    assert draft.snapshot["execution_budget"] == {
        "max_model_calls": 5,
        "max_tool_calls": 2,
        "max_external_writes": 1,
        "max_duration_seconds": 90,
    }
    agent.max_tool_calls = 99
    agent.tools[0].policy = {"requires_approval": False}
    config = resolve_execution_config(
        SimpleNamespace(schema_version=draft.schema_version, snapshot=draft.snapshot),
        None,
        None,
        None,
    )
    assert config.execution_budget.max_tool_calls == 2
    assert config.working_context == draft.snapshot["working_context"]
    assert config.tools[0]["policy"]["requires_approval"] is True


def test_legacy_spec_keeps_legacy_budget_behavior():
    snapshot = {
        "max_model_calls": 3,
        "prompt": {"rendered": ""},
        "model": {"provider": "openai", "model_name": "fake"},
        "tools": [],
        "context_policy": {},
        "context_budget": {},
    }
    for version in (2, 3):
        config = resolve_execution_config(
            SimpleNamespace(schema_version=version, snapshot=snapshot), None, None, None
        )
        assert config.execution_budget is None
        assert config.max_model_calls == 3


def test_v4_spec_does_not_enable_working_context():
    snapshot = {
        "max_model_calls": 3,
        "prompt": {"rendered": ""},
        "model": {"provider": "openai", "model_name": "fake"},
        "tools": [],
        "context_policy": {},
        "context_budget": {},
        "execution_budget": {
            "max_model_calls": 3,
            "max_tool_calls": 3,
            "max_external_writes": 0,
            "max_duration_seconds": 60,
        },
    }
    config = resolve_execution_config(
        SimpleNamespace(schema_version=4, snapshot=snapshot), None, None, None
    )
    assert config.working_context is None
