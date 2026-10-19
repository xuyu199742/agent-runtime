import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool

from app.runtime.agent import LangChainAgentRuntime
from app.runtime.errors import PolicyDenied
from app.runtime.policy import PolicyOutcome, evaluate_tool_policy


@pytest.mark.parametrize(
    "tool, outcome, reason",
    [
        ({"name": "echo", "effect_type": "READ_ONLY"}, PolicyOutcome.ALLOW, "READ_ALLOWED"),
        (
            {"name": "ticket.create", "effect_type": "EXTERNAL_WRITE", "policy": {}},
            PolicyOutcome.DENY,
            "WRITE_NOT_ALLOWED",
        ),
        (
            {
                "name": "ticket.create",
                "effect_type": "EXTERNAL_WRITE",
                "policy": {
                    "write_allowed": True,
                    "requires_approval": True,
                    "approval_risk": "HIGH",
                },
            },
            PolicyOutcome.REQUIRE_APPROVAL,
            "APPROVAL_REQUIRED",
        ),
        (
            {
                "name": "ticket.create",
                "effect_type": "EXTERNAL_WRITE",
                "policy": {"write_allowed": True},
            },
            PolicyOutcome.ALLOW,
            "WRITE_ALLOWED",
        ),
        (
            {"name": "x", "effect_type": "INTERNAL_WRITE"},
            PolicyOutcome.DENY,
            "UNSUPPORTED_EFFECT_TYPE",
        ),
        (
            {"name": "x", "effect_type": "READ_ONLY", "enabled": False},
            PolicyOutcome.DENY,
            "POLICY_DENIED",
        ),
        (None, PolicyOutcome.DENY, "POLICY_DENIED"),
    ],
)
def test_policy_decision_matrix(tool, outcome, reason):
    decision = evaluate_tool_policy(tool)
    assert (decision.outcome, decision.reason_code) == (outcome, reason)
    if outcome is PolicyOutcome.REQUIRE_APPROVAL:
        assert decision.risk == "HIGH"


async def test_policy_denial_precedes_approval_and_tool_call(monkeypatch):
    class ToolModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    async def tool_invoke(ticket_key: str, title: str) -> str:
        raise AssertionError("Policy 拒绝后不得执行 Tool")

    async def approval_ensure(*_args, **_kwargs):
        raise AssertionError("Policy 拒绝后不得创建审批")

    async def emit(_kind, _data):
        pass

    async def not_cancelled():
        return False

    monkeypatch.setattr("app.runtime.approval.ApprovalRepository.ensure", approval_ensure)
    model = ToolModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "ticket.create", "args": {"ticket_key": "k", "title": "t"}, "id": "c1"}
                ],
            )
        ]
    )
    runtime = LangChainAgentRuntime(
        model,
        [
            StructuredTool.from_function(
                coroutine=tool_invoke, name="ticket.create", description="受控工单"
            )
        ],
        "",
        3,
        tool_policies={
            "ticket.create": {
                "name": "ticket.create",
                "effect_type": "EXTERNAL_WRITE",
                "policy": {"write_allowed": False, "requires_approval": True},
            }
        },
        approval_session_factory=object(),
    )
    with pytest.raises(PolicyDenied) as exc:
        await runtime.run("run-1", [HumanMessage(content="创建")], emit, not_cancelled)
    assert exc.value.code == "WRITE_NOT_ALLOWED"
