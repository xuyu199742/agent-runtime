import json
from hashlib import sha256

from app.context.planner import ContextMessage


def context_content_hash(summary_id: str | None, message_ids: list[str], budget: dict) -> str:
    payload = {"budget": budget, "message_ids": message_ids, "summary_id": summary_id}
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
