"""只根据 Run 冻结的 Tool 定义做最小运行时决策。"""

from dataclasses import dataclass
from enum import StrEnum


class PolicyOutcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    reason_code: str
    risk: str | None = None


def evaluate_tool_policy(tool: dict | None) -> PolicyDecision:
    if tool is None or tool.get("enabled", True) is not True:
        return PolicyDecision(PolicyOutcome.DENY, "POLICY_DENIED")
    effect_type = tool.get("effect_type", "READ_ONLY")
    if effect_type == "INTERNAL_WRITE" or effect_type not in {"READ_ONLY", "EXTERNAL_WRITE"}:
        return PolicyDecision(PolicyOutcome.DENY, "UNSUPPORTED_EFFECT_TYPE")
    policy = tool.get("policy") or {}
    if effect_type == "EXTERNAL_WRITE" and policy.get("write_allowed") is not True:
        return PolicyDecision(PolicyOutcome.DENY, "WRITE_NOT_ALLOWED")
    if policy.get("requires_approval") is True:
        return PolicyDecision(
            PolicyOutcome.REQUIRE_APPROVAL,
            "APPROVAL_REQUIRED",
            policy.get("approval_risk", "LOW"),
        )
    return PolicyDecision(
        PolicyOutcome.ALLOW, "READ_ALLOWED" if effect_type == "READ_ONLY" else "WRITE_ALLOWED"
    )
