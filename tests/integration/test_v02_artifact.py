import os
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.application.artifacts import ArtifactService
from app.infrastructure.artifact_storage import LocalArtifactStorage
from app.infrastructure.passwords import hash_password
from app.main import app
from app.persistence.database import AgentDefinition, ModelConfig, Session, User, get_db
from app.persistence.repositories.artifacts import ArtifactRepository
from app.transport.http.common import artifact_service


async def test_artifact_storage_and_client_ownership():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]
    with TemporaryDirectory() as directory:
        storage = LocalArtifactStorage(directory)

        async def override_db():
            async with factory() as db:
                yield db

        def override_artifacts(db: Annotated[AsyncSession, Depends(override_db)]):
            return ArtifactService(ArtifactRepository(db), storage)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[artifact_service] = override_artifacts
        try:
            async with factory() as db:
                model = ModelConfig(
                    name=f"artifact-model-{suffix}", provider="openai", model_name="fake"
                )
                db.add(model)
                await db.flush()
                agent = AgentDefinition(name=f"artifact-agent-{suffix}", model_id=model.id)
                db.add(agent)
                await db.flush()
                alice = User(
                    username=f"artifact-alice-{suffix}",
                    display_name="Alice",
                    password_hash=hash_password("artifact-alice-secret"),
                )
                bob = User(
                    username=f"artifact-bob-{suffix}",
                    display_name="Bob",
                    password_hash=hash_password("artifact-bob-secret-12"),
                )
                db.add_all([alice, bob])
                await db.flush()
                session = Session(agent_id=agent.id, user_id=alice.id)
                db.add(session)
                await db.commit()
                artifact = await ArtifactService(ArtifactRepository(db), storage).create_bytes(
                    session.id,
                    "../report.txt",
                    "TEXT",
                    "text/plain",
                    b"private report",
                )
                artifact_id = artifact.id

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:

                async def token(username, password):
                    response = await client.post(
                        "/api/v1/auth/login", json={"username": username, "password": password}
                    )
                    assert response.status_code == 200, response.text
                    return {"Authorization": f"Bearer {response.json()['access_token']}"}

                alice_headers = await token(alice.username, "artifact-alice-secret")
                bob_headers = await token(bob.username, "artifact-bob-secret-12")
                own = await client.get(
                    f"/api/v1/client/artifacts/{artifact_id}", headers=alice_headers
                )
                assert own.status_code == 200 and own.json()["name"] == "report.txt"
                assert "storage_key" not in own.json()
                file = await client.get(
                    f"/api/v1/client/artifacts/{artifact_id}/download", headers=alice_headers
                )
                assert file.status_code == 200 and file.content == b"private report"
                assert (
                    await client.get(f"/api/v1/client/artifacts/{artifact_id}", headers=bob_headers)
                ).status_code == 404
                listed = await client.get(
                    f"/api/v1/client/conversations/{session.id}/artifacts", headers=alice_headers
                )
                assert listed.json()["total"] == 1
            try:
                storage.path("../etc/passwd")
                raise AssertionError("unsafe key accepted")
            except ValueError:
                pass
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()
