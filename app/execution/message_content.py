"""读取供应商消息中的可展示正文和显式推理，不读取隐藏状态。"""


def model_content(message) -> tuple[str, str]:
    text, reasoning = [], []
    extra = getattr(message, "additional_kwargs", {}) or {}
    if isinstance(extra.get("reasoning_content"), str):
        reasoning.append(extra["reasoning_content"])
    content = message.content
    if isinstance(content, str):
        text.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind in {"text", "output_text"} and isinstance(block.get("text"), str):
                text.append(block["text"])
            elif kind in {"reasoning", "reasoning_content", "thinking"}:
                value = block.get("reasoning") or block.get("thinking") or block.get("text")
                if isinstance(value, str):
                    reasoning.append(value)
                for summary in (
                    block.get("summary", []) if isinstance(block.get("summary"), list) else []
                ):
                    if isinstance(summary, dict) and isinstance(summary.get("text"), str):
                        reasoning.append(summary["text"])
    return "".join(text), "".join(reasoning)
