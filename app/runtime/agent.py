from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

from app.runtime.approval import ApprovalMiddleware
from app.runtime.errors import ApprovalRecoveryLost
from app.runtime.middleware import (
    EffectSafetyMiddleware,
    PolicyMiddleware,
    RunContextMiddleware,
    ToolErrorMiddleware,
    TracingMiddleware,
)


class RunContext(TypedDict, total=False):
    run_id: str
    session_id: str
    user_id: str


class RunCancelled(Exception):
    pass


class RunWaiting(Exception):
    def __init__(self, approvals: list[dict]):
        self.approvals = approvals


EventSink = Callable[[str, dict], Awaitable[None]]
CancelCheck = Callable[[], Awaitable[bool]]


@dataclass(frozen=True)
class RuntimeInterrupt:
    id: str
    approval_id: str


class LangChainAgentRuntime:
    def __init__(
        self,
        model: BaseChatModel,
        tools: Sequence[BaseTool],
        system_prompt: str,
        max_model_calls: int,
        checkpointer=None,
        tool_execution_store=None,
        run_id: str | None = None,
        tool_policies: dict | None = None,
        approval_session_factory=None,
        model_call_journal=None,
        worker_id: str | None = None,
        effect_store=None,
        effect_providers: dict | None = None,
        working_context_middleware=None,
    ) -> None:
        middleware = [
            RunContextMiddleware(),
            TracingMiddleware(model_call_journal),
            PolicyMiddleware(approval_session_factory, run_id, worker_id, tool_policies),
            ApprovalMiddleware(approval_session_factory, run_id, tool_policies, worker_id),
            EffectSafetyMiddleware(
                effect_store, run_id, worker_id, tool_policies, effect_providers
            ),
            ToolErrorMiddleware(tool_execution_store, run_id, tool_policies),
            ModelCallLimitMiddleware(run_limit=max_model_calls, exit_behavior="error"),
        ]
        if working_context_middleware is not None:
            middleware.append(working_context_middleware)
        self.graph = create_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            middleware=middleware,
            context_schema=RunContext,
            checkpointer=checkpointer,
        )
        self.model_call_journal = model_call_journal
        self.has_checkpointer = checkpointer is not None
        self.sync_durability = working_context_middleware is not None

    async def inspect_interrupts(
        self, run_id: str, *, require_checkpoint: bool = False
    ) -> list[RuntimeInterrupt]:
        if not self.has_checkpointer:
            if require_checkpoint:
                raise ApprovalRecoveryLost("审批恢复所需检查点不存在")
            return []
        state = await self.graph.aget_state({"configurable": {"thread_id": run_id}})
        if require_checkpoint and state.created_at is None:
            raise ApprovalRecoveryLost("审批恢复所需检查点不存在")
        return [
            RuntimeInterrupt(id=item.id, approval_id=item.value["approval_id"])
            for item in state.interrupts
        ]

    async def run(
        self,
        run_id: str,
        messages: Sequence[BaseMessage],
        emit: EventSink,
        should_cancel: CancelCheck,
        session_id: str | None = None,
        user_id: str | None = None,
        resume: bool = False,
        approval_decisions: dict[str, bool] | None = None,
        require_checkpoint: bool = False,
    ) -> str:
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 1000}
        input_state = {"messages": list(messages)}
        if resume and self.has_checkpointer:
            state = await self.graph.aget_state(config)
            if require_checkpoint and state.created_at is None:
                raise ApprovalRecoveryLost("审批恢复所需检查点不存在")
            if state.values:
                if not state.next:
                    for message in reversed(state.values.get("messages", [])):
                        if isinstance(message, AIMessage) and not message.tool_calls:
                            return message.text
                input_state = Command(resume=approval_decisions) if approval_decisions else None
        answer = ""
        pending_approvals = []
        model_step = None
        step_id = None
        async for mode, chunk in self.graph.astream(
            input_state,
            config=config,
            context={"run_id": run_id, "session_id": session_id, "user_id": user_id},
            stream_mode=["messages", "updates"],
            **({"durability": "sync"} if self.sync_durability else {}),
        ):
            if await should_cancel():
                raise RunCancelled
            if mode == "messages":
                message, metadata = chunk
                if metadata.get("langgraph_node") == "model" and isinstance(message, AIMessage):
                    if step_id is None or metadata.get("langgraph_step") != model_step:
                        model_step = metadata.get("langgraph_step")
                        step_id = f"{run_id}:model:{model_step}"
                        # 同一 logical step 的新 started 表示重试；消费者应清空旧 partial。
                        await emit("model.started", {"step_id": step_id})
                    if self.model_call_journal is not None:
                        await self.model_call_journal.stream(step_id, message)
                    if isinstance(message.content, str) and message.content:
                        await emit("model.delta", {"step_id": step_id, "text": message.content})
            elif mode == "updates":
                if "__interrupt__" in chunk:
                    pending_approvals = [item.value for item in chunk["__interrupt__"]]
                    continue
                for node, update in chunk.items():
                    if not isinstance(update, dict):
                        continue
                    for message in update.get("messages", []):
                        if node == "model" and isinstance(message, AIMessage):
                            if step_id is None:
                                model_step = len(
                                    [
                                        m
                                        for m in update.get("messages", [])
                                        if isinstance(m, AIMessage)
                                    ]
                                )
                                step_id = f"{run_id}:model:{model_step}"
                                await emit("model.started", {"step_id": step_id})
                            await emit("model.completed", {"step_id": step_id})
                            step_id = None
                            for call in message.tool_calls:
                                await emit(
                                    "tool.started",
                                    {"name": call["name"], "tool_call_id": call["id"]},
                                )
                            if not message.tool_calls:
                                answer = message.text
                        elif node == "tools" and isinstance(message, ToolMessage):
                            kind = "tool.failed" if message.status == "error" else "tool.completed"
                            await emit(
                                kind, {"name": message.name, "tool_call_id": message.tool_call_id}
                            )
        if pending_approvals:
            raise RunWaiting(pending_approvals)
        return answer
