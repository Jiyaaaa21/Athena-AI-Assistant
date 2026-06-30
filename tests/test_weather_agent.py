from backend.agents.agent import process_query

response = process_query(
    "What is the weather in Delhi?"
)

print(response)