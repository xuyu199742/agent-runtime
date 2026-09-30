"""Run 配置快照；密钥只保存既有密文，不写明文。"""

from hashlib import sha256

from app.config import get_settings
from app.persistence.database import ExecutionSpec, new_id

RUNTIME_VERSION = "0.2"


def freeze_execution_spec(agent, model) -> ExecutionSpec:
    settings = get_settings()
    prompt = agent.system_prompt
    return ExecutionSpec(
        id=new_id(),
        agent_id=agent.id,
        agent_revision=agent.revision,
        runtime_version=RUNTIME_VERSION,
        snapshot={
            "system_prompt": prompt,
            "prompt_hash": sha256(prompt.encode()).hexdigest(),
            "max_model_calls": agent.max_model_calls,
            "model": {
                "provider": model.provider,
                "model_name": model.model_name,
                "base_url": model.base_url,
                "config": model.config,
                "api_key_encrypted": model.api_key_encrypted,
            },
            "tools": [
                {
                    "name": tool.name,
                    "type": tool.type,
                    "description": tool.description,
                    "config": tool.config,
                    "policy": tool.policy,
                    "effect_type": tool.effect_type,
                    "failure_policy": tool.failure_policy,
                }
                for tool in sorted(agent.tools, key=lambda item: item.id)
            ],
            "context": {
                "max_messages": settings.context_max_messages,
                "max_tokens": settings.context_max_tokens,
            },
        },
    )
