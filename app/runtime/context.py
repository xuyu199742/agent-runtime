from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.domain.session import ConversationTurn


def approximate_tokens(content: str) -> int:
    """保守估算上下文大小，避免超长输入进入模型；未来可替换为模型 tokenizer。"""
    ascii_count = sum(char.isascii() for char in content)
    return (ascii_count + 3) // 4 + (len(content) - ascii_count) * 2


def build_context(
    history: Sequence[ConversationTurn], max_messages: int = 30, max_tokens: int = 12000
) -> list[BaseMessage]:
    """从最近消息向前选择模型上下文；数据库仍保存完整 Session 历史。"""
    selected = []
    remaining = max_tokens
    for message in reversed(history[-max_messages:]):
        content = message.content
        cost = approximate_tokens(content)
        if cost > remaining:
            if selected:
                break
            # 当前消息也必须受到上限保护，截断后仍保留可处理的输入。
            lo, hi = 0, len(content)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if approximate_tokens(content[:mid]) <= remaining:
                    lo = mid
                else:
                    hi = mid - 1
            content = content[:lo]
            cost = approximate_tokens(content)
        selected.append((message.role, content))
        remaining -= cost
        if remaining <= 0:
            break

    result: list[BaseMessage] = []
    for role, content in reversed(selected):
        if role == "user":
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
    return result
