from backend.database.db import SessionLocal
from backend.database.models import Note


class NotesTool:

    name = "notes"

    description = (
        "Store and retrieve notes"
    )

    def run(self, command):

        db = SessionLocal()

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
                    Note.content == note_text
                ).first()

                if existing_note:

                    return (
                        "Note already exists."
                    )

                note = Note(
                    content=note_text
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