from backend.agents.agent import process_query

print(
    process_query(
        "Save a reminder: Amazon ML application Friday"
    )
)

print()

print(
    process_query(
        "Show reminders"
    )
)