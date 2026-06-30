from backend.tools.reminders import (
    ReminderTool
)

tool = ReminderTool()

print(
    tool.run(
        "save:Amazon ML application|Friday"
    )
)

print()

print(
    tool.run(
        "save:Athena frontend|Sunday"
    )
)

print()

print(
    tool.run(
        "list"
    )
)