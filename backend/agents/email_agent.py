"""
backend/agents/email_agent.py  —  Phase 22

Lets the user say "email dad and tell him I'll be late" and have Athena
draft + send it. Sending is irreversible, so — unlike notes/reminders —
this agent never sends on the first pass. It always shows a draft and
ends with a confirmation question ("Send this?"), which the orchestrator's
existing pending-question detector (see orchestrator.py) will route the
next turn straight back here rather than re-classifying it as a new
request. A "yes"/"send it"/"confirm" reply on the locked-in next turn is
what actually triggers the send.

State isn't stored anywhere explicit — like every other agent here, the
draft is *reconstructed* each turn from conversation history via the LLM.
This matches ReminderAgent/NoteAgent's existing approach rather than
introducing a new session-state mechanism.
"""
from __future__ import annotations

import json
import re

from backend.agents.base import BaseAgent, AgentResult
from backend.core.llm import ask_llm_raw
from backend.core.logger import agent_logger
from backend.tools.email_tool import EmailTool
from backend.core.config import EMAIL_PROVIDER

_email_tool = EmailTool()

_EMAIL_KEYWORDS = {
    "email", "e-mail", "send an email", "send a mail", "mail to",
    "send this to", "write to", "compose an email",
}

_CONFIRM_YES = re.compile(
    r"^\s*(yes|yep|yeah|send it|confirm|go ahead|do it|sure)\b", re.IGNORECASE
)
_CONFIRM_NO = re.compile(
    r"^\s*(no|nope|cancel|don'?t|nevermind|never mind|stop)\b", re.IGNORECASE
)


class EmailAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "email"

    @property
    def description(self) -> str:
        return (
            "Composes and sends emails on the user's behalf. Always drafts "
            "the email and asks for confirmation before actually sending."
        )

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in _EMAIL_KEYWORDS)

    def run(self, query: str, context: dict | None = None) -> AgentResult:
        # A bare "yes"/"no" on its own can't be classified by keyword —
        # the orchestrator's pending-state lock is what gets a bare
        # confirmation routed here at all. If it's clearly a "no", bail out
        # without touching the draft further.
        if _CONFIRM_NO.match(query.strip()):
            return AgentResult(
                answer="Okay, I won't send that.",
                agent_name=self.name,
            )

        history = self.get_conversation_context(turns=8)
        draft = self._extract_draft(query, history)

        if not draft or not draft.get("to") or not draft.get("body"):
            return AgentResult(
                answer=(
                    "Who should I send this to, and what would you like it "
                    "to say?"
                ),
                agent_name=self.name,
                metadata={"incomplete": True},
            )

        if "@" not in draft["to"]:
            # There's no contacts/address-book feature yet — Athena can't
            # resolve "dad" or "the landlord" to a real address, so ask
            # rather than let the send silently fail at the tool layer.
            return AgentResult(
                answer=f"What's {draft['to']}'s email address?",
                agent_name=self.name,
                metadata={"incomplete": True, "draft": draft},
            )

        # Was the last Athena turn already showing this same draft, and is
        # this message an affirmative confirmation? Then send for real.
        was_confirming = "send this" in (history or "").lower() or "shall i send" in (history or "").lower()
        if was_confirming and _CONFIRM_YES.match(query.strip()):
            result = _email_tool.run(
                f"send:{draft['to']}|{draft['subject']}|{draft['body']}"
            )
            agent_logger.info("[EmailAgent] send attempted to=%s", draft["to"])
            return AgentResult(answer=result, agent_name=self.name)

        # Otherwise: show the draft and ask for confirmation. Ending on a
        # literal "?" is what the orchestrator's pending-question regex
        # keys off of, so the next turn locks back to this agent.
        preview = (
            f"Here's the draft:\n\n"
            f"To: {draft['to']}\n"
            f"Subject: {draft['subject']}\n\n"
            f"{draft['body']}\n\n"
        )
        if EMAIL_PROVIDER == "dev":
            preview += (
                "(Note: email sending isn't configured for real delivery yet "
                "— this will only be logged, not actually delivered.)\n\n"
            )
        preview += "Should I send this?"

        return AgentResult(
            answer=preview,
            agent_name=self.name,
            metadata={"incomplete": True, "draft": draft},
        )

    def _extract_draft(self, query: str, history: str) -> dict | None:
        prompt = (
            f"{history}\n"
            f"The user wants to send an email. Extract the recipient, "
            f"subject, and body from the request and conversation history.\n"
            f"If the recipient is a name rather than an email address (e.g. "
            f"'dad'), use that name as-is in the 'to' field — a later step "
            f"resolves it to a real address.\n"
            f"Write the body in a natural, appropriately toned way based on "
            f"what the user asked for; don't just repeat their instruction "
            f"verbatim.\n\n"
            f'Respond ONLY as JSON: {{"to": "...", "subject": "...", "body": "..."}}\n'
            f"Use empty strings for anything not determinable.\n\n"
            f"Request: {query}"
        )
        raw = ask_llm_raw(prompt).strip()
        # Strip markdown code fences if the model added them anyway
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            agent_logger.warning("[EmailAgent] failed to parse draft JSON: %r", raw)
            return None

        to = (data.get("to") or "").strip()
        subject = (data.get("subject") or "").strip() or "(no subject)"
        body = (data.get("body") or "").strip()

        if not to or not body:
            return None
        return {"to": to, "subject": subject, "body": body}
