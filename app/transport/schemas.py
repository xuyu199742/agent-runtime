from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    @model_validator(mode="after")
    def validate_runtime_options(self):
        if self.provider == "openai-compatible" and not self.base_url:
            raise ValueError("OpenAI-compatible 模型需要 base_url")
        if set(self.config) - {"timeout_seconds", "max_retries", "temperature"}:
            raise ValueError("模型 config 包含不支持的配置项")
        timeout = self.config.get("timeout_seconds", 60)
        retries = self.config.get("max_retries", 1)
        if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 300:
            raise ValueError("timeout_seconds 必须在 1 到 300 秒之间")
        if not isinstance(retries, int) or not 0 <= retries <= 5:
            raise ValueError("max_retries 必须在 0 到 5 之间")
        return self


class ModelOut(ModelIn, Out):
    id: str


class ToolIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    type: Literal["NATIVE", "HTTP"]
    config: dict = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_tool_options(self):
        if self.type == "NATIVE" and (self.name not in {"echo", "calculator"} or self.config):
            raise ValueError("不支持的 Native Tool 配置")
        if self.type == "HTTP":
            if self.name != "http_request" or set(self.config) - {
                "allowed_hosts",
                "timeout_seconds",
            }:
                raise ValueError("不支持的 HTTP Tool 配置")
            hosts = self.config.get("allowed_hosts", [])
            if (
                not isinstance(hosts, list)
                or not hosts
                or not all(isinstance(host, str) and host for host in hosts)
            ):
                raise ValueError("HTTP Tool 需要 allowed_hosts 域名列表")
        return self


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
    answer: str | None = None
    status: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
