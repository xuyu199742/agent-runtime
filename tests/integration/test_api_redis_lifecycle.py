from app.main import app


async def test_api_lifespan_owns_shared_redis_pool():
    async with app.router.lifespan_context(app):
        redis = app.state.redis
        assert await redis.ping()
        assert app.state.redis is redis
