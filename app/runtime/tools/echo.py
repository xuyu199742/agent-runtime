from langchain_core.tools import tool


@tool
def echo(text: str) -> str:
    """原样返回输入文本。"""
    return text
