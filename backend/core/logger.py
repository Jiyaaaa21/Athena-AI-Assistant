import logging
import sys
import os

# Phase 2 fix: FileHandler() does not create its parent directory, so the
# app crashed on import in any environment where ./logs didn't already
# exist (e.g. a fresh clone or container).
os.makedirs("logs", exist_ok=True)

formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s"
)

# ── Phase 17 fix: force UTF-8 everywhere ──────────────────────────────────────
# On Windows, logging.FileHandler() and the default console StreamHandler
# both default to the OS locale encoding (commonly cp1252), not UTF-8.
# Several log messages throughout the codebase contain non-ASCII
# characters (→, —, ✓, etc.) for readability. On cp1252 that raises
# UnicodeEncodeError mid-write, which logging swallows into a "--- Logging
# error ---" dump instead of propagating — meaning the actual log line is
# LOST, not just garbled, and any error logged alongside it can be missed
# entirely. encoding="utf-8" on every handler fixes this at the source
# instead of having to strip non-ASCII characters from every log call
# across the codebase.

# Force the root/uvicorn console handler to UTF-8 too, since uvicorn's
# own access-log and error-log output goes through the standard logging
# module and inherits the same locale-encoding problem on Windows.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # non-fatal — older Python or non-standard stream, fall through


def _console_handler() -> logging.StreamHandler:
    """
    Phase 28 addition: these loggers previously wrote ONLY to a file under
    logs/ -- fine for local dev (readable via `Get-Content logs/*.log`),
    but effectively invisible in production. Render's Logs dashboard only
    captures stdout/stderr, not arbitrary files on disk, and Render's free
    tier disk is ephemeral anyway (wiped on redeploy/restart/idle
    spin-down -- same issue already fixed for document storage). Without
    this, there was no way to see agent/tool/error activity on a deployed
    instance at all. Each logger now writes to both its file (still useful
    for local dev, where it survives restarts within a session) and stdout
    (so `Get-Content` still works locally, and Render's log viewer works
    in production).
    """
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(formatter)
    return h


# ------------------------
# AGENT LOGGER
# ------------------------

agent_logger = logging.getLogger(
    "agent"
)

agent_logger.setLevel(
    logging.INFO
)

agent_handler = logging.FileHandler(
    "logs/agent.log", encoding="utf-8"
)

agent_handler.setFormatter(
    formatter
)

agent_logger.addHandler(
    agent_handler
)
agent_logger.addHandler(_console_handler())

# ------------------------
# TOOL LOGGER
# ------------------------

tool_logger = logging.getLogger(
    "tools"
)

tool_logger.setLevel(
    logging.INFO
)

tool_handler = logging.FileHandler(
    "logs/tools.log", encoding="utf-8"
)

tool_handler.setFormatter(
    formatter
)

tool_logger.addHandler(
    tool_handler
)
tool_logger.addHandler(_console_handler())

# ------------------------
# ERROR LOGGER
# ------------------------

error_logger = logging.getLogger(
    "errors"
)

error_logger.setLevel(
    logging.ERROR
)

error_handler = logging.FileHandler(
    "logs/errors.log", encoding="utf-8"
)

error_handler.setFormatter(
    formatter
)

error_logger.addHandler(
    error_handler
)
error_logger.addHandler(_console_handler())