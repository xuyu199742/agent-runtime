from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.infrastructure.database import Message


def build_context(history: Sequence[Message], max_messages: int = 30) -> list[BaseMessage]:
    """集中构造模型输入；Session 长期历史与本次上下文分别管理。"""
    selected = history[-max_messages:]
    result: list[BaseMessage] = []
    for message in selected:
        if message.role == "user":
            result.append(HumanMessage(content=message.content))
        elif message.role == "assistant":
            result.append(AIMessage(content=message.content))
    return result
