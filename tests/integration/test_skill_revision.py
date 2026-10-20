import os
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.catalog import AgentInput, CatalogService
from app.application.execution_spec import build_execution_spec
from app.execution.config import resolve_execution_config
from app.persistence.database import ModelConfig, Skill, SkillRevision
from app.persistence.repositories.catalog import CatalogRepository
from app.skills.content import freeze_skill, read_skill_content


async def test_run_keeps_skill_revision_after_new_publish():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]
    try:
        async with factory() as db:
            model = ModelConfig(
                name=f"skill-model-{suffix}",
                provider="openai",
                model_name="fake",
                config={"context_window": 8192, "max_output_tokens": 1024},
            )
            skill = Skill(name=f"skill-{suffix}", description="描述", when_to_use="需要时")
            db.add_all([model, skill])
            await db.flush()
            v1 = freeze_skill(skill.name, "v1 body", {"references/a.md": "v1 resource"})
            db.add(
                SkillRevision(
                    skill_id=skill.id,
                    revision=1,
                    body=v1["body"],
                    resources=v1["resources"],
                    content_hash=v1["content_hash"],
                )
            )
            await db.commit()
            agent = await CatalogService(CatalogRepository(db)).save_agent(
                AgentInput(
                    name=f"agent-{suffix}",
                    description="",
                    system_prompt="system",
                    model_id=model.id,
                    max_model_calls=3,
                    enabled=True,
                    tool_ids=[],
                    skill_ids=[skill.id],
                )
            )
            loaded = await db.get(type(agent), agent.id)
            assert loaded.skills[0].id == skill.id
            draft = build_execution_spec(loaded, model)
            assert draft.schema_version == 6
            v2 = freeze_skill(skill.name, "v2 body", {"references/a.md": "v2 resource"})
            db.add(
                SkillRevision(
                    skill_id=skill.id,
                    revision=2,
                    body=v2["body"],
                    resources=v2["resources"],
                    content_hash=v2["content_hash"],
                )
            )
            await db.commit()
            config = resolve_execution_config(
                type("Spec", (), {"schema_version": 6, "snapshot": draft.snapshot})(),
                None,
                None,
                None,
            )
            assert read_skill_content(config.skills, skill.name) == "v1 body"
            assert read_skill_content(config.skills, skill.name, "references/a.md") == "v1 resource"
            rows = (
                await db.scalars(select(SkillRevision).where(SkillRevision.skill_id == skill.id))
            ).all()
            assert sorted(row.revision for row in rows) == [1, 2]
    finally:
        await engine.dispose()
