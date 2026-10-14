from dataclasses import dataclass

from app.context.tokens import approximate_tokens
from app.domain.errors import InvalidConfiguration, ModelContextConfigMissing


@dataclass(frozen=True)
class ContextBudget:
    conversation_input_budget: int
    soft_limit: int
    hard_limit: int
    max_compaction_rounds: int
    summary_input_budget: int


def read_model_context(config: dict | None) -> tuple[int, int]:
    values = config or {}
    window = values.get("context_window")
    output = values.get("max_output_tokens")
    if window is None or output is None:
        raise ModelContextConfigMissing("模型缺少 context_window 或 max_output_tokens")
    if _invalid_positive_int(window) or _invalid_positive_int(output):
        raise ModelContextConfigMissing("context_window 和 max_output_tokens 必须是正整数")
    if output >= window:
        raise ModelContextConfigMissing("max_output_tokens 必须小于 context_window")
    return window, output


def _invalid_positive_int(value: object) -> bool:
    return isinstance(value, bool) or not isinstance(value, int) or value <= 0


def build_context_budget(
    *,
    context_window: int,
    max_output_tokens: int,
    rendered_prompt: str,
    tool_schema_tokens: int,
    safety_margin: int,
    soft_limit_ratio: float,
    hard_limit_ratio: float,
    max_compaction_rounds: int,
) -> tuple[dict, dict, ContextBudget]:
    if not 0 < soft_limit_ratio < hard_limit_ratio <= 1:
        raise InvalidConfiguration("上下文压缩阈值配置无效")
    if safety_margin < 0 or max_compaction_rounds < 1:
        raise InvalidConfiguration("上下文预算配置无效")
    prompt_tokens = approximate_tokens(rendered_prompt)
    conversation_input_budget = (
        context_window - max_output_tokens - prompt_tokens - tool_schema_tokens - safety_margin
    )
    summary_input_budget = context_window - max_output_tokens - safety_margin
    policy = {
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
        "soft_limit_ratio": soft_limit_ratio,
        "hard_limit_ratio": hard_limit_ratio,
        "max_compaction_rounds": max_compaction_rounds,
        "safety_margin": safety_margin,
        "token_estimator": "approx_v1",
    }
    numbers = {
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
        "rendered_prompt_tokens": prompt_tokens,
        "tool_schema_tokens": tool_schema_tokens,
        "safety_margin": safety_margin,
        "conversation_input_budget": conversation_input_budget,
        "summary_input_budget": summary_input_budget,
        "soft_limit": int(conversation_input_budget * soft_limit_ratio),
        "hard_limit": int(conversation_input_budget * hard_limit_ratio),
    }
    budget = ContextBudget(
        conversation_input_budget=conversation_input_budget,
        soft_limit=numbers["soft_limit"],
        hard_limit=numbers["hard_limit"],
        max_compaction_rounds=max_compaction_rounds,
        summary_input_budget=summary_input_budget,
    )
    return policy, numbers, budget
