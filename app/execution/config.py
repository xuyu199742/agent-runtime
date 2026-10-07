from dataclasses import dataclass, field

from app.domain.agent import ToolDefinition
from app.execution.draft import ExecutionSpecDraft

RUNTIME_VERSION = "0.3"


@dataclass(frozen=True)
class ResolvedExecutionConfig:
    schema_version: int
    system_prompt: str
    max_model_calls: int
    provider: str
    model_name: str
    base_url: str | None
    model_options: dict
    api_key_encrypted: str | None
    enabled: bool
    tools: list[dict] = field(default_factory=list)
    v1_max_messages: int | None = None
    v1_max_tokens: int | None = None
    context_policy: dict | None = None
    context_budget: dict | None = None

    def tool_definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=tool["name"],
                type=tool["type"],
                description=tool.get("description") or "",
                config=tool.get("config") or {},
                policy=tool.get("policy") or {},
                enabled=True,
            )
            for tool in self.tools
        ]


def redact_execution_snapshot(snapshot: dict) -> dict:
    model = dict(snapshot.get("model") or {})
    model.pop("api_key_encrypted", None)
    return {**snapshot, "model": model}


def resolve_execution_config(spec, agent, model, settings) -> ResolvedExecutionConfig:
    if spec is None:
        return _from_live_agent(agent, model, settings)
    if spec.schema_version == 1:
        return _from_v1(spec.snapshot)
    if spec.schema_version == 2:
        return _from_v2(spec.snapshot)
    raise ValueError(f"不支持的 ExecutionSpec schema_version: {spec.schema_version}")


def execution_spec_from_draft(draft: ExecutionSpecDraft):
    from app.persistence.database import ExecutionSpec, new_id

    return ExecutionSpec(
        id=new_id(),
        agent_id=draft.agent_id,
        agent_revision=draft.agent_revision,
        schema_version=draft.schema_version,
        runtime_version=draft.runtime_version,
        snapshot=draft.snapshot,
    )


def _model_fields(model: dict, *, enabled: bool) -> dict:
    return {
        "provider": model["provider"],
        "model_name": model["model_name"],
        "base_url": model.get("base_url"),
        "model_options": model.get("config") or {},
        "api_key_encrypted": model.get("api_key_encrypted"),
        "enabled": enabled,
    }


def _from_v1(snapshot: dict) -> ResolvedExecutionConfig:
    context = snapshot.get("context") or {}
    return ResolvedExecutionConfig(
        schema_version=1,
        system_prompt=snapshot["system_prompt"],
        max_model_calls=snapshot["max_model_calls"],
        tools=list(snapshot.get("tools") or []),
        v1_max_messages=context.get("max_messages"),
        v1_max_tokens=context.get("max_tokens"),
        **_model_fields(snapshot["model"], enabled=True),
    )


def _from_v2(snapshot: dict) -> ResolvedExecutionConfig:
    return ResolvedExecutionConfig(
        schema_version=2,
        system_prompt=snapshot["prompt"]["rendered"],
        max_model_calls=snapshot["max_model_calls"],
        tools=list(snapshot.get("tools") or []),
        context_policy=dict(snapshot["context_policy"]),
        context_budget=dict(snapshot["context_budget"]),
        **_model_fields(snapshot["model"], enabled=True),
    )


def _from_live_agent(agent, model, settings) -> ResolvedExecutionConfig:
    tools = [
        {
            "name": tool.name,
            "type": tool.type,
            "description": tool.description,
            "config": tool.config,
            "policy": tool.policy,
            "effect_type": getattr(tool, "effect_type", "READ_ONLY"),
            "failure_policy": getattr(tool, "failure_policy", "RETURN_ERROR"),
        }
        for tool in agent.tools
    ]
    return ResolvedExecutionConfig(
        schema_version=1,
        system_prompt=agent.system_prompt,
        max_model_calls=agent.max_model_calls,
        provider=model.provider,
        model_name=model.model_name,
        base_url=model.base_url,
        model_options=model.config or {},
        api_key_encrypted=model.api_key_encrypted,
        enabled=model.enabled,
        tools=tools,
        v1_max_messages=settings.context_max_messages,
        v1_max_tokens=settings.context_max_tokens,
    )
