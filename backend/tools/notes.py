from backend.database.db import SessionLocal
from backend.database.models import Note
from backend.core.request_context import get_current_user_id


class NotesTool:

    name = "notes"

    description = (
        "Store and retrieve notes"
    )

    def run(self, command):

        db = SessionLocal()

        # Phase 12: scope every read/write to the authenticated user issuing
        # the chat request (see core/request_context.py). `run`'s signature
        # is fixed by BaseTool, so this can't be an explicit parameter.
        user_id = get_current_user_id()

        try:

            # Save Note

            if command.startswith(
                "save:"
            ):

                note_text = (
                    command.replace(
                        "save:",
                        ""
                    ).strip()
                )

                existing_note = db.query(
                    Note
                ).filter(
                    Note.content == note_text,
                    Note.user_id == user_id,
                ).first()

                if existing_note:

                    return (
                        "Note already exists."
                    )

                note = Note(
                    content=note_text,
                    user_id=user_id,
                )

                db.add(
                    note
                )

                db.commit()

                return (
                    "Note saved successfully."
                )

            # List Notes

            elif command == "list":

                notes = db.query(
                    Note
                ).filter(
                    Note.user_id == user_id
                ).all()

                if not notes:

                    return (
                        "No notes found."
                    )

                result = []

                for note in notes:

                    result.append(
                        f"{note.id}. "
                        f"{note.content}"
                    )

                return "\n".join(
                    result
                )

            return (
                "Invalid notes command."
            )

        finally:

            db.close()
