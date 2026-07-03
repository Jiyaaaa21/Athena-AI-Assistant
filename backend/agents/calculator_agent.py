"""
backend/agents/calculator_agent.py — Phase 29

Handles "what's 15% of 240", "calculate 45 * 12", "square root of 144",
"what is 1200 divided by 7", etc.

Design: the LLM is used ONLY to translate the natural-language request
into a clean arithmetic expression -- it is never asked to compute the
actual answer itself, since LLMs are well known to be unreliable at
precise arithmetic (this is exactly the kind of task a calculator tool
exists to make actually correct). The real computation runs through
CalculatorTool, which evaluates expressions via a restricted AST
allowlist (see tools/calculator.py) rather than eval() -- the input
here is LLM-derived from user text, so it needed to be something that
literally cannot execute arbitrary code, not just something that
"probably" won't in practice.
"""
from __future__ import annotations

import re

from backend.agents.base import BaseAgent, AgentResult
from backend.core.llm import ask_llm_raw
from backend.core.logger import agent_logger
from backend.tools.calculator import CalculatorTool

_calculator = CalculatorTool()

_MATH_KEYWORDS = {
    "calculate", "calculation", "what's", "what is", "how much is",
    "square root", "sqrt", "percent", "percentage", "plus", "minus",
    "times", "multiplied by", "divided by", "sum of", "product of",
    "average of",
}
_MATH_SYMBOL_RE = re.compile(r"[0-9].*[+\-*/^%]|[+\-*/^%].*[0-9]")


class CalculatorAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return (
            "Math and calculation agent. Use for arithmetic, percentages, "
            "square roots, and other numeric calculations -- 'what's 15% "
            "of 240', 'calculate 45 times 12', 'square root of 144'. "
            "Guarantees a correct computed answer rather than an LLM's "
            "own (unreliable) arithmetic."
        )

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        if any(kw in q for kw in _MATH_KEYWORDS) and any(c.isdigit() for c in q):
            return True
        return bool(_MATH_SYMBOL_RE.search(q))

    def _extract_expression(self, query: str) -> str | None:
        prompt = (
            "Extract ONLY a clean arithmetic expression from this request, "
            "suitable for evaluation by a calculator. Use only numbers, "
            "+ - * / % ** parentheses, and these function names if needed: "
            "abs, round, min, max, sqrt, floor, ceil, log, log10, sin, cos, "
            "tan, pi, e. Convert percentages to multiplication (e.g. '15% "
            "of 240' -> '240 * 0.15'). Respond with ONLY the expression, "
            "nothing else -- no explanation, no markdown, no equals sign.\n\n"
            f"Request: {query}\n\nExpression:"
        )
        raw = ask_llm_raw(prompt).strip()
        # Strip common LLM formatting artifacts (backticks, leading "=").
        raw = raw.strip("`").strip()
        if raw.startswith("="):
            raw = raw[1:].strip()
        return raw or None

    def run(self, query: str, context: dict | None = None) -> AgentResult:
        steps = ["Extracting the calculation…"]
        expression = self._extract_expression(query)

        if not expression:
            return AgentResult(
                answer="I couldn't figure out what to calculate from that — could you rephrase it as a math question?",
                agent_name=self.name,
                steps=steps,
                confidence=30,
            )

        steps.append(f"Evaluating: {expression}")
        agent_logger.info(f"[CalculatorAgent] query={query!r} expression={expression!r}")
        result = _calculator.run(expression)

        if result.startswith("Error:"):
            return AgentResult(
                answer=(
                    f"I tried to calculate that as `{expression}` but ran into an issue: "
                    f"{result[len('Error: '):]}. Could you rephrase the calculation?"
                ),
                agent_name=self.name,
                steps=steps,
                confidence=30,
                metadata={"expression": expression, "failed": True},
            )

        return AgentResult(
            answer=f"**{expression} = {result}**",
            agent_name=self.name,
            steps=steps,
            confidence=95,
            metadata={"expression": expression, "result": result},
        )