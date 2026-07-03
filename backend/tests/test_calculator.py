"""
Tests for backend/tools/calculator.py's safe_eval_math().

This is the highest-value test file in this whole suite: it's the
regression guard for a fixed RCE vulnerability (raw eval() on
LLM-constructed input). If a future edit to calculator.py accidentally
reintroduces something eval()-like, these injection tests should catch
it immediately rather than relying on someone remembering to check by
hand again.
"""

import math

import pytest

from backend.tools.calculator import safe_eval_math, CalculatorTool


class TestLegitimateMath:
    def test_basic_arithmetic(self):
        assert safe_eval_math("2+2") == 4
        assert safe_eval_math("10 - 3") == 7
        assert safe_eval_math("6 * 7") == 42
        assert safe_eval_math("15 / 4") == 3.75

    def test_percentage_style(self):
        assert safe_eval_math("240 * 0.15") == pytest.approx(36.0)

    def test_exponent(self):
        assert safe_eval_math("2**10") == 1024

    def test_functions(self):
        assert safe_eval_math("sqrt(144)") == pytest.approx(12.0)
        assert safe_eval_math("abs(-5)") == 5
        assert safe_eval_math("round(3.7)") == 4
        assert safe_eval_math("max(3, 7, 2)") == 7
        assert safe_eval_math("min(3, 7, 2)") == 2

    def test_constants(self):
        assert safe_eval_math("pi") == pytest.approx(math.pi)
        assert safe_eval_math("e") == pytest.approx(math.e)

    def test_nested_expression(self):
        assert safe_eval_math("(2 + 3) * (4 - 1)") == 15

    def test_negative_numbers(self):
        assert safe_eval_math("-5 + 3") == -2
        assert safe_eval_math("-(3 + 2)") == -5


class TestRejectsCodeExecution:
    """Every one of these must raise ValueError, never actually execute."""

    @pytest.mark.parametrize("payload", [
        "__import__('os').environ",
        "__import__('os').system('echo pwned')",
        "open('/etc/passwd').read()",
        "[].__class__.__base__.__subclasses__()",
        "exec('print(1)')",
        "eval('1+1')",
        "().__class__",
        "globals()",
        "locals()",
        "compile('1+1', '<string>', 'eval')",
        "'a' + 'b'",              # string literals aren't allowed either
        "[1, 2, 3]",              # list literals not allowed
        "{'a': 1}",               # dict literals not allowed
        "lambda: 1",
        "import os",              # not even valid as an expression, but must not crash oddly
    ])
    def test_blocks_injection(self, payload):
        with pytest.raises(ValueError):
            safe_eval_math(payload)

    def test_unknown_function_rejected(self):
        with pytest.raises(ValueError):
            safe_eval_math("os.system('ls')")

    def test_keyword_arguments_rejected(self):
        with pytest.raises(ValueError):
            safe_eval_math("round(3.14159, ndigits=2)")


class TestCalculatorToolWrapper:
    """CalculatorTool.run() is the actual interface agents call -- make
    sure its error-string-not-exception contract holds too."""

    def test_run_returns_string_result(self):
        tool = CalculatorTool()
        assert tool.run("2+2") == "4"

    def test_run_returns_error_string_not_exception(self):
        tool = CalculatorTool()
        result = tool.run("__import__('os').environ")
        assert result.startswith("Error:")

    def test_run_handles_division_by_zero(self):
        tool = CalculatorTool()
        result = tool.run("1/0")
        assert "Error" in result
