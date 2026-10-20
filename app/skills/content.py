"""Skill 是低信任的 Context Source，不具备执行权限。"""

import hashlib
import json
import re
from copy import deepcopy
from pathlib import PurePosixPath


def validate_resource_path(path: str) -> str:
    if (
        not isinstance(path, str)
        or not path.startswith("references/")
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or PurePosixPath(path).is_absolute()
    ):
        raise ValueError("Skill 资源路径无效")
    return path


def freeze_skill(name: str, body: str, resources: dict[str, str]) -> dict:
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,99}", name):
        raise ValueError("Skill 名称无效")
    if not isinstance(body, str) or not body or len(body.encode()) > 32768:
        raise ValueError("SKILL.md 内容无效或过大")
    if not isinstance(resources, dict) or len(resources) > 32:
        raise ValueError("Skill 资源数量超限")
    for path, content in resources.items():
        validate_resource_path(path)
        if not isinstance(content, str) or len(content.encode()) > 32768:
            raise ValueError("Skill 资源内容无效或过大")
    payload = {"name": name, "body": body, "resources": deepcopy(resources)}
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return {**payload, "content_hash": digest}


def read_skill_content(skills: list[dict], name: str, resource: str | None = None) -> str:
    if resource is not None:
        validate_resource_path(resource)
    for skill in skills:
        if skill["name"] != name:
            continue
        expected = freeze_skill(skill["name"], skill["body"], skill["resources"])
        if expected["content_hash"] != skill["content_hash"]:
            raise ValueError("Skill 内容校验失败")
        if resource is None:
            return skill["body"]
        if resource not in skill["resources"]:
            raise ValueError("Skill 资源不存在")
        return skill["resources"][resource]
    raise ValueError("Skill 不在此 Run 的允许列表中")
