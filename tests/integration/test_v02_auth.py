import os
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.passwords import hash_password
from app.main import app
from app.persistence.database import Permission, Role, User, get_db


async def test_auth_login_refresh_logout_and_me():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    suffix = uuid4().hex[:8]
    password = "correct-secret-1234"
    try:
        async with factory() as db:
            role = Role(name=f"role-{suffix}")
            role.permissions = [Permission(code=f"agent:view:{suffix}")]
            db.add(
                User(
                    username=f"user-{suffix}",
                    display_name="测试用户",
                    password_hash=hash_password(password),
                    roles=[role],
                )
            )
            await db.commit()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.get("/api/v1/auth/me")
            assert denied.status_code == 401
            assert denied.json()["request_id"] == denied.headers["X-Request-ID"]
            failed = await client.post(
                "/api/v1/auth/login", json={"username": f"user-{suffix}", "password": "wrong"}
            )
            assert failed.status_code == 401
            login = await client.post(
                "/api/v1/auth/login", json={"username": f"user-{suffix}", "password": password}
            )
            assert login.status_code == 200
            tokens = login.json()
            headers = {"Authorization": f"Bearer {tokens['access_token']}"}
            me = await client.get("/api/v1/auth/me", headers=headers)
            assert me.status_code == 200
            assert me.json()["roles"] == [f"role-{suffix}"]
            assert f"agent:view:{suffix}" in me.json()["permissions"]
            rotated = await client.post(
                "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
            )
            assert rotated.status_code == 200
            assert (
                await client.post(
                    "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
                )
            ).status_code == 401
            assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
            new_headers = {"Authorization": f"Bearer {rotated.json()['access_token']}"}
            assert (
                await client.post("/api/v1/auth/logout", headers=new_headers)
            ).status_code == 204
            assert (await client.get("/api/v1/auth/me", headers=new_headers)).status_code == 401
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
