from backend.database.db import SessionLocal
from backend.database.models import Reminder


class ReminderTool:

    name = "reminder"

    description = (
        "Store and retrieve reminders"
    )

    def run(self, command):

        db = SessionLocal()

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
                    Reminder.due_time == due_time
                ).first()

                if existing_reminder:

                    return (
                        "Reminder already exists."
                    )

                reminder = Reminder(
                    content=content,
                    due_time=due_time
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