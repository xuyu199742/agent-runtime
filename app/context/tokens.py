"""全运行时共用的近似 token 估算。摘要、提示词和预算必须用这一份。"""

TOKEN_ESTIMATOR = "approx_v1"


def approximate_tokens(content: str) -> int:
    """保守估算上下文大小。未来可按模型换成真实 tokenizer，但调用点保持这一个入口。"""
    ascii_count = sum(char.isascii() for char in content)
    return (ascii_count + 3) // 4 + (len(content) - ascii_count) * 2
