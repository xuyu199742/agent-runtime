"""已公布的模型上下文上限。只用于补齐对应模型的存量配置，不作为全局默认值。"""

# 数字来自 DeepSeek API 模型表：上下文 1M，最大输出 384K（393216）。
# deepseek-v4-flash 与 deepseek-v4-flash-vision-exp 已由 deepseek-flash 承接。
PUBLISHED_MODEL_CONTEXT: dict[str, tuple[int, int]] = {
    "deepseek-flash": (1_048_576, 393_216),
    "deepseek-v4-flash": (1_048_576, 393_216),
    "deepseek-v4-flash-vision-exp": (1_048_576, 393_216),
    "deepseek-v4-pro": (1_048_576, 393_216),
}


def fill_known_model_context(config: dict | None, model_name: str) -> dict | None:
    """缺少上限时，只补这个模型自己公布的数字。未知模型返回 None。"""
    published = PUBLISHED_MODEL_CONTEXT.get(model_name)
    if published is None:
        return None
    values = dict(config or {})
    window = values.get("context_window", published[0])
    output = values.get("max_output_tokens", published[1])
    if values.get("context_window") is not None and values.get("max_output_tokens") is not None:
        return None
    if _invalid(window) or _invalid(output) or output >= window:
        return None
    values["context_window"] = window
    values["max_output_tokens"] = output
    return values


def _invalid(value: object) -> bool:
    return isinstance(value, bool) or not isinstance(value, int) or value <= 0
