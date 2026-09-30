import os
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.passwords import hash_password
from app.main import app
from app.persistence.database import Permission, Role, User, get_db


async def test_admin_rbac_pagination_and_audit():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    suffix = uuid4().hex[:8]
    try:
        async with factory() as db:
            # 管理接口使用固定权限码，测试保留 unique 用户/角色即可。
            actual_view = await db.get(Permission, "model:view")
            if actual_view is None:
                actual_view = Permission(code="model:view")
                db.add(actual_view)
            actual_edit = await db.get(Permission, "model:update")
            if actual_edit is None:
                actual_edit = Permission(code="model:update")
                db.add(actual_edit)
            actual_audit = await db.get(Permission, "audit:view")
            if actual_audit is None:
                actual_audit = Permission(code="audit:view")
                db.add(actual_audit)
            reader_role = Role(name=f"reader-{suffix}", permissions=[actual_view])
            editor_role = Role(
                name=f"editor-{suffix}", permissions=[actual_view, actual_edit, actual_audit]
            )
            db.add_all(
                [
                    User(
                        username=f"reader-{suffix}",
                        display_name="Reader",
                        password_hash=hash_password("reader-secret-123"),
                        roles=[reader_role],
                    ),
                    User(
                        username=f"editor-{suffix}",
                        display_name="Editor",
                        password_hash=hash_password("editor-secret-123"),
                        roles=[editor_role],
                    ),
                ]
            )
            await db.commit()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            async def login(username, password):
                result = await client.post(
                    "/api/v1/auth/login", json={"username": username, "password": password}
                )
                assert result.status_code == 200
                return {"Authorization": f"Bearer {result.json()['access_token']}"}

            reader = await login(f"reader-{suffix}", "reader-secret-123")
            editor = await login(f"editor-{suffix}", "editor-secret-123")
            body = {"name": f"model-{suffix}", "provider": "openai", "model_name": "gpt-test"}
            assert (
                await client.post("/api/v1/admin/models", json=body, headers=reader)
            ).status_code == 403
            created = await client.post("/api/v1/admin/models", json=body, headers=editor)
            assert created.status_code == 201, created.text
            assert (
                await client.get("/api/v1/admin/models", headers=reader, params={"keyword": suffix})
            ).json()["total"] == 1
            assert (await client.get("/api/v1/admin/audit-logs", headers=reader)).status_code == 403
            audit = await client.get("/api/v1/admin/audit-logs", headers=editor)
            assert audit.status_code == 200
            assert any(
                item["action"] == "model:create" and item["resource_id"] == created.json()["id"]
                for item in audit.json()["items"]
            )
            disabled = await client.post(
                f"/api/v1/admin/models/{created.json()['id']}/disable", headers=editor
            )
            assert disabled.status_code == 200 and disabled.json()["enabled"] is False
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
