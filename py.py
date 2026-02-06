import asyncio
import os
from dotenv import load_dotenv
from deepgram import (
    DeepgramClient,
    LiveTranscriptionEvents,
    LiveOptions,
    Microphone
)

load_dotenv()
API_KEY = "YOUR_DEEPGRAM_API_KEY"

async def main():
    # 1. Initialize the Deepgram Client
    client = DeepgramClient(API_KEY)

    # 2. Define the connection
    dg_connection = client.listen.asynchronous_live.v("1")

    # 3. Define what happens when we get a transcript back
    def on_message(self, result, **kwargs):
        sentence = result.channel.alternatives[0].transcript
        if len(sentence) > 0:
            # result.channel.alternatives[0].words contains the speaker tag for each word
            # For simplicity, we grab the speaker tag of the first word in this chunk
            speaker = result.channel.alternatives[0].words[0].speaker
            print(f"[Speaker {speaker}]: {sentence}")

    # 4. Attach the event handler
    dg_connection.on(LiveTranscriptionEvents.TranscriptReceived, on_message)

    # 5. Configure the Live Options (Crucial: set diarize=True)
    options = LiveOptions(
        model="nova-3",
        language="en-US",
        smart_format=True,
        diarize=True,      # This enables speaker separation
        interim_results=False # Set to True if you want faster but less accurate "preview" text
    )

    # 6. Start the connection and the microphone
    if await dg_connection.start(options) is False:
        print("Failed to connect to Deepgram")
        return

    # Open microphone stream (16kHz is standard for Deepgram)
    microphone = Microphone(dg_connection.send)

    print("Listening... (Press Ctrl+C to stop)")
    microphone.start()

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        microphone.stop()
        await dg_connection.finish()

if __name__ == "__main__":
    asyncio.run(main())