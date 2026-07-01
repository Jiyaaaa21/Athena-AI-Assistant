"""
backend/agents/action_agent.py  —  Phase 22

Routes "run my X action" / "turn on the lights" / "post this to Slack"
style requests to a user-registered connected action (see
tools/action_tool.py + api/actions.py + database UserAction model).

Like EmailAgent, this confirms before firing — triggering an external
webhook is a real-world side effect Athena can't undo, so the first pass
always names the matched action and asks for confirmation. The exception
is when the user's own registered action explicitly opts out of
confirmation isn't currently supported — kept deliberately simple (always
confirm) rather than adding a config flag that's easy to misuse.
"""
from __future__ import annotations

import re

from backend.agents.base import BaseAgent, AgentResult
from backend.core.llm import ask_llm_raw
from backend.core.logger import agent_logger
from backend.core.request_context import get_current_user_id
from backend.database.db import SessionLocal
from backend.database.models import UserAction
from backend.tools.action_tool import ActionTool

_action_tool = ActionTool()

_ACTION_KEYWORDS = {
    "run my", "trigger my", "trigger the", "run the", "activate",
    "connected action", "my action", "run action", "webhook",
}

_CONFIRM_YES = re.compile(
    r"^\s*(yes|yep|yeah|do it|confirm|go ahead|trigger it|run it)\b", re.IGNORECASE
)
_CONFIRM_NO = re.compile(
    r"^\s*(no|nope|cancel|don'?t|nevermind|never mind|stop)\b", re.IGNORECASE
)


class ActionAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "action"

    @property
    def description(self) -> str:
        return (
            "Triggers a user-registered connected action (a custom webhook "
            "set up in Settings, e.g. a smart-home trigger or Slack post). "
            "Always confirms before triggering."
        )

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        if any(kw in q for kw in _ACTION_KEYWORDS):
            return True
        # Also match directly against the user's own action names, so
        # "lights on" works if they registered an action literally named
        # that, without requiring a "run my ..." prefix every time.
        return self._match_by_name(query) is not None

    def _list_actions(self) -> list[UserAction]:
        db = SessionLocal()
        try:
            return (
                db.query(UserAction)
                .filter(
                    UserAction.user_id == get_current_user_id(),
                    UserAction.enabled == True,  # noqa: E712
                )
                .all()
            )
        finally:
            db.close()

    def _match_by_name(self, query: str) -> UserAction | None:
        q = query.lower()
        for action in self._list_actions():
            if action.name.lower() in q:
                return action
        return None

    def run(self, query: str, context: dict | None = None) -> AgentResult:
        if _CONFIRM_NO.match(query.strip()):
            return AgentResult(answer="Okay, not triggering that.", agent_name=self.name)

        actions = self._list_actions()
        if not actions:
            return AgentResult(
                answer=(
                    "You don't have any connected actions set up yet. You can "
                    "add one in Settings — just needs a name and a webhook URL."
                ),
                agent_name=self.name,
            )

        history = self.get_conversation_context(turns=6)
        was_confirming = "should i trigger" in (history or "").lower()

        matched = self._match_by_name(query)
        if not matched:
            matched = self._resolve_via_llm(query, actions)

        if not matched:
            names = ", ".join(f"'{a.name}'" for a in actions)
            return AgentResult(
                answer=f"I couldn't tell which action you meant. You have: {names}.",
                agent_name=self.name,
                metadata={"incomplete": True},
            )

        if was_confirming and _CONFIRM_YES.match(query.strip()):
            result = _action_tool.run(f"run:{matched.name}|")
            agent_logger.info("[ActionAgent] triggered action=%r", matched.name)
            return AgentResult(answer=result, agent_name=self.name)

        return AgentResult(
            answer=f"Should I trigger '{matched.name}'?",
            agent_name=self.name,
            metadata={"incomplete": True},
        )

    def _resolve_via_llm(self, query: str, actions: list[UserAction]) -> UserAction | None:
        names = [a.name for a in actions]
        prompt = (
            f"The user has these connected actions available: {names}\n"
            f"Which one (if any) does this request refer to: {query!r}\n"
            f"Return ONLY the exact action name from the list, or NONE if "
            f"no reasonable match exists."
        )
        raw = ask_llm_raw(prompt).strip()
        for action in actions:
            if action.name.strip().lower() == raw.strip().lower():
                return action
        return None
