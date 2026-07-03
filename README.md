# Athena — AI Operating System

A personal AI assistant with real memory, real integrations, and a real agent architecture — not just a chat wrapper around an LLM. Athena manages your notes, reminders, goals, documents, and calendar; searches the live web; understands images; generates real documents; and proactively surfaces things worth knowing, all through natural conversation.

**Live app:** [athena-ai-assistant.jyoti21.workers.dev](https://athena-ai-assistant.jyoti21.workers.dev)

---

## Features

**Conversation & Intelligence**
- Streaming chat with a multi-agent orchestrator that routes each message to the right specialist (research, notes, reminders, calendar, documents, calculator, web search, and more)
- Persistent memory across conversations, with automatic fact extraction
- Proactive Intelligence — periodically reviews your goals, reminders, and calendar and surfaces genuinely useful nudges unprompted
- Guaranteed-correct math via a sandboxed calculator (the LLM only translates language into an expression; a restricted evaluator does the actual computation)
- Real-time web search (Tavily) for anything beyond the model's training data
- Image understanding — attach a photo and ask about it
- Document generation — ask for a report or summary and get back a real, downloadable PDF

**Personal Data**
- Notes, reminders, goals & projects, routines, countdown timers
- Document upload with RAG (semantic search over your own PDFs)
- Google Calendar integration (OAuth, two-way sync)
- Connected Actions — register your own outbound webhooks (Slack, Home Assistant, IFTTT, etc.) and trigger them from natural language
- Full data export (a zip of everything) and permanent account deletion, on your own terms

**Voice**
- Speech-to-text (Groq Whisper, with a Hugging Face Whisper fallback)
- Text-to-speech with incremental/streaming playback
- Wake-word activation

**Reliability & Cost Control**
- Automatic fallback from Groq to Gemini if the primary LLM provider is unavailable
- Per-user rate limiting across every endpoint that touches a shared, free-tier API budget (chat, voice, document embeddings, search) — protects the whole deployment from being exhausted by one user
- All uploaded documents and generated files persist in Postgres (not local disk), so nothing is lost on redeploy or restart

**Admin**
- User management, deactivation, forced sign-out, and a full audit log
- Usage overview across all users

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python) |
| Frontend | TanStack Start (React + Vite, SSR) |
| Database | PostgreSQL ([Neon](https://neon.tech)), SQLAlchemy ORM, Alembic migrations |
| Primary LLM | [Groq](https://groq.com) (Llama) |
| Fallback LLM | [Gemini](https://aistudio.google.com) |
| Web search | [Tavily](https://tavily.com) |
| Embeddings | Hugging Face Inference API |
| Speech-to-text | Groq Whisper → Hugging Face Whisper (fallback) |
| Text-to-speech | edge-tts |
| Document generation | fpdf2 |
| Auth | JWT (access + refresh tokens), bcrypt |
| Backend hosting | [Render](https://render.com) |
| Frontend hosting | [Cloudflare Workers](https://workers.cloudflare.com) |
| Testing | pytest, GitHub Actions CI |

Every third-party API used has a genuinely free tier — this project is designed to run at zero cost.

---

## Project Structure

```
Athena/
├── main.py                          # FastAPI app entrypoint, router registration
├── requirements.txt                 # Production dependencies
├── requirements-dev.txt             # Test-only dependencies (pytest, pytest-cov)
├── pytest.ini
├── alembic.ini
│
├── .github/
│   └── workflows/
│       └── ci.yml                   # Backend tests + frontend type-check/build on every push
│
├── alembic/
│   ├── env.py
│   └── versions/
│       ├── 0001_initial_schema.py
│       ├── 0002_phase14_assistant.py
│       ├── 0003_phase22_email_actions.py
│       ├── 58f3c14121da_sync_missing_tables.py
│       ├── 0004_pg_document_storage.py     # Documents/embeddings moved to Postgres
│       └── 0005_admin_surface.py            # is_admin flag + audit log
│
├── backend/
│   ├── agents/                       # Specialist agents -- the orchestrator routes each
│   │   │                             # message to whichever of these can_handle() it
│   │   ├── base.py                     # BaseAgent / AgentResult
│   │   ├── orchestrator.py             # Routing logic, ALL_AGENTS registry
│   │   ├── agent.py                    # Legacy process_query() wrapper (GET /chat)
│   │   ├── research_agent.py
│   │   ├── planner_agent.py
│   │   ├── calculator_agent.py         # Safe, guaranteed-correct arithmetic
│   │   ├── document_agent.py           # Real PDF generation
│   │   ├── note_agent.py
│   │   ├── reminder_agent.py
│   │   ├── timer_agent.py
│   │   ├── calendar_agent.py
│   │   ├── rag_agent.py                # Answers from the user's own documents
│   │   ├── web_search_agent.py         # Live web search + news + weather
│   │   ├── email_agent.py
│   │   └── action_agent.py             # Triggers connected webhooks
│   │
│   ├── api/                          # One FastAPI router per feature area
│   │   ├── auth.py                     # signup/login/refresh/password reset
│   │   ├── profile.py                  # profile, avatar, data export, account deletion
│   │   ├── admin.py                    # user management, deactivation, audit log
│   │   ├── chat.py                     # /chat/stream (SSE), GET /chat, in-chat uploads
│   │   ├── documents.py                # Document list/preview/delete
│   │   ├── upload.py                   # Document upload + RAG indexing
│   │   ├── search.py                   # Global + per-document semantic search
│   │   ├── notes.py
│   │   ├── reminders.py
│   │   ├── timers.py
│   │   ├── routines.py
│   │   ├── goals.py
│   │   ├── projects.py
│   │   ├── actions.py                  # Connected-action (webhook) CRUD
│   │   ├── calendar.py                 # Google Calendar OAuth + events
│   │   ├── voice.py                    # STT/TTS endpoints
│   │   ├── briefing.py                 # "Good morning" home-screen summary
│   │   ├── assistant.py                # Natural-language smart-action classifier
│   │   ├── proactive.py                # Proactive-insights feed
│   │   ├── conversations.py
│   │   ├── user_memory.py              # Extracted user facts
│   │   ├── memory.py
│   │   ├── news.py
│   │   ├── weather.py
│   │   ├── analytics.py
│   │   ├── preferences.py
│   │   ├── push.py                     # Web push subscriptions
│   │   └── health.py
│   │
│   ├── auth/
│   │   ├── schemas.py                  # Pydantic request/response models
│   │   ├── service.py                  # User creation, authentication, token rotation
│   │   └── dependencies.py             # get_current_user, require_admin
│   │
│   ├── core/
│   │   ├── config.py                    # All environment variables, single source of truth
│   │   ├── llm.py                       # Groq client + Gemini fallback, vision support
│   │   ├── rate_limit.py                # Per-user sliding-window limiters
│   │   ├── logger.py                    # agent/tool/error loggers (file + stdout)
│   │   ├── security.py                  # Password hashing, JWT signing
│   │   ├── request_context.py           # Per-request current-user contextvar
│   │   ├── memory_service.py            # Chat history read/write
│   │   ├── context_builder.py           # Assembles user context for prompts
│   │   ├── memory_intelligence.py       # Background fact extraction
│   │   ├── auto_title.py                # Auto-titles new conversations
│   │   ├── proactive_engine.py          # Background proactive-insights loop
│   │   ├── reminder_scheduler.py        # Background reminder-firing loop
│   │   ├── push_notifications.py
│   │   ├── push_vapid.py
│   │   └── email.py                     # Password-reset email delivery
│   │
│   ├── database/
│   │   ├── models.py                    # Every SQLAlchemy model
│   │   ├── db.py                        # Engine + session factory
│   │   └── migrate.py                   # SQLite auto-migration for local dev only
│   │
│   ├── integrations/
│   │   └── google_calendar.py           # OAuth flow, event CRUD
│   │
│   ├── rag/
│   │   ├── chunker.py
│   │   ├── embedder.py                  # Hugging Face embeddings
│   │   ├── vector_store.py              # Postgres-backed similarity search
│   │   ├── rag_pipeline.py              # Retrieval + synthesis
│   │   ├── pdf_loader.py                # Text/page-count extraction from uploads
│   │   └── pdf_generator.py             # Renders generated documents to PDF
│   │
│   ├── tools/                        # Low-level tools agents call into
│   │   ├── base.py
│   │   ├── calculator.py                # AST-based safe expression evaluator
│   │   ├── web_search_tool.py           # Tavily
│   │   ├── rag_tool.py
│   │   ├── weather.py
│   │   ├── news.py
│   │   ├── notes.py
│   │   ├── reminders.py
│   │   ├── email_tool.py
│   │   ├── action_tool.py               # Webhook trigger + SSRF guard
│   │   └── direct_return.py
│   │
│   ├── voice/
│   │   ├── stt.py                       # Groq Whisper -> Hugging Face fallback
│   │   └── tts.py                       # edge-tts
│   │
│   └── tests/
│       ├── conftest.py                  # Fixtures: isolated DB, test client, auth users
│       ├── README.md                    # What's covered, how to run, how to extend
│       ├── test_auth.py
│       ├── test_account_deletion.py
│       ├── test_admin.py
│       ├── test_actions.py
│       ├── test_calculator.py
│       ├── test_pdf_generator.py
│       └── test_rate_limit.py
│
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    │
    └── src/
        ├── routeTree.gen.ts          # Auto-generated by TanStack Router -- never edit
        ├── styles.css
        │
        ├── routes/                   # File-based routing -- one file per page
        │   ├── __root.tsx              # Root layout, auth gate
        │   ├── index.tsx                # Home / chat
        │   ├── login.tsx
        │   ├── signup.tsx
        │   ├── forgot-password.tsx
        │   ├── documents.tsx
        │   ├── notes.tsx
        │   ├── reminders.tsx
        │   ├── goals.tsx
        │   ├── routines.tsx
        │   ├── search.tsx
        │   ├── memory.tsx
        │   ├── news.tsx
        │   ├── weather.tsx
        │   ├── analytics.tsx
        │   ├── settings.tsx
        │   └── admin.tsx                # Admin dashboard, gated on is_admin
        │
        ├── components/
        │   ├── athena/                # App-specific components
        │   │   ├── app-shell.tsx
        │   │   ├── app-sidebar.tsx
        │   │   ├── mobile-topbar.tsx
        │   │   ├── composer.tsx          # Message input, attachments, voice
        │   │   ├── message.tsx
        │   │   ├── conversation-manager.tsx
        │   │   ├── command-palette.tsx
        │   │   ├── citation-card.tsx
        │   │   ├── agent-panel.tsx
        │   │   ├── proactive-insights.tsx
        │   │   ├── voice-dialog.tsx
        │   │   ├── voice-orb.tsx
        │   │   ├── waveform.tsx
        │   │   ├── timer-provider.tsx
        │   │   ├── quick-chip.tsx
        │   │   ├── kpi-card.tsx
        │   │   ├── page-header.tsx
        │   │   ├── empty-state.tsx
        │   │   ├── export-menu.tsx
        │   │   └── logo.tsx
        │   └── ui/                    # shadcn/ui primitives (button, card, dialog,
        │                              # alert-dialog, table, input, select, ...)
        │
        ├── stores/                    # Zustand state
        │   ├── auth.ts
        │   ├── chat.ts
        │   ├── conversations.ts
        │   ├── voice.ts
        │   ├── voice-activation.ts
        │   └── sidebar.ts
        │
        ├── hooks/
        │   ├── use-wake-word.ts
        │   ├── use-push-notifications.ts
        │   └── use-reminder-notifications.ts
        │
        └── lib/
            ├── api.ts                   # Main API client (chat, documents, admin, ...)
            ├── voice-api.ts
            ├── push-api.ts
            ├── proactive-api.ts
            ├── streaming-playback-queue.ts
            ├── mock.ts                  # Offline/demo-mode fallback data
            └── utils.ts
```

## Getting Started

### Prerequisites
- Python 3.10+
- Node.js 20+
- A free API key from each of: [Groq](https://console.groq.com), [Google AI Studio](https://aistudio.google.com/apikey) (Gemini), [Tavily](https://tavily.com), [Hugging Face](https://huggingface.co/settings/tokens)

### Backend

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your keys — see Environment Variables below
alembic upgrade head    # only needed against Postgres; SQLite auto-migrates on startup
uvicorn main:app --reload
```

Backend runs at `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173` (or `:8080` depending on your Vite config) and expects the backend at the URL set in `VITE_API_BASE_URL`.

### Running Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

No real API keys or database needed — the test suite uses safe dummy values and an isolated SQLite file. See [`backend/tests/README.md`](backend/tests/README.md) for what's covered.

---

## Environment Variables

Set these in a local `.env` file for development, and in your hosting provider's environment settings (Render for the backend, Cloudflare for the frontend build) for production.

### Required

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | Primary LLM provider. The app won't even start without a value set (a placeholder is fine for local dev if you're not testing chat). |
| `DATABASE_URL` | `sqlite:///athena.db` for local dev, or a Postgres connection string in production. |
| `JWT_SECRET_KEY` | Signs auth tokens. Auto-generates a random one if unset, but set an explicit value in production so tokens survive a restart. |

### Strongly recommended

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Fallback LLM — without it, a Groq outage means chat stops working entirely instead of degrading gracefully. |
| `TAVILY_API_KEY` | Enables real web search. |
| `HF_TOKEN` | Enables document embeddings (RAG) and the Whisper STT fallback. |

### Feature-specific

| Variable | Purpose |
|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT_URI` | Google Calendar integration. |
| `ADMIN_EMAILS` | Comma-separated list of emails auto-promoted to admin at signup/login. |
| `ALLOWED_ORIGINS` | Comma-separated list of frontend origins allowed by CORS. Must match your deployed frontend URL exactly. |
| `FRONTEND_BASE_URL` | Used for password-reset email links and OAuth redirects back to the app. |
| `SMTP_HOST` / `SMTP_USERNAME` / `SMTP_PASSWORD` | Real email delivery for password resets. Defaults to a dev mode that logs the reset token instead of emailing it. |
| `PROACTIVE_ENABLED` | Set to `false` to disable the background proactive-insights engine (useful during local development to avoid burning API quota on every restart). |

See `backend/core/config.py` for the complete, authoritative list with defaults.

### Frontend

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | The backend's URL. |

---

## Deployment

- **Backend** is deployed on Render as a single web service (`uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1`). **Must stay at one worker** — the reminder scheduler and proactive-insights engine run as in-process background threads and would duplicate with more than one worker.
- **Frontend** is deployed on Cloudflare Workers via `npm run build` + `npx wrangler deploy`, auto-triggered on push via GitHub integration.
- **Database** is Neon Postgres. Run `alembic upgrade head` against your production `DATABASE_URL` after any migration is added — this does **not** happen automatically on deploy (see `backend/database/migrate.py`; only SQLite auto-migrates, deliberately, to keep production schema changes explicit).
- Uploaded documents, generated files, and RAG embeddings are stored **in Postgres**, not local disk — Render's free tier disk is ephemeral (wiped on every redeploy, restart, or idle spin-down), so anything written to the filesystem instead of the database would be lost.

---

## CI

Every push and pull request runs, via GitHub Actions:
- The full backend test suite with coverage
- Frontend type-checking (`tsc --noEmit`) and a full build

See `.github/workflows/ci.yml`.

---
