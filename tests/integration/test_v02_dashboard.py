import os
from uuid import uuid4

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.passwords import hash_password
from app.main import app
from app.persistence.database import Permission, Role, User, get_db
from app.persistence.repositories.dashboard import DashboardRepository


async def test_dashboard_queries_return_runtime_metrics():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            summary = await DashboardRepository(db).summary()
        assert summary["today_runs"] >= 0
        assert summary["running"] >= 0
        assert summary["waiting"] >= 0
        assert isinstance(summary["model_usage"], list)
        assert isinstance(summary["run_trend"], list)
    finally:
        await engine.dispose()


async def test_observability_routes_require_permissions():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    suffix = uuid4().hex[:8]

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.state.redis = redis
    try:
        async with factory() as db:
            viewer = User(
                username=f"observer-{suffix}",
                display_name="Observer",
                password_hash=hash_password("observer-secret-123"),
                roles=[
                    Role(
                        name=f"observer-role-{suffix}",
                        permissions=[
                            Permission(code=f"dashboard:view:{suffix}"),
                            Permission(code=f"worker:view:{suffix}"),
                        ],
                    )
                ],
            )
            db.add(viewer)
            await db.commit()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": viewer.username, "password": "observer-secret-123"},
            )
            assert login.status_code == 200
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            assert (await client.get("/api/v1/admin/dashboard", headers=headers)).status_code == 403
            assert (await client.get("/api/v1/admin/workers", headers=headers)).status_code == 403
            assert (await client.get("/api/v1/admin/artifacts", headers=headers)).status_code == 403
    finally:
        app.dependency_overrides.clear()
        await redis.aclose()
        await engine.dispose()
