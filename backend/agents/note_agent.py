"""
agents/note_agent.py  —  Phase 13
Phase 15 fix: Added rename/delete/update intents.
Previously "rename the note to X" was classified as "save" and created
a brand new note instead of renaming the existing one. Now the intent
detector handles: save | rename | delete | update | list | search | summarise
and each maps to the correct database operation.
"""

from __future__ import annotations

from typing import Generator

from backend.agents.base import BaseAgent, AgentResult
from backend.core.llm import ask_llm_raw, ask_llm_raw_stream
from backend.core.logger import agent_logger
from backend.tools.notes import NotesTool
from backend.database.db import SessionLocal
from backend.database.models import Note
from backend.core.request_context import get_current_user_id

_notes_tool = NotesTool()

_NOTE_KEYWORDS = {
    "note", "notes", "write down", "jot", "save", "remember",
    "summarise my notes", "summarize my notes", "search notes",
    "find note", "what notes", "my notes", "note about",
    "capture", "record", "store", "keep",
    "rename", "rename the note", "delete note", "remove note",
    "update note", "edit note", "change the note",
    # Phase 15: append / update triggers
    "add to the note", "add to my note", "add to an existing",
    "existing note", "the existing note", "change the existing",
    "append to", "add to it", "update the note",
}


class NoteAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "note"

    @property
    def description(self) -> str:
        return (
            "Intelligent note-taking agent. Use for saving notes, searching "
            "existing notes, summarising note collections, or organising "
            "captured information. Also handles renaming, editing, and "
            "deleting existing notes."
        )

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in _NOTE_KEYWORDS)

    # ── Intent detection ──────────────────────────────────────────────────────

    def _detect_intent(self, query: str) -> str:
        """Returns: save | rename | delete | update | list | search | summarise"""
        q = query.lower()
        if any(w in q for w in ("summarise", "summarize", "summary", "overview of my notes")):
            return "summarise"
        if any(w in q for w in ("rename", "rename the note", "change the title", "change the name")):
            return "rename"
        if any(w in q for w in ("delete", "remove", "trash", "get rid of")):
            return "delete"

        # ── Update / append triggers ──────────────────────────────────────────
        # IMPORTANT: "add a note" and "add note" are SAVE intents, not update.
        # Only treat as update when the user clearly refers to an EXISTING note.
        is_new_note = any(p in q for p in (
            "add a note", "add note", "create a note", "create note",
            "save a note", "save note", "new note", "make a note",
            "write a note", "write down", "note down",
        ))

        update_triggers = any(w in q for w in (
            "update", "edit", "modify",
            "change the note", "change the existing", "change existing",
            "add to the note", "add to my note", "add to an existing",
            "add to existing", "append", "append to",
            "also buy", "also add",
            "update the note", "update my note",
            "existing note", "existing shopping", "existing list",
            "as well", "along with",
            "add items", "add more", "add these", "include these",
            "include in the note", "include in my note",
            "in the note", "in my note", "in the list", "in my list",
            "put it in the note", "put in the note",
        ))

        if update_triggers and not is_new_note:
            # Extra guard: "as well" / "along with" only mean update if a
            # note-like word is nearby
            if any(w in q for w in ("as well", "along with")):
                if not any(n in q for n in ("note", "list", "existing", "add", "update")):
                    return "save"
            return "update"

        if any(w in q for w in ("search", "find", "look for", "which note", "note about")):
            return "search"
        if any(w in q for w in ("list", "show", "what notes", "my notes", "all notes")):
            return "list"
        return "save"

    def _get_all_notes(self) -> list[dict]:
        db = SessionLocal()
        try:
            user_id = get_current_user_id()
            notes = db.query(Note).filter(Note.user_id == user_id)\
                      .order_by(Note.id.desc()).all()
            return [{"id": n.id, "title": n.title or "", "content": n.content or ""} for n in notes]
        finally:
            db.close()

    def _get_most_recent_note(self) -> dict | None:
        """Returns the most recently created note for the current user."""
        db = SessionLocal()
        try:
            user_id = get_current_user_id()
            note = db.query(Note).filter(Note.user_id == user_id)\
                     .order_by(Note.id.desc()).first()
            if not note:
                return None
            return {"id": note.id, "title": note.title or "", "content": note.content or ""}
        finally:
            db.close()

    def _find_note_by_ref(self, query: str, all_notes: list[dict]) -> dict | None:
        """
        Use the LLM + conversation history to identify which note the user
        is referring to. Falls back to most recent if nothing specific is mentioned.
        """
        if not all_notes:
            return None

        # Single note — must be it
        if len(all_notes) == 1:
            return all_notes[0]

        q = query.lower()
        vague = any(p in q for p in ("the note", "that note", "this note", "it", "existing note", "the existing"))
        specific = any(p in q for p in ("titled", "called", "named", "about", "on ", "for ", "grocery", "stationary"))

        if vague and not specific:
            # Use conversation history to identify the note
            history = self.get_conversation_context(turns=6)
            notes_summary = "\n".join(
                f"ID:{n['id']} Title:{n['title']!r} Preview:{n['content'][:80]}"
                for n in all_notes[:15]
            )
            prompt = (
                f"{history}\n"
                f"The user said: {query!r}\n\n"
                f"Available notes:\n{notes_summary}\n\n"
                f"Which note ID is the user referring to based on conversation context? "
                f"Return ONLY the numeric ID, nothing else."
            )
            raw = ask_llm_raw(prompt).strip()
            try:
                target_id = int(raw)
                for n in all_notes:
                    if n["id"] == target_id:
                        return n
            except (ValueError, TypeError):
                pass
            return all_notes[0]  # most recent fallback

        notes_summary = "\n".join(
            f"ID:{n['id']} Title:{n['title']!r} Preview:{n['content'][:80]}"
            for n in all_notes[:15]
        )
        prompt = (
            f"A user said: {query!r}\n\n"
            f"Available notes:\n{notes_summary}\n\n"
            f"Which note ID is the user referring to? "
            f"Return ONLY the numeric ID, nothing else. "
            f"If unclear, return the most recently created one (first in the list)."
        )
        raw = ask_llm_raw(prompt).strip()
        try:
            target_id = int(raw)
            for n in all_notes:
                if n["id"] == target_id:
                    return n
        except (ValueError, TypeError):
            pass
        return all_notes[0]

    def _extract_new_name(self, query: str) -> str:
        """Extract the new title from a rename query."""
        prompt = (
            f"Extract the new note title/name from this instruction.\n"
            f"Return ONLY the new title text, nothing else, no quotes.\n\n"
            f"Instruction: {query}"
        )
        return ask_llm_raw(prompt).strip().strip('"').strip("'")

    def _rename_note(self, note_id: int, new_title: str) -> bool:
        db = SessionLocal()
        try:
            user_id = get_current_user_id()
            note = db.query(Note).filter(
                Note.id == note_id, Note.user_id == user_id
            ).first()
            if not note:
                return False
            note.title = new_title
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()

    def _delete_note(self, note_id: int) -> bool:
        db = SessionLocal()
        try:
            user_id = get_current_user_id()
            note = db.query(Note).filter(
                Note.id == note_id, Note.user_id == user_id
            ).first()
            if not note:
                return False
            db.delete(note)
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()

    def _update_note_content(self, note_id: int, new_content: str) -> bool:
        db = SessionLocal()
        try:
            user_id = get_current_user_id()
            note = db.query(Note).filter(
                Note.id == note_id, Note.user_id == user_id
            ).first()
            if not note:
                return False
            note.content = new_content
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()

    def _structure_note(self, raw_input: str) -> tuple[str, str]:
        """Returns (title, content) for the new note."""
        prompt = (
            f"Convert the following into a clean note.\n"
            f"Return EXACTLY two lines:\n"
            f"Line 1: The note title (short, clear)\n"
            f"Line 2 onwards: The note content\n\n"
            f"Input: {raw_input}"
        )
        result = ask_llm_raw(prompt).strip()
        lines = result.split("\n", 1)
        title = lines[0].strip()
        content = lines[1].strip() if len(lines) > 1 else raw_input
        return title, content

    def _summarise_notes(self, notes: list[dict]) -> str:
        if not notes:
            return "You have no notes yet."
        notes_text = "\n\n".join(
            f"Note {n['id']} — {n['title']}:\n{n['content'][:300]}" for n in notes[:20]
        )
        prompt = (
            f"Summarise the following notes into a concise overview. "
            f"Group by theme if applicable. Highlight key topics.\n\n{notes_text}"
        )
        return ask_llm_raw(prompt)

    def _search_notes(self, query: str, notes: list[dict]) -> tuple[str, list[dict]]:
        if not notes:
            return "No notes found to search.", []
        notes_text = "\n".join(
            f"[ID:{n['id']}] {n['title']} — {n['content'][:200]}" for n in notes[:30]
        )
        prompt = (
            f"From these notes, find the ones most relevant to: {query!r}\n\n"
            f"Notes:\n{notes_text}\n\n"
            f"Return only the IDs of relevant notes as a comma-separated list (e.g. 1,3,7). "
            f"If none are relevant, return NONE."
        )
        raw = ask_llm_raw(prompt).strip()
        if raw.upper() == "NONE" or not raw:
            return "No matching notes found.", []
        relevant_ids = set()
        for part in raw.split(","):
            try:
                relevant_ids.add(int(part.strip()))
            except ValueError:
                pass
        relevant = [n for n in notes if n["id"] in relevant_ids]
        if not relevant:
            return "No matching notes found.", []
        result_text = "\n\n".join(
            f"**{n['title']}** (ID {n['id']}):\n{n['content']}" for n in relevant
        )
        return f"Found {len(relevant)} matching note(s):\n\n{result_text}", relevant

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, query: str, context: dict | None = None) -> AgentResult:
        steps = []
        agent_logger.info(f"[NoteAgent] query={query!r}")

        intent = self._detect_intent(query)
        steps.append(f"Detected intent: {intent}")

        if intent == "rename":
            steps.append("Finding target note…")
            all_notes = self._get_all_notes()
            target = self._find_note_by_ref(query, all_notes)
            if not target:
                answer = "I couldn't find a note to rename. Do you have any notes saved?"
            else:
                new_name = self._extract_new_name(query)
                steps.append(f"Renaming note {target['id']} to '{new_name}'…")
                ok = self._rename_note(target["id"], new_name)
                if ok:
                    answer = f"✓ Note renamed to **{new_name}**."
                else:
                    answer = "I couldn't rename the note — it may not exist anymore."

        elif intent == "delete":
            steps.append("Finding target note…")
            all_notes = self._get_all_notes()
            target = self._find_note_by_ref(query, all_notes)
            if not target:
                answer = "I couldn't find a note to delete."
            else:
                title_preview = target["title"] or target["content"][:40]
                steps.append(f"Deleting note {target['id']}…")
                ok = self._delete_note(target["id"])
                answer = (
                    f"✓ Note deleted: **{title_preview}**."
                    if ok else "I couldn't delete that note."
                )

        elif intent == "update":
            steps.append("Finding target note…")
            all_notes = self._get_all_notes()
            target = self._find_note_by_ref(query, all_notes)
            if not target:
                answer = "I couldn't find a note to update."
            else:
                # Detect whether user wants to APPEND or REPLACE
                q = query.lower()
                is_append = any(w in q for w in (
                    "add", "append", "also", "as well", "along with",
                    "include", "in addition", "plus", "and also",
                ))
                if is_append:
                    prompt = (
                        f"The user wants to ADD to an existing note.\n"
                        f"Current note title: {target['title']}\n"
                        f"Current note content: {target['content']}\n"
                        f"User instruction: {query}\n\n"
                        f"Return ONLY the complete updated note content "
                        f"(original content + new additions merged naturally). "
                        f"Do not include the title. Do not add explanations."
                    )
                else:
                    prompt = (
                        f"The user wants to UPDATE an existing note.\n"
                        f"Current note title: {target['title']}\n"
                        f"Current note content: {target['content']}\n"
                        f"User instruction: {query}\n\n"
                        f"Return ONLY the new note content. "
                        f"Do not include the title. Do not add explanations."
                    )
                new_content = ask_llm_raw(prompt).strip()
                ok = self._update_note_content(target["id"], new_content)
                if ok:
                    action_word = "updated" if not is_append else "updated (added to)"
                    answer = (
                        f"✓ Note {action_word}: **{target['title']}**\n\n"
                        f"{new_content}"
                    )
                else:
                    answer = "I couldn't update that note."

        elif intent == "save":
            steps.append("Structuring note content…")
            title, content = self._structure_note(query)
            result = _notes_tool.run(f"save:{title}\n{content}")
            answer = (
                f"✓ Note saved:\n\n**{title}**\n{content}"
                if "successfully" in result.lower()
                else f"Note result: {result}"
            )

        elif intent == "list":
            steps.append("Retrieving all notes…")
            notes = self._get_all_notes()
            if not notes:
                answer = "You have no notes yet. Try asking me to save something!"
            else:
                answer = f"You have **{len(notes)} note(s)**:\n\n"
                answer += "\n\n".join(
                    f"**{i+1}. {n['title'] or 'Untitled'}**\n{n['content'][:150]}"
                    for i, n in enumerate(notes[:20])
                )

        elif intent == "summarise":
            steps.append("Loading notes for summarisation…")
            notes = self._get_all_notes()
            steps.append(f"Summarising {len(notes)} notes…")
            answer = self._summarise_notes(notes)

        else:  # search
            steps.append("Searching notes…")
            notes = self._get_all_notes()
            answer, _ = self._search_notes(query, notes)

        return AgentResult(
            answer=answer,
            agent_name=self.name,
            sources=[],
            steps=steps,
            confidence=92,
            metadata={"intent": intent},
        )

    def run_stream(
        self, query: str, context: dict | None = None
    ) -> Generator[str, None, None]:
        agent_logger.info(f"[NoteAgent] stream query={query!r}")
        result = self.run(query, context)
        words = result.answer.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
