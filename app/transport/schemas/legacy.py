from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.budget import (
    DEFAULT_MAX_DURATION_SECONDS,
    DEFAULT_MAX_EXTERNAL_WRITES,
    DEFAULT_MAX_MODEL_CALLS,
    DEFAULT_MAX_TOOL_CALLS,
)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ModelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    provider: Literal["openai", "openai-compatible"]
    model_name: str = Field(min_length=1, max_length=120)
    base_url: str | None = None
    api_key: str | None = Field(default=None, min_length=1, exclude=True, repr=False)
    config: dict = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_runtime_options(self):
        if self.provider == "openai-compatible" and not self.base_url:
            raise ValueError("OpenAI-compatible 模型需要 base_url")
        allowed = {
            "timeout_seconds",
            "max_retries",
            "temperature",
            "context_window",
            "max_output_tokens",
        }
        if set(self.config) - allowed:
            raise ValueError("模型 config 包含不支持的配置项")
        for key in ("context_window", "max_output_tokens"):
            if key not in self.config:
                raise ValueError(f"模型配置必须包含 {key}")
            value = self.config[key]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{key} 必须是正整数")
        if self.config["max_output_tokens"] >= self.config["context_window"]:
            raise ValueError("max_output_tokens 必须小于 context_window")
        timeout = self.config.get("timeout_seconds", 60)
        retries = self.config.get("max_retries", 1)
        if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 300:
            raise ValueError("timeout_seconds 必须在 1 到 300 秒之间")
        if not isinstance(retries, int) or not 0 <= retries <= 5:
            raise ValueError("max_retries 必须在 0 到 5 之间")
        return self


class ModelOut(Out):
    id: str
    name: str
    provider: Literal["openai", "openai-compatible"]
    model_name: str
    base_url: str | None = None
    config: dict = Field(default_factory=dict)
    enabled: bool = True
    has_api_key: bool


class ToolIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    type: Literal["NATIVE", "HTTP"]
    config: dict = Field(default_factory=dict)
    policy: dict = Field(default_factory=dict)
    effect_type: Literal["READ_ONLY"] = "READ_ONLY"
    failure_policy: Literal["RETURN_ERROR", "FAIL_RUN"] = "RETURN_ERROR"
    enabled: bool = True

    @model_validator(mode="after")
    def validate_tool_options(self):
        approval_keys = {"requires_approval", "approval_risk"}
        if set(self.policy) - (approval_keys | {"allowed_hosts"}):
            raise ValueError("Tool policy 包含不支持的配置")
        if not isinstance(self.policy.get("requires_approval", False), bool):
            raise ValueError("requires_approval 必须是布尔值")  # noqa: TRY004 - Pydantic 将其转为 422
        if self.policy.get("approval_risk", "LOW") not in {"LOW", "MEDIUM", "HIGH"}:
            raise ValueError("approval_risk 无效")
        if self.type == "NATIVE" and (
            self.name not in {"echo", "calculator"}
            or set(self.config) - {"timeout_seconds"}
            or "allowed_hosts" in self.policy
        ):
            raise ValueError("不支持的 Native Tool 配置")
        if self.type == "HTTP":
            if self.name != "http_request" or set(self.config) - {
                "allowed_hosts",
                "timeout_seconds",
            }:
                raise ValueError("不支持的 HTTP Tool 配置")
            hosts = self.policy.get("allowed_hosts", self.config.get("allowed_hosts", []))
            if (
                not isinstance(hosts, list)
                or not hosts
                or not all(isinstance(host, str) and host for host in hosts)
            ):
                raise ValueError("HTTP Tool 需要 allowed_hosts 域名列表")
        timeout = self.config.get("timeout_seconds", 10)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= 30
        ):
            raise ValueError("Tool timeout_seconds 必须在 0 到 30 秒之间")
        return self


class ToolOut(ToolIn, Out):
    id: str


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    system_prompt: str = ""
    model_id: str
    max_model_calls: int = Field(default=DEFAULT_MAX_MODEL_CALLS, ge=1, le=100)
    max_tool_calls: int = Field(default=DEFAULT_MAX_TOOL_CALLS, ge=1, le=1000)
    max_external_writes: int = Field(default=DEFAULT_MAX_EXTERNAL_WRITES, ge=0, le=100)
    max_duration_seconds: int = Field(default=DEFAULT_MAX_DURATION_SECONDS, ge=1, le=86400)
    enabled: bool = True
    tool_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)


class AgentOut(Out):
    id: str
    name: str
    description: str
    system_prompt: str
    model_id: str
    max_model_calls: int
    max_tool_calls: int
    max_external_writes: int
    max_duration_seconds: int
    enabled: bool
    tool_ids: list[str]
    skill_ids: list[str] = Field(default_factory=list)
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
