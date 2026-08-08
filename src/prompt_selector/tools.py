"""A small tool registry so tool-using techniques are executable, not decorative.

Hosts register their own tools; the built-ins are deterministic and side-effect
free so a ReAct benchmark measures the loop rather than the network.
"""

from __future__ import annotations

import ast
import json
import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class ToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]

    def declaration(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def declarations(self) -> list[dict[str, Any]]:
        return [tool.declaration() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def __bool__(self) -> bool:
        return bool(self._tools)

    def call(self, name: str, arguments: dict[str, Any] | str) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"error: unknown tool {name!r}; available: {', '.join(self.names()) or 'none'}"
        payload: dict[str, Any]
        if isinstance(arguments, str):
            try:
                payload = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                return f"error: arguments for {name!r} are not valid JSON"
        else:
            payload = arguments or {}
        try:
            return tool.handler(payload)
        except Exception as exc:  # a failing tool is an observation, not a crash
            return f"error: {exc}"


DEFAULT_REGISTRY = ToolRegistry()


_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_evaluate(node.operand))
    raise ToolError("only arithmetic over numeric literals is supported")


def calculate(arguments: dict[str, Any]) -> str:
    expression = str(arguments.get("expression", "")).strip()
    if not expression:
        raise ToolError("expression is required")
    parsed = ast.parse(expression, mode="eval")
    result = _evaluate(parsed)
    return json.dumps({"expression": expression, "result": result})


DEFAULT_REGISTRY.register(
    Tool(
        name="calculator",
        description="Evaluate an arithmetic expression over numeric literals.",
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Arithmetic expression, e.g. (12 * 7) + 3",
                }
            },
            "required": ["expression"],
        },
        handler=calculate,
    )
)
