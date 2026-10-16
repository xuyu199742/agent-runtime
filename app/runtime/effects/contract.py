"""受控外部写入 Provider 与核对结果的最小契约。"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True)
class EffectIdentity:
    provider_namespace: str
    operation_name: str
    business_key: str
    contract_version: int
    request_hash: str


class ObservationStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    NOT_APPLIED = "NOT_APPLIED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EffectObservation:
    status: ObservationStatus
    result_content: str | None = None
    external_ref: str | None = None
    final: bool = False

    @classmethod
    def succeeded(cls, result_content: str, external_ref: str | None = None):
        return cls(ObservationStatus.SUCCEEDED, result_content, external_ref, True)

    @classmethod
    def not_applied(cls, *, final: bool):
        return cls(ObservationStatus.NOT_APPLIED, final=final)

    @classmethod
    def unknown(cls):
        return cls(ObservationStatus.UNKNOWN)


class ExternalWriteProvider(Protocol):
    def identity(self, args: dict) -> EffectIdentity: ...

    async def invoke(self, args: dict, business_key: str) -> EffectObservation: ...

    async def reconcile(self, identity: EffectIdentity) -> EffectObservation: ...
