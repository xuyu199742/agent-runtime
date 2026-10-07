import json
from collections.abc import Sequence

from app.context.tokens import approximate_tokens
from app.domain.agent import ToolDefinition
from app.runtime.tools.registry import build_tools


def tool_schema_tokens(definitions: Sequence[ToolDefinition]) -> int:
    """按真正交给模型的工具 schema 估算，不用数据库字段猜测。"""
    if not definitions:
        return 0
    rendered = []
    for tool in build_tools(definitions):
        args_schema = getattr(tool, "args_schema", None)
        if hasattr(args_schema, "model_json_schema"):
            parameters = args_schema.model_json_schema()
        else:
            parameters = {}
        rendered.append(
            json.dumps(
                {"name": tool.name, "description": tool.description, "parameters": parameters},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return approximate_tokens("\n".join(rendered))
