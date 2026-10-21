"""可续传的用户活动快照；正文与 trace 索引分离。"""

import json
import re

from sqlalchemy import func, select

from app.context.errors import ContextLeaseLost
from app.persistence.database import RunActivitySnapshot, ToolExecution, new_id
from app.persistence.repositories.traces import ExecutionRecorder

TEXT_LIMIT = 65536
PREVIEW_LIMIT = 8192
TRUNCATED = "\n[内容已截断]"
# 按认证字段语义判断，不将 contentHash、token_count 等普通元数据误判成秘密。
_SENSITIVE_KEYS = {
    "headers",
    "requestheaders",
    "responseheaders",
    "auth",
    "authentication",
    "authorization",
    "proxyauthorization",
    "authkey",
    "apikey",
    "xapikey",
    "accesskey",
    "accesskeyid",
    "secretaccesskey",
    "awsaccesskeyid",
    "awssecretaccesskey",
    "password",
    "passwd",
    "passphrase",
    "secret",
    "clientsecret",
    "credential",
    "credentials",
    "privatekey",
    "token",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "authtoken",
    "bearertoken",
    "sessionid",
    "sessionkey",
    "sessiontoken",
    "cookie",
    "setcookie",
    "csrftoken",
    "xsrftoken",
    "xauthtoken",
}
# 字符串可能来自非 JSON 的工具结果，兼容 snake_case、camelCase 和常见 HTTP 字段。
_KEY_PATTERN = "|".join(
    "[-_.]?".join(name) for name in sorted(_SENSITIVE_KEYS, key=len, reverse=True)
)
_SECRET_ASSIGNMENT = re.compile(
    rf"(?i)(?<![\w])([\"']?(?:{_KEY_PATTERN})[\"']?\s*[=:]\s*)"
    r"(?:\[已脱敏\]|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;&}\]]+)"
)


def _sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return normalized in _SENSITIVE_KEYS or normalized.endswith(
        (
            "auth",
            "password",
            "passwd",
            "secret",
            "token",
            "apikey",
            "accesskey",
            "privatekey",
            "credential",
            "credentials",
            "sessionid",
        )
    )


def bounded(text: str, limit: int = TEXT_LIMIT) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[: limit - len(TRUNCATED.encode())].decode("utf-8", errors="ignore") + TRUNCATED


def preview(value, depth: int = 0):
    """有界预览；递归移除认证字段，字符串内 JSON 同样检查。"""
    if depth > 5:
        return "[嵌套内容已截断]"
    if isinstance(value, dict):
        result = {
            str(key)[:100]: "[已脱敏]" if _sensitive_key(str(key)) else preview(item, depth + 1)
            for key, item in list(value.items())[:50]
        }
        return (
            result
            if len(json.dumps(result, ensure_ascii=False).encode()) <= PREVIEW_LIMIT
            else bounded(json.dumps(result, ensure_ascii=False), PREVIEW_LIMIT)
        )
    if isinstance(value, (list, tuple)):
        return preview({str(i): item for i, item in enumerate(value[:30])}, depth + 1)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return preview(parsed, depth + 1)
        text = re.sub(r"(?i)\b(Bearer|Basic)\s+[^\s\"']+", r"\1 [已脱敏]", value)
        text = re.sub(
            r"(?i)(\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:\s*)[^\r\n]*",
            r"\1[已脱敏]",
            text,
        )
        text = _SECRET_ASSIGNMENT.sub(r"\1[已脱敏]", text)
        return bounded(text, PREVIEW_LIMIT)
    return value if value is None or isinstance(value, (int, float, bool)) else "[不支持的预览类型]"


async def append_snapshot(db, run_id, worker_id, activity_id, kind, content):
    recorder = ExecutionRecorder(db)
    row = RunActivitySnapshot(
        id=new_id(),
        run_id=run_id,
        sequence=0,
        activity_id=activity_id,
        activity_type=kind,
        content=content,
    )
    sequence = await recorder.append(
        run_id,
        "activity.updated",
        {},
        worker_id=worker_id,
        ref_type="activity_snapshot",
        ref_id=row.id,
    )
    if sequence is None:
        raise ContextLeaseLost
    row.sequence = sequence
    db.add(row)


async def latest_snapshot(db, run_id, activity_id):
    return await db.scalar(
        select(RunActivitySnapshot)
        .where(RunActivitySnapshot.run_id == run_id, RunActivitySnapshot.activity_id == activity_id)
        .order_by(RunActivitySnapshot.sequence.desc())
        .limit(1)
    )


def legacy_tool_content(row):
    """只展示旧事实已有字段；旧版本未保存输入或 Skill 元数据。"""
    return {
        "name": row.tool_name,
        "toolCallId": row.tool_call_id,
        "status": "RUNNING" if row.status == "STARTED" else row.status,
        "input": None,
        "output": preview(row.result_content),
        "error": row.error_code,
    }


async def activity_items(db, run_id):
    latest = (
        select(func.max(RunActivitySnapshot.sequence))
        .where(RunActivitySnapshot.run_id == run_id)
        .group_by(RunActivitySnapshot.activity_id)
    )
    rows = (
        await db.scalars(
            select(RunActivitySnapshot)
            .where(
                RunActivitySnapshot.run_id == run_id,
                RunActivitySnapshot.sequence.in_(latest),
            )
            .order_by(RunActivitySnapshot.sequence)
        )
    ).all()
    items = [
        {"id": row.activity_id, "type": row.activity_type, "content": row.content} for row in rows
    ]
    snapshot_ids = {item["id"] for item in items}
    legacy_tools = (
        await db.scalars(
            select(ToolExecution)
            .where(
                ToolExecution.run_id == run_id,
            )
            .order_by(ToolExecution.started_at, ToolExecution.id)
        )
    ).all()
    # 旧事实先于新快照；同一调用只保留新活动，禁止旧结果覆盖新状态。
    return [
        {"id": f"tool:{tool.tool_call_id}", "type": "tool", "content": legacy_tool_content(tool)}
        for tool in legacy_tools
        if f"tool:{tool.tool_call_id}" not in snapshot_ids
    ] + items
