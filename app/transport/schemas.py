from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ModelIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: Literal["openai", "openai-compatible"]
    model_name: str = Field(min_length=1, max_length=120)
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class ModelOut(ModelIn, Out):
    id: str


class ToolIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    type: Literal["NATIVE", "HTTP"]
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class ToolOut(ToolIn, Out):
    id: str


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    system_prompt: str = ""
    model_id: str
    max_steps: int = Field(default=10, ge=1, le=100)
    enabled: bool = True
    tool_ids: list[str] = Field(default_factory=list)


class AgentOut(Out):
    id: str
    name: str
    description: str
    system_prompt: str
    model_id: str
    max_steps: int
    enabled: bool
    tool_ids: list[str]
    created_at: datetime
    updated_at: datetime


class SessionIn(BaseModel):
    agent_id: str


class SessionOut(Out):
    id: str
    agent_id: str
    user_id: str
    created_at: datetime


class MessageIn(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1)


class MessageAccepted(BaseModel):
    message_id: str
    run_id: str


class RunOut(Out):
    id: str
    session_id: str
    message_id: str
    answer_message_id: str | None
    status: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
