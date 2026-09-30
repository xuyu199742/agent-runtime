import os
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.persistence.database import get_db
from scripts.bootstrap_admin import create_admin


async def test_bootstrap_admin_manages_permissions_roles_users_and_menus():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    suffix = uuid4().hex[:8]
    username = f"admin-{suffix}"
    try:
        await create_admin(username, "管理员", "bootstrap-secret-123")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": "bootstrap-secret-123"},
            )
            assert login.status_code == 200, login.text
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            permission = await client.post(
                "/api/v1/admin/permissions",
                headers=headers,
                json={"code": f"report:view:{suffix}", "description": "看报表"},
            )
            assert permission.status_code == 201, permission.text
            menu = await client.post(
                "/api/v1/admin/menus",
                headers=headers,
                json={
                    "name": f"报表-{suffix}",
                    "path": f"/reports/{suffix}",
                    "permission_code": f"report:view:{suffix}",
                },
            )
            assert menu.status_code == 201, menu.text
            role = await client.post(
                "/api/v1/admin/roles",
                headers=headers,
                json={
                    "name": f"analyst-{suffix}",
                    "permission_codes": [f"report:view:{suffix}"],
                    "menu_ids": [menu.json()["id"]],
                },
            )
            assert role.status_code == 201, role.text
            user = await client.post(
                "/api/v1/admin/users",
                headers=headers,
                json={
                    "username": f"analyst-{suffix}",
                    "display_name": "分析员",
                    "password": "analyst-secret-123",
                    "role_ids": [role.json()["id"]],
                },
            )
            assert user.status_code == 201, user.text
            assert "password_hash" not in user.json()
            analyst_login = await client.post(
                "/api/v1/auth/login",
                json={"username": f"analyst-{suffix}", "password": "analyst-secret-123"},
            )
            analyst = {"Authorization": f"Bearer {analyst_login.json()['access_token']}"}
            assert (await client.get("/api/v1/admin/models", headers=analyst)).status_code == 403
            assert (await client.get("/api/v1/admin/me/menus", headers=analyst)).status_code == 403
            assert (await client.get("/api/v1/admin/me/menus", headers=headers)).status_code == 200
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
