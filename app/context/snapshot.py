import json
from hashlib import sha256

from app.context.planner import ContextMessage


def context_content_hash(
    summary_id: str | None,
    summary_text: str | None,
    messages: list[ContextMessage],
    budget: dict,
) -> str:
    """哈希覆盖摘要正文和原始消息正文，恢复时可以核对文本没有变化。"""
    payload = {
        "budget": budget,
        "messages": [
            {"content": message.content, "id": message.id, "role": message.role}
            for message in messages
        ],
        "summary_id": summary_id,
        "summary_text": summary_text or "",
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return sha256(canonical.encode()).hexdigest()


def render_context(
    summary_text: str | None, messages: list[ContextMessage]
) -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    if summary_text:
        turns.append(("user", "以下是此前对话的摘要，被覆盖的原文不再重复：\n" + summary_text))
    for message in messages:
        role = "assistant" if message.role == "assistant" else "user"
        turns.append((role, message.content))
    return turns
