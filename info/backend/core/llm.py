from groq import Groq
from backend.core.config import GROQ_API_KEY
from backend.core.memory_service import (
    add_message,
    get_history
)

client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """
You are Athena, an intelligent AI virtual assistant.

Always introduce yourself as Athena when asked.

Remember the conversation context provided to you.
"""


def ask_llm_raw(prompt: str):

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.7
    )

    return response.choices[0].message.content


def ask_llm_with_memory(user_message: str):

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    messages.extend(get_history())

    messages.append(
        {
            "role": "user",
            "content": user_message
        }
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.7
    )

    answer = response.choices[0].message.content

    add_message(
        "user",
        user_message
    )

    add_message(
        "assistant",
        answer
    )

    return answer