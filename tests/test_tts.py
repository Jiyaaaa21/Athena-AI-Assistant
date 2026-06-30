import asyncio
import edge_tts


TEXT = "Hello Jiya. I am Athena. Your voice system is working."


async def generate():

    communicate = edge_tts.Communicate(
        TEXT,
        voice="en-US-AriaNeural"
    )

    await communicate.save(
        "athena_voice.mp3"
    )


asyncio.run(generate())

print("Audio generated successfully")