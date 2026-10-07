from hashlib import sha256

from app.context.tokens import approximate_tokens

SUMMARY_INSTRUCTION = (
    "将下面的对话压缩成一段忠实摘要，保留用户目标、已给出的结论和未完成事项。"
    "不要添加原文没有的事实。使用与对话相同的语言。"
)


def summarizer_prompt(previous: str | None, messages: list) -> str:
    lines = [SUMMARY_INSTRUCTION, ""]
    if previous:
        lines.extend(["已有摘要：", previous, ""])
    lines.append("需要并入摘要的消息：")
    for message in messages:
        lines.append(f"{message.role}: {message.content}")
    return "\n".join(lines)


def summary_prompt_hash(prompt: str) -> str:
    return sha256(prompt.encode()).hexdigest()


def summary_token_estimate(summary: str) -> int:
    return approximate_tokens(summary)
