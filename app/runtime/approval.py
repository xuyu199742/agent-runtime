"""LangGraph interrupt 对接持久 Approval，恢复时由调用方提供决策。"""

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.types import interrupt

from app.persistence.repositories.approvals import ApprovalRepository


class ApprovalMiddleware(AgentMiddleware):
    def __init__(
        self, session_factory=None, run_id: str | None = None, policies: dict | None = None
    ):
        self.session_factory = session_factory
        self.run_id = run_id
        self.policies = policies or {}

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        policy = self.policies.get(call["name"], {})
        if self.session_factory is None or not policy.get("policy", {}).get("requires_approval"):
            return await handler(request)
        async with self.session_factory() as db:
            approval = await ApprovalRepository(db).ensure(
                self.run_id,
                call["id"],
                call["name"],
                f"确认执行 {call['name']}",
                policy.get("description", ""),
                policy["policy"].get("approval_risk", "LOW"),
            )
        accepted = interrupt(
            {
                "approval_id": approval.id,
                "title": approval.title,
                "description": approval.description,
                "risk": approval.risk,
                "tool_name": approval.tool_name,
            }
        )
        if not accepted:
            return ToolMessage(
                content="用户拒绝工具调用",
                tool_call_id=call["id"],
                name=call["name"],
                status="error",
            )
        return await handler(request)
