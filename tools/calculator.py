from __future__ import annotations

import ast
import operator
from typing import Any

from .registry import ToolInputError, require_text


BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def evaluate_expression(params: dict[str, Any]) -> dict[str, Any]:
    expression = require_text(params, "expression")
    try:
        parsed = ast.parse(expression, mode="eval")
        result = evaluate_node(parsed.body)
    except ZeroDivisionError as error:
        raise ToolInputError("division by zero") from error
    except (SyntaxError, ValueError, TypeError) as error:
        raise ToolInputError(f"invalid expression: {error}") from error

    return {"expression": expression, "result": result}


def evaluate_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        raise ToolInputError("only numeric expressions are supported")
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    if isinstance(node, ast.BinOp):
        operator_fn = BINARY_OPERATORS.get(type(node.op))
        if operator_fn is None:
            raise ToolInputError("operator is not supported")
        left = evaluate_node(node.left)
        right = evaluate_node(node.right)
        return operator_fn(left, right)
    if isinstance(node, ast.UnaryOp):
        operator_fn = UNARY_OPERATORS.get(type(node.op))
        if operator_fn is None:
            raise ToolInputError("operator is not supported")
        operand = evaluate_node(node.operand)
        return operator_fn(operand)
    raise ToolInputError("only numeric expressions are supported")
