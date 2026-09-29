import ast
import operator

from langchain_core.tools import BaseTool, tool

_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def calculate(expression: str) -> str:
    if len(expression) > 200:
        raise ValueError("表达式过长")

    def evaluate(node: ast.AST, depth: int = 0) -> float:
        if depth > 20:
            raise ValueError("表达式嵌套过深")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = float(node.value)
        elif isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            value = _OPERATORS[type(node.op)](
                evaluate(node.left, depth + 1), evaluate(node.right, depth + 1)
            )
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand, depth + 1) * (-1 if isinstance(node.op, ast.USub) else 1)
        else:
            raise ValueError("只支持数字与加减乘除")
        if abs(value) > 1e12:
            raise ValueError("计算结果超出范围")
        return value

    try:
        result = evaluate(ast.parse(expression, mode="eval").body)
    except (SyntaxError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError("表达式无效") from exc
    return str(int(result)) if result.is_integer() else str(result)


@tool("calculator")
def calculator(expression: str) -> str:
    """计算仅含数字和加减乘除的算术表达式。"""
    return calculate(expression)


def calculator_tool() -> BaseTool:
    return calculator
