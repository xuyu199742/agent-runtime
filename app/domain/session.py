from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationTurn:
    role: str
    content: str
