"""
backend/tools/calculator.py — Phase 29 security fix

This tool previously called raw eval(input_data) on a string the LLM
constructs from a user's natural-language message. eval() executes
ANY Python expression, not just arithmetic -- something like
`__import__('os').environ` would have run successfully and leaked
every secret this process holds (DATABASE_URL, JWT_SECRET_KEY, every
API key). The old routing path that would have fed user-influenced
text into this (backend/tools/registry.py, backend/prompts/
tool_router_prompt.py) turned out to be dead code, superseded by the
agent-based orchestrator -- so this was never actually reachable in
production. But it's exactly the kind of landmine worth defusing
properly rather than leaving in place, especially while fixing it up
to be a real, live capability (see agents/calculator_agent.py).

This version evaluates expressions by walking a restricted Python AST
and only ever allowing numeric literals, basic arithmetic operators,
and a small allowlist of safe math functions -- there is no code path
here that can reach an import, an attribute access, a function call
outside the allowlist, or anything else capable of touching the rest
of the process. Malformed or disallowed input raises ValueError, which
.run() below turns into a clean error string.
"""

from __future__ import annotations

import ast
import math
import operator

from backend.tools.base import BaseTool

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_UNARYOPS = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Deliberately small: enough for genuinely common "do some math for me"
# requests, nothing that expands the reachable surface (no __builtins__,
# no arbitrary attribute access -- these are looked up by name from this
# fixed dict only).
_ALLOWED_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "floor": math.floor,
    "ceil": math.ceil,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}

_ALLOWED_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
}


def _eval_node(node: ast.AST):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value!r}")

    if isinstance(node, ast.BinOp):
        op_fn = _ALLOWED_BINOPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op_fn(_eval_node(node.left), _eval_node(node.right))

    if isinstance(node, ast.UnaryOp):
        op_fn = _ALLOWED_UNARYOPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_fn(_eval_node(node.operand))

    if isinstance(node, ast.Name):
        if node.id in _ALLOWED_CONSTANTS:
            return _ALLOWED_CONSTANTS[node.id]
        raise ValueError(f"Unknown name: {node.id!r}")

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise ValueError("Only a fixed set of math functions are allowed")
        if node.keywords:
            raise ValueError("Keyword arguments are not supported")
        args = [_eval_node(a) for a in node.args]
        return _ALLOWED_FUNCS[node.func.id](*args)

    # Anything else -- attribute access, subscripts, comprehensions,
    # lambdas, imports, string/list/dict literals, ... -- is rejected.
    raise ValueError(f"Unsupported expression: {type(node).__name__}")


def safe_eval_math(expression: str):
    """Parses and evaluates a restricted arithmetic expression. Raises
    ValueError (never executes arbitrary code) on anything outside the
    allowlist above."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Couldn't parse that as a math expression: {e}")
    return _eval_node(tree)


class CalculatorTool(BaseTool):

    @property
    def name(self):
        return "calculator"

    @property
    def description(self):
        return "Performs mathematical calculations safely (arithmetic + common math functions)."

    def run(self, input_data: str) -> str:
        try:
            result = safe_eval_math(input_data)
            return str(result)
        except ValueError as e:
            return f"Error: {e}"
        except ZeroDivisionError:
            return "Error: division by zero"
        except Exception as e:
            return f"Error: {e}"