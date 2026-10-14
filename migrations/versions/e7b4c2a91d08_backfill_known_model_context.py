"""backfill published context limits for known models

Revision ID: e7b4c2a91d08
Revises: c31a7e5b90d2

只补齐模型标识已经公布上限、且配置里还缺字段的行。
未知模型保持原样，避免把同一组数字写给所有模型。
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7b4c2a91d08"
down_revision: str | Sequence[str] | None = "c31a7e5b90d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 迁移必须自包含，避免以后运行时代码更新改变历史迁移的结果。
# 来源：https://api-docs.deepseek.com/api/list-models/
PUBLISHED_MODEL_CONTEXT = {
    "deepseek-flash": (1_048_576, 393_216),
    "deepseek-v4-flash": (1_048_576, 393_216),
    "deepseek-v4-flash-vision-exp": (1_048_576, 393_216),
    "deepseek-v4-pro": (1_048_576, 393_216),
}


def _fill_known_model_context(config: dict | None, model_name: str) -> dict | None:
    published = PUBLISHED_MODEL_CONTEXT.get(model_name)
    if published is None:
        return None
    values = dict(config or {})
    if values.get("context_window") is not None and values.get("max_output_tokens") is not None:
        return None
    window = values.get("context_window", published[0])
    output = values.get("max_output_tokens", published[1])
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in (window, output)
    ):
        return None
    if output >= window:
        return None
    values["context_window"] = window
    values["max_output_tokens"] = output
    return values


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, model_name, config FROM model_configs")).mappings()
    for row in rows:
        updated = _fill_known_model_context(dict(row["config"] or {}), row["model_name"])
        if updated is None:
            continue
        bind.execute(
            sa.text("UPDATE model_configs SET config = CAST(:config AS json) WHERE id = :id"),
            {"config": json.dumps(updated, ensure_ascii=False), "id": row["id"]},
        )


def downgrade() -> None:
    # 无法区分迁移回填值和迁移前已有的相同配置；降级仅移动版本，不删除模型设置。
    pass
