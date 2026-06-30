from backend.database.db import SessionLocal
from backend.database.models import Reminder
from backend.core.request_context import get_current_user_id


class ReminderTool:

    name = "reminder"

    description = (
        "Store and retrieve reminders"
    )

    def run(self, command):

        db = SessionLocal()

        # Phase 12: scope every read/write to the authenticated user issuing
        # the chat request (see core/request_context.py).
        user_id = get_current_user_id()

        try:

            # save:task|time

            if command.startswith(
                "save:"
            ):

                payload = command.replace(
                    "save:",
                    ""
                ).strip()

                if "|" not in payload:

                    return (
                        "Invalid reminder format."
                    )

                content, due_time = (
                    payload.split(
                        "|",
                        1
                    )
                )

                content = content.strip()
                due_time = due_time.strip()

                existing_reminder = db.query(
                    Reminder
                ).filter(
                    Reminder.content == content,
                    Reminder.due_time == due_time,
                    Reminder.user_id == user_id,
                ).first()

                if existing_reminder:

                    return (
                        "Reminder already exists."
                    )

                reminder = Reminder(
                    content=content,
                    due_time=due_time,
                    user_id=user_id,
                )

                db.add(
                    reminder
                )

                db.commit()

                return (
                    "Reminder saved successfully."
                )

            elif command == "list":

                reminders = db.query(
                    Reminder
                ).filter(
                    Reminder.user_id == user_id
                ).all()

                if not reminders:

                    return (
                        "No reminders found."
                    )

                result = []

                for reminder in reminders:

                    result.append(
                        f"{reminder.id}. "
                        f"{reminder.content} "
                        f"(Due: {reminder.due_time})"
                    )

                return "\n".join(
                    result
                )

            return (
                "Invalid reminder command."
            )

        finally:

            db.close()
