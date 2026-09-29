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
from app.transport.http import agents, models, runs, sessions, sse, tools
from app.transport.http.common import Db

configure_logging()
log = structlog.get_logger()
app = FastAPI(title="Agent Server", version="0.1.0")


@app.middleware("http")
async def request_context(request: Request, call_next):
    structlog.contextvars.clear_contextvars()
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    structlog.contextvars.bind_contextvars(
        request_id=request_id, user_id=get_settings().dev_user_id
    )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(IntegrityError)
async def integrity_error(_request: Request, exc: IntegrityError):
    log.warning("数据库约束冲突", error_type=type(exc).__name__)
    return JSONResponse(
        status_code=409, content={"code": "VALIDATION_ERROR", "message": "记录重复或关联无效"}
    )


@app.exception_handler(SQLAlchemyError)
async def database_error(_request: Request, exc: SQLAlchemyError):
    log.error("数据库不可用", error_type=type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={"code": "INTERNAL_ERROR", "message": "数据库暂不可用"},
    )


@app.exception_handler(RedisError)
async def redis_error(_request: Request, exc: RedisError):
    log.error("Redis 不可用", error_type=type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={"code": "INTERNAL_ERROR", "message": "运行服务暂不可用"},
    )


@app.exception_handler(AppError)
async def app_error(_request: Request, exc: AppError):
    status = 404 if isinstance(exc, NotFound) else 409 if isinstance(exc, Conflict) else 422
    return JSONResponse(status_code=status, content={"code": exc.code, "message": str(exc)})


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    code = "PERMISSION_DENIED" if exc.status_code == 403 else "VALIDATION_ERROR"
    if exc.status_code >= 500:
        code = "INTERNAL_ERROR"
    return JSONResponse(status_code=exc.status_code, content={"code": code, "message": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError):
    return JSONResponse(
        status_code=422, content={"code": "VALIDATION_ERROR", "message": "请求参数无效"}
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready(db: Db):
    try:
        await db.execute(text("SELECT 1"))
        redis = Redis.from_url(get_settings().redis_url)
        try:
            await redis.ping()
        finally:
            await redis.aclose()
    except (SQLAlchemyError, RedisError, OSError):
        raise HTTPException(503, detail="依赖暂不可用") from None
    return {"status": "ready"}


for module in (models, tools, agents, sessions, runs, sse):
    app.include_router(module.router)
