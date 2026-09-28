from typing import Annotated
from uuid import uuid4

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.catalog import agent_out, save_agent
from app.application.chat import create_session, submit_message
from app.config import get_settings
from app.infrastructure.database import (
    AgentDefinition,
    ModelConfig,
    Run,
    Session,
    ToolDefinition,
    get_db,
)
from app.transport.schemas import (
    AgentIn,
    AgentOut,
    MessageAccepted,
    MessageIn,
    ModelIn,
    ModelOut,
    RunOut,
    SessionIn,
    SessionOut,
    ToolIn,
    ToolOut,
)

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger()
app = FastAPI(title="Agent Server", version="0.1.0")
Db = Annotated[AsyncSession, Depends(get_db)]


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


@app.post("/api/models", response_model=ModelOut, status_code=201)
async def add_model(body: ModelIn, db: Db):
    model = ModelConfig(**body.model_dump())
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


@app.get("/api/models", response_model=list[ModelOut])
async def list_models(db: Db):
    return list((await db.scalars(select(ModelConfig).order_by(ModelConfig.name))).all())


@app.post("/api/tools", response_model=ToolOut, status_code=201)
async def add_tool(body: ToolIn, db: Db):
    tool = ToolDefinition(**body.model_dump())
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return tool


@app.get("/api/tools", response_model=list[ToolOut])
async def list_tools(db: Db):
    return list((await db.scalars(select(ToolDefinition).order_by(ToolDefinition.name))).all())


@app.post("/api/agents", response_model=AgentOut, status_code=201)
async def add_agent(body: AgentIn, db: Db):
    return agent_out(await save_agent(db, body))


@app.get("/api/agents", response_model=list[AgentOut])
async def list_agents(db: Db):
    return [
        agent_out(agent)
        for agent in (
            await db.scalars(select(AgentDefinition).order_by(AgentDefinition.name))
        ).all()
    ]


@app.get("/api/agents/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str, db: Db):
    agent = await db.get(AgentDefinition, agent_id)
    if agent is None:
        raise HTTPException(404, detail="Agent 不存在")
    return agent_out(agent)


@app.put("/api/agents/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: str, body: AgentIn, db: Db):
    agent = await db.get(AgentDefinition, agent_id)
    if agent is None:
        raise HTTPException(404, detail="Agent 不存在")
    return agent_out(await save_agent(db, body, agent))


@app.post("/api/sessions", response_model=SessionOut, status_code=201)
async def add_session(body: SessionIn, db: Db):
    return await create_session(db, body.agent_id, get_settings().dev_user_id)


@app.get("/api/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, db: Db):
    session = await db.get(Session, session_id)
    if session is None or session.user_id != get_settings().dev_user_id:
        raise HTTPException(404, detail="Session 不存在")
    return session


@app.post("/api/sessions/{session_id}/messages", response_model=MessageAccepted, status_code=202)
async def add_message(session_id: str, body: MessageIn, db: Db):
    return await submit_message(db, session_id, get_settings().dev_user_id, body)


@app.get("/api/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: str, db: Db):
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, detail="Run 不存在")
    session = await db.get(Session, run.session_id)
    if session.user_id != get_settings().dev_user_id:
        raise HTTPException(404, detail="Run 不存在")
    return run
