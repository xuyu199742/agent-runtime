from collections.abc import Awaitable, Callable, Sequence
from typing import TypedDict

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.runtime.middleware import RunContextMiddleware, ToolErrorMiddleware, TracingMiddleware


class RunContext(TypedDict, total=False):
    run_id: str
    session_id: str
    user_id: str


class RunCancelled(Exception):
    pass


EventSink = Callable[[str, dict], Awaitable[None]]
CancelCheck = Callable[[], Awaitable[bool]]


class LangChainAgentRuntime:
    def __init__(
        self,
        model: BaseChatModel,
        tools: Sequence[BaseTool],
        system_prompt: str,
        max_steps: int,
        checkpointer=None,
    ) -> None:
        self.graph = create_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            middleware=[RunContextMiddleware(), TracingMiddleware(), ToolErrorMiddleware()],
            context_schema=RunContext,
            checkpointer=checkpointer,
        )
        self.max_steps = max_steps
        self.has_checkpointer = checkpointer is not None

    async def run(
        self,
        run_id: str,
        messages: Sequence[BaseMessage],
        emit: EventSink,
        should_cancel: CancelCheck,
        session_id: str | None = None,
        user_id: str | None = None,
        resume: bool = False,
    ) -> str:
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": self.max_steps * 2 + 2}
        input_state = {"messages": list(messages)}
        if resume and self.has_checkpointer:
            state = await self.graph.aget_state(config)
            if state.values:
                if not state.next:
                    for message in reversed(state.values.get("messages", [])):
                        if isinstance(message, AIMessage) and not message.tool_calls:
                            return message.text
                input_state = None
        answer = ""
        model_step = None
        async for mode, chunk in self.graph.astream(
            input_state,
            config=config,
            context={"run_id": run_id, "session_id": session_id, "user_id": user_id},
            stream_mode=["messages", "updates"],
        ):
            if await should_cancel():
                raise RunCancelled
            if mode == "messages":
                message, metadata = chunk
                if metadata.get("langgraph_node") == "model" and isinstance(message, AIMessage):
                    if metadata.get("langgraph_step") != model_step:
                        model_step = metadata.get("langgraph_step")
                        await emit("model.started", {})
                    if isinstance(message.content, str) and message.content:
                        await emit("model.delta", {"text": message.content})
            elif mode == "updates":
                for node, update in chunk.items():
                    if not isinstance(update, dict):
                        continue
                    for message in update.get("messages", []):
                        if node == "model" and isinstance(message, AIMessage):
                            await emit("model.completed", {})
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
        return answer
