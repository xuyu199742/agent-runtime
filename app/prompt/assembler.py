import json
from dataclasses import dataclass
from hashlib import sha256

PLATFORM_IDENTITY = (
    "你是运行在 Agent Runtime 中的助手。遵循本轮给出的执行契约、工具策略和上下文边界。"
)
RUNTIME_POLICY = (
    "只使用本轮提供的工具。需要审批的工具会暂停等待决定。不要声称执行了尚未返回结果的操作。"
)


@dataclass(frozen=True)
class PromptSection:
    name: str
    source: str
    content: str
    hash: str


@dataclass(frozen=True)
class PromptBundle:
    version: int
    sections: tuple[PromptSection, ...]
    rendered: str
    hash: str

    def snapshot(self) -> dict:
        return {
            "version": self.version,
            "hash": self.hash,
            "rendered": self.rendered,
            "sections": [
                {
                    "name": section.name,
                    "source": section.source,
                    "content": section.content,
                    "hash": section.hash,
                }
                for section in self.sections
            ],
        }


def _section(name: str, source: str, content: str) -> PromptSection:
    return PromptSection(
        name=name, source=source, content=content, hash=sha256(content.encode()).hexdigest()
    )


def bundle_hash(sections: tuple[PromptSection, ...] | list[PromptSection]) -> str:
    payload = [
        {
            "name": section.name,
            "source": section.source,
            "content": section.content,
            "hash": section.hash,
        }
        for section in sections
    ]
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return sha256(canonical.encode()).hexdigest()


def render_sections(sections: tuple[PromptSection, ...] | list[PromptSection]) -> str:
    return "\n\n".join(f"## {section.name}\n{section.content}" for section in sections)


def assemble(
    *,
    instruction: str,
    revision: int,
    environment: str,
    identity: str = PLATFORM_IDENTITY,
    policy: str = RUNTIME_POLICY,
) -> PromptBundle:
    sections = (
        _section("platform_identity", "platform:v1", identity),
        _section("agent_instruction", f"agent_revision:{revision}", instruction),
        _section("runtime_policy", "platform:policy:v1", policy),
        _section("environment", "runtime:v1", environment),
    )
    return PromptBundle(
        version=1,
        sections=sections,
        rendered=render_sections(sections),
        hash=bundle_hash(sections),
    )
