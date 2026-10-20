"""Skill 元数据与不可变版本管理。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.application.auth import Principal
from app.domain.errors import NotFound
from app.persistence.database import Skill, SkillRevision
from app.skills.content import freeze_skill
from app.transport.http.common import Audit, Db
from app.transport.http.v1.admin.common import record_action
from app.transport.http.v1.dependencies import require

router = APIRouter(prefix="/api/v1/admin/skills", tags=["admin-skills"])
Viewer = Annotated[Principal, Depends(require("agent:view"))]
Editor = Annotated[Principal, Depends(require("agent:update"))]


class SkillInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    when_to_use: str = Field(default="", max_length=1000)
    body: str = Field(min_length=1)
    resources: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_content(self):
        freeze_skill(self.name, self.body, self.resources)
        return self


class RevisionInput(BaseModel):
    body: str = Field(min_length=1)
    resources: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_content(self):
        freeze_skill("validation", self.body, self.resources)
        return self


class SkillMetadataIn(BaseModel):
    description: str = Field(default="", max_length=1000)
    when_to_use: str = Field(default="", max_length=1000)
    enabled: bool = True


def _metadata(skill: Skill) -> dict:
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "when_to_use": skill.when_to_use,
        "enabled": skill.enabled,
        "current_revision": max((row.revision for row in skill.revisions), default=0),
    }


async def _get(db: Db, skill_id: str) -> Skill:
    skill = await db.get(Skill, skill_id)
    if skill is None:
        raise NotFound("Skill 不存在")
    return skill


@router.get("")
async def list_skills(_user: Viewer, db: Db):
    rows = (await db.scalars(select(Skill).order_by(Skill.name))).all()
    return [_metadata(skill) for skill in rows]


@router.get("/{skill_id}")
async def detail(skill_id: str, _user: Viewer, db: Db):
    return _metadata(await _get(db, skill_id))


@router.get("/{skill_id}/revisions")
async def revisions(skill_id: str, _user: Viewer, db: Db):
    skill = await _get(db, skill_id)
    return [
        {
            "revision": row.revision,
            "body": row.body,
            "resources": row.resources,
            "content_hash": row.content_hash,
            "created_at": row.created_at,
        }
        for row in sorted(skill.revisions, key=lambda item: item.revision)
    ]


@router.post("", status_code=201)
async def create(body: SkillInput, user: Editor, db: Db, audit: Audit, request: Request):
    frozen = freeze_skill(body.name, body.body, body.resources)
    skill = Skill(
        name=body.name,
        description=body.description,
        when_to_use=body.when_to_use,
        enabled=body.enabled,
    )
    db.add(skill)
    await db.flush()
    db.add(
        SkillRevision(
            skill_id=skill.id,
            revision=1,
            body=frozen["body"],
            resources=frozen["resources"],
            content_hash=frozen["content_hash"],
        )
    )
    await db.commit()
    await db.refresh(skill)
    await record_action(audit, request, user, "skill:create", "skill", skill.id)
    return _metadata(skill)


@router.post("/{skill_id}/revisions", status_code=201)
async def publish_revision(
    skill_id: str, body: RevisionInput, user: Editor, db: Db, audit: Audit, request: Request
):
    skill = await _get(db, skill_id)
    frozen = freeze_skill(skill.name, body.body, body.resources)
    revision = max((row.revision for row in skill.revisions), default=0) + 1
    db.add(
        SkillRevision(
            skill_id=skill.id,
            revision=revision,
            body=frozen["body"],
            resources=frozen["resources"],
            content_hash=frozen["content_hash"],
        )
    )
    await db.commit()
    await record_action(
        audit, request, user, "skill:publish", "skill", skill.id, {"revision": revision}
    )
    return {"revision": revision, "content_hash": frozen["content_hash"]}


@router.put("/{skill_id}")
async def update_metadata(
    skill_id: str, body: SkillMetadataIn, user: Editor, db: Db, audit: Audit, request: Request
):
    skill = await _get(db, skill_id)
    skill.description = body.description
    skill.when_to_use = body.when_to_use
    skill.enabled = body.enabled
    await db.commit()
    await record_action(audit, request, user, "skill:update", "skill", skill.id)
    return _metadata(skill)
