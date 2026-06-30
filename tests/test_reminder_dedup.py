from backend.tools.reminders import ReminderTool

tool = ReminderTool()

print(
    tool.run(
        "save: Amazon ML application|Friday"
    )
)

print(
    tool.run(
        "save: Amazon ML application|Friday"
    )
)