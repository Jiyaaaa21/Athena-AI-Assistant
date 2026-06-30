from backend.voice.stt import listen
from backend.voice.tts import speak
from backend.agents.agent import process_query


print("Athena Voice Mode Started")
print("Say 'goodbye' to exit.\n")

while True:

    user_text = listen()

    if not user_text:
        continue

    print("User:", user_text)

    if user_text.lower() in [
        "goodbye",
        "exit",
        "stop",
        "bye"
    ]:

        speak("Goodbye. Have a great day.")

        print("Athena: Goodbye.")

        break

    answer = process_query(
        user_text
    )

    print("Athena:", answer)

    speak(answer)