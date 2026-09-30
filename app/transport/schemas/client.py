from datetime import datetime

from pydantic import BaseModel, Field


class PublicAgent(BaseModel):
    id: str
    name: str
    description: str
    avatar: str | None = None
    capabilities: list[str] = Field(default_factory=list)


class AgentSummary(BaseModel):
    id: str
    name: str


class ConversationOut(BaseModel):
    id: str
    title: str
    agent: AgentSummary
    last_message: str | None
    last_active_at: datetime
    created_at: datetime


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime


class ClientRunOut(BaseModel):
    id: str
    conversation_id: str
    status: str
    answer: str | None
    error: str | None
    created_at: datetime


class Page(BaseModel):
    items: list
    page: int
    page_size: int
    total: int
