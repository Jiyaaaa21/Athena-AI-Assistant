import asyncio
import edge_tts
import os


async def speak_async(text):

    communicate = edge_tts.Communicate(
        text,
        voice="en-US-AriaNeural"
    )

    await communicate.save(
        "athena_response.mp3"
    )


def speak(text):

    asyncio.run(
        speak_async(text)
    )

    os.startfile(
        "athena_response.mp3"
    )