from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelDefinition:
    provider: str
    model_name: str
    base_url: str | None = None
    api_key_encrypted: str | None = None
    config: dict = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    type: str
    description: str = ""
    config: dict = field(default_factory=dict)
    policy: dict = field(default_factory=dict)
    enabled: bool = True
