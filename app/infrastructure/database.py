from collections.abc import AsyncIterator
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings
from app.domain.entities import RunStatus


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    provider: Mapped[str] = mapped_column(String(40))
    model_name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str | None] = mapped_column(String(500))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ToolDefinition(Base):
    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(20))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentTool(Base):
    __tablename__ = "agent_tools"

    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.id"), primary_key=True)


class AgentDefinition(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    model_id: Mapped[str] = mapped_column(ForeignKey("model_configs.id"))
    max_steps: Mapped[int] = mapped_column(Integer, default=10)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    tools: Mapped[list[ToolDefinition]] = relationship(secondary="agent_tools", lazy="selectin")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    user_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("user_id", "client_message_id"),
        Index("ix_messages_session_created", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    user_id: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    client_message_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_status_lease", "status", "lease_until"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), unique=True)
    answer_message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"))
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.PENDING)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_factory() as db:
        yield db
