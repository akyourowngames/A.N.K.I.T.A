import asyncio
import edge_tts
import os

VOICE = "en-IN-NeerjaNeural"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "output.mp3")

async def _speak(text):
    communicate = edge_tts.Communicate(text, voice=VOICE)
    await communicate.save(OUTPUT_PATH)

def speak(text):
    asyncio.run(_speak(text))
    os.system(f'start "" "{OUTPUT_PATH}"')
