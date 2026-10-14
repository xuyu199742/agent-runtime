"""模型输入输出的持久化白名单。不要序列化 provider 原始响应。"""

import json
from hashlib import sha256

from langchain_core.messages import BaseMessage

ROLE_NAMES = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}
USAGE_FIELDS = {"input_tokens", "output_tokens", "total_tokens"}
SENSITIVE_KEYS = {"authorization", "api_key", "apikey", "password", "secret", "token"}


def _safe_value(value):
    if isinstance(value, dict):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
            if str(key).lower().replace("-", "_") not in SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _safe_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        )
    return ""


def _safe_tool_calls(message: BaseMessage) -> list[dict]:
    return [
        {
            "id": str(call.get("id") or ""),
            "name": str(call.get("name") or ""),
            "args": _safe_value(call.get("args") or {}),
        }
        for call in getattr(message, "tool_calls", [])
        if isinstance(call, dict)
    ]


def _message_fields(message: BaseMessage) -> dict:
    role = ROLE_NAMES.get(message.type)
    if role is None:
        raise ValueError("不支持持久化的模型消息类型")
    return {
        "role": role,
        "content": _safe_content(message.content),
        "tool_calls": _safe_tool_calls(message),
    }


def serialize_model_input(messages: list[BaseMessage]) -> list[dict]:
    return [_message_fields(message) for message in messages]


def serialize_model_output(message: BaseMessage) -> dict:
    result = _message_fields(message)
    usage = getattr(message, "usage_metadata", None) or {}
    result["usage"] = {
        key: value
        for key, value in usage.items()
        if key in USAGE_FIELDS and isinstance(value, int) and not isinstance(value, bool)
    }
    metadata = getattr(message, "response_metadata", None) or {}
    finish_reason = metadata.get("finish_reason")
    result["finish_reason"] = finish_reason if isinstance(finish_reason, str) else None
    return result


def model_input_hash(messages: list[dict]) -> str:
    canonical = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode()).hexdigest()
