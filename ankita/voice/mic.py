import sounddevice as sd
import numpy as np
import wave
import os
import tempfile
import time

SAMPLE_RATE = 16000
DURATION = 5  # seconds

def record_audio(
    duration=DURATION,
    silence_duration: float = 0.5,
    silence_threshold: float = 0.015,
    min_speech_duration: float = 0.2,
):
    max_duration = float(duration)
    print(f"[Voice] Listening...")

    frames: list[np.ndarray] = []
    started = False
    speech_start_t = None
    last_voice_t = None
    start_t = time.time()

    block_dur = 0.03
    blocksize = int(SAMPLE_RATE * block_dur)

    def _rms_int16(block: np.ndarray) -> float:
        if block.size == 0:
            return 0.0
        x = block.astype(np.float32) / 32768.0
        return float(np.sqrt(np.mean(x * x)))

    def callback(indata, _frames, _time_info, status):
        nonlocal started, speech_start_t, last_voice_t
        if status:
            pass
        block = indata[:, 0].copy()
        now = time.time()
        rms = _rms_int16(block)

        if rms >= silence_threshold:
            if not started:
                started = True
                speech_start_t = now
            last_voice_t = now

        if started:
            frames.append(block)

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=blocksize,
            callback=callback,
        ):
            while True:
                time.sleep(block_dur)
                now = time.time()

                if now - start_t >= max_duration:
                    break

                if started and last_voice_t is not None:
                    if (now - last_voice_t) >= silence_duration:
                        if speech_start_t is not None and (last_voice_t - speech_start_t) >= min_speech_duration:
                            break
    finally:
        pass

    if frames:
        audio = np.concatenate(frames).reshape(-1, 1)
    else:
        audio = np.zeros((0, 1), dtype=np.int16)

    print("[Voice] Done recording.")

    temp_path = os.path.join(tempfile.gettempdir(), "ankita_voice.wav")
    with wave.open(temp_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())

    return temp_path
