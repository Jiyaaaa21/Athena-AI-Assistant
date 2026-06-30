from backend.agents.agent import process_query

response = process_query(
    "What are the latest AI news headlines?"
)

print(response)