from app.config import get_settings
from app.context.budget import build_context_budget, read_model_context
from app.domain.agent import ToolDefinition
from app.execution.config import RUNTIME_VERSION
from app.execution.draft import ExecutionSpecDraft
from app.prompt.assembler import assemble
from app.runtime.tools.schema_tokens import tool_schema_tokens


def build_execution_spec(agent, model) -> ExecutionSpecDraft:
    """在 Run 创建时冻结提示词、模型、工具和上下文预算。不读取进程级 token 上限。"""
    window, output = read_model_context(model.config)
    settings = get_settings()
    definitions = [
        ToolDefinition(
            name=tool.name,
            type=tool.type,
            description=getattr(tool, "description", "") or "",
            config=getattr(tool, "config", None) or {},
            policy=getattr(tool, "policy", None) or {},
            enabled=getattr(tool, "enabled", True),
            effect_type=getattr(tool, "effect_type", "READ_ONLY"),
            failure_policy=getattr(tool, "failure_policy", "RETURN_ERROR"),
        )
        for tool in sorted(agent.tools, key=lambda item: getattr(item, "id", item.name))
    ]
    environment = (
        f"runtime_version={RUNTIME_VERSION}\nprovider={model.provider}\nmodel={model.model_name}"
    )
    bundle = assemble(
        instruction=agent.system_prompt or "",
        revision=agent.revision,
        environment=environment,
    )
    policy, numbers, _budget = build_context_budget(
        context_window=window,
        max_output_tokens=output,
        rendered_prompt=bundle.rendered,
        tool_schema_tokens=tool_schema_tokens(definitions),
        safety_margin=settings.context_safety_margin,
        soft_limit_ratio=settings.context_soft_limit_ratio,
        hard_limit_ratio=settings.context_hard_limit_ratio,
        max_compaction_rounds=settings.context_max_compaction_rounds,
    )
    tools = [
        {
            "name": tool.name,
            "type": tool.type,
            "description": getattr(tool, "description", "") or "",
            "config": getattr(tool, "config", None) or {},
            "policy": getattr(tool, "policy", None) or {},
            "effect_type": getattr(tool, "effect_type", "READ_ONLY"),
            "failure_policy": getattr(tool, "failure_policy", "RETURN_ERROR"),
        }
        for tool in sorted(agent.tools, key=lambda item: getattr(item, "id", item.name))
    ]
    return ExecutionSpecDraft(
        agent_id=agent.id,
        agent_revision=agent.revision,
        schema_version=3 if any(tool["effect_type"] == "EXTERNAL_WRITE" for tool in tools) else 2,
        runtime_version=RUNTIME_VERSION,
        snapshot={
            "max_model_calls": agent.max_model_calls,
            "prompt": bundle.snapshot(),
            "model": {
                "provider": model.provider,
                "model_name": model.model_name,
                "base_url": model.base_url,
                "config": model.config or {},
                "api_key_encrypted": model.api_key_encrypted,
            },
            "tools": tools,
            "context_policy": policy,
            "context_budget": numbers,
        },
    )
