# Wiring these files in

## 1. `backend/tools/registry.py` — register the two new tools

```python
from backend.tools.calculator import CalculatorTool
from backend.tools.rag_tool import RAGTool
from backend.tools.weather import WeatherTool
from backend.tools.news import NewsTool
from backend.tools.notes import NotesTool
from backend.tools.reminders import ReminderTool
from backend.tools.email_tool import EmailTool      # NEW
from backend.tools.action_tool import ActionTool    # NEW


tool_instances = [
    CalculatorTool(),
    RAGTool(),
    WeatherTool(),
    NewsTool(),
    NotesTool(),
    ReminderTool(),
    EmailTool(),      # NEW
    ActionTool(),     # NEW
]

TOOLS = {
    tool.name: tool
    for tool in tool_instances
}
```

## 2. `backend/agents/orchestrator.py` — register the two new agents

Add the imports near the other agent imports:

```python
from backend.agents.email_agent import EmailAgent      # NEW
from backend.agents.action_agent import ActionAgent    # NEW
```

Add both to `ALL_AGENTS`:

```python
ALL_AGENTS: list[BaseAgent] = [
    ResearchAgent(),
    PlannerAgent(),
    NoteAgent(),
    ReminderAgent(),
    TimerAgent(),
    CalendarAgent(),
    RAGAgent(),
    WebSearchAgent(),
    EmailAgent(),      # NEW
    ActionAgent(),     # NEW
]
```

Add both to `_QUESTION_AGENT_HINTS` so a bare "yes" reply after a
confirmation question locks back to the right agent (this is the same
mechanism that already makes reminder/note follow-ups work):

```python
_QUESTION_AGENT_HINTS: dict[str, str] = {
    "remind":   "reminder",
    "reminder": "reminder",
    "note":     "note",
    "rename":   "note",
    "goal":     "planner",
    "project":  "planner",
    "time":     "reminder",
    "send this": "email",       # NEW
    "should i send": "email",   # NEW
    "trigger": "action",        # NEW
}
```

## 3. `main.py` — mount the new actions API

```python
from backend.api.actions import router as actions_router   # NEW, near the other Phase 16 imports

...

app.include_router(actions_router, dependencies=_auth_required)   # NEW, alongside goals/projects/etc.
```

## 4. `backend/core/config.py` — append the block in `config_additions.py`

Paste the contents of `config_additions.py` onto the end of your real
`core/config.py`.

## 5. `backend/database/models.py` — append the block in `models_additions.py`

Paste the `UserAction` class from `models_additions.py` onto the end of
your real `database/models.py`. On SQLite (dev default) this table is
created automatically on next `uvicorn` startup via `run_migrations()` —
no extra step needed. On Postgres, run:

```bash
alembic upgrade head
```

which will pick up `0003_phase22_email_actions.py`.

## 6. `.env` — add SMTP config if you want real email delivery

```env
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=<gmail app password, not your real password>
SMTP_USE_TLS=true
```

Leave `EMAIL_PROVIDER=dev` (or unset) to keep the old log-only behavior —
`EmailAgent` still works end-to-end in that mode, it just tells the user
up front that nothing will actually be delivered.

## 7. Full file list added

```
backend/core/email.py               (replaces existing — real SMTP branch)
backend/tools/email_tool.py         (new)
backend/tools/action_tool.py        (new)
backend/agents/email_agent.py       (new)
backend/agents/action_agent.py      (new)
backend/api/actions.py              (new)
alembic/versions/0003_phase22_email_actions.py  (new)
```

Plus append-only edits to:
```
backend/core/config.py       (append config_additions.py)
backend/database/models.py   (append models_additions.py)
backend/tools/registry.py    (2 lines, see above)
backend/agents/orchestrator.py (imports + 2 list entries + 3 dict entries)
main.py                      (1 import + 1 include_router line)
```

## Not included (frontend)

No Settings-page UI for managing connected actions was added — the API
(`GET/POST/PUT/DELETE /actions`, `POST /actions/{id}/test`) is ready for
a frontend panel, but building that panel wasn't in scope for this pass.
Until then, actions can be registered directly via the API (e.g. from the
API docs at `/docs`, or curl) — say the word if you want the Settings UI
built too.

## Known limitation

`EmailAgent` can't resolve a name like "dad" to a real address — there's
no contacts/address-book feature yet, so it will ask for the literal
email address when it can't already see one. That's a reasonable next
addition if you send emails to the same people often.
