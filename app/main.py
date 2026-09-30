from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.config import get_settings
from app.domain.errors import AppError, Conflict, NotFound
from app.infrastructure.logging import configure_logging
from app.messaging.client import close_if_owned, redis_for_request
from app.persistence.database import engine
from app.transport.http import agents, models, runs, sessions, sse, tools
from app.transport.http.common import Db
from app.transport.http.v1 import auth
from app.transport.http.v1.admin import agents as admin_agents
from app.transport.http.v1.admin import audit as admin_audit
from app.transport.http.v1.admin import conversations as admin_conversations
from app.transport.http.v1.admin import models as admin_models
from app.transport.http.v1.admin import runs as admin_runs
from app.transport.http.v1.admin import system as admin_system
from app.transport.http.v1.admin import tools as admin_tools
from app.transport.http.v1.client import agents as client_agents
from app.transport.http.v1.client import conversations as client_conversations
from app.transport.http.v1.client import runs as client_runs

configure_logging()
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    app.state.redis = redis
    try:
        yield
    finally:
        await redis.aclose()
        await engine.dispose()
        del app.state.redis


app = FastAPI(title="Agent Runtime", version="0.2.0", lifespan=lifespan)


def error_response(
    request: Request, status: int, code: str, message: str, headers: dict | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
        },
        headers=headers,
    )


@app.middleware("http")
async def request_context(request: Request, call_next):
    structlog.contextvars.clear_contextvars()
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    structlog.contextvars.bind_contextvars(request_id=request_id)
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(IntegrityError)
async def integrity_error(request: Request, exc: IntegrityError):
    log.warning("数据库约束冲突", error_type=type(exc).__name__)
    return error_response(request, 409, "VALIDATION_ERROR", "记录重复或关联无效")


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    log.error("数据库不可用", error_type=type(exc).__name__)
    return error_response(request, 503, "INTERNAL_ERROR", "数据库暂不可用")


@app.exception_handler(RedisError)
async def redis_error(request: Request, exc: RedisError):
    log.error("Redis 不可用", error_type=type(exc).__name__)
    return error_response(request, 503, "INTERNAL_ERROR", "运行服务暂不可用")


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError):
    status = 404 if isinstance(exc, NotFound) else 409 if isinstance(exc, Conflict) else 422
    return error_response(request, status, exc.code, str(exc))


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    code = (
        "AUTH_REQUIRED"
        if exc.status_code == 401
        else "PERMISSION_DENIED"
        if exc.status_code == 403
        else "VALIDATION_ERROR"
    )
    if exc.status_code >= 500:
        code = "INTERNAL_ERROR"
    return error_response(request, exc.status_code, code, exc.detail, exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, _exc: RequestValidationError):
    return error_response(request, 422, "VALIDATION_ERROR", "请求参数无效")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready(request: Request, db: Db):
    try:
        await db.execute(text("SELECT 1"))
        redis, owned = redis_for_request(request)
        try:
            await redis.ping()
        finally:
            await close_if_owned(redis, owned)
    except (SQLAlchemyError, RedisError, OSError):
        raise HTTPException(503, detail="依赖暂不可用") from None
    return {"status": "ready"}


app.include_router(auth.router)
for module in (client_agents, client_conversations, client_runs):
    app.include_router(module.router)
for module in (
    admin_agents,
    admin_models,
    admin_tools,
    admin_conversations,
    admin_runs,
    admin_audit,
    admin_system,
):
    app.include_router(module.router)

if get_settings().legacy_api_enabled:
    for module in (models, tools, agents, sessions, runs, sse):
        app.include_router(module.router)
