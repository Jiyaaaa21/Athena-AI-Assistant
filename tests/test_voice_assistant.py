from backend.voice.stt import listen
from backend.voice.tts import speak
from backend.agents.agent import process_query


user_text = listen()

print("User:", user_text)

answer = process_query(
    user_text
)

print("Athena:", answer)

speak(answer)