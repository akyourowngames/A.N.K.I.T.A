from faster_whisper import WhisperModel

model = None

def get_model():
    global model
    if model is None:
        model = WhisperModel("small", device="cpu")
    return model

def transcribe(audio_path):
    m = get_model()
    segments, _ = m.transcribe(audio_path)
    return " ".join(seg.text for seg in segments)
