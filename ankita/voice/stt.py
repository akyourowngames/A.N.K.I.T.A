import json
import os
import wave
from vosk import Model, KaldiRecognizer

_model = None

def _get_model():
    global _model
    if _model is None:
        model_path = os.getenv("VOSK_MODEL_PATH")
        
        # Validate that the environment path actually exists
        if not model_path or not os.path.exists(model_path):
            # Try to find it in the project root
            project_root = r"C:\Users\anime\3D Objects\New folder\A.N.K.I.T.A"
            potential_paths = [
                os.path.join(project_root, "vosk-model-small-en-us-0.15"),
                os.path.join(project_root, "vosk-model-en-in-0.5")
            ]
            for p in potential_paths:
                if os.path.exists(p):
                    model_path = p
                    break
        
        if model_path and os.path.exists(model_path):
            _model = Model(model_path)
    return _model

def transcribe(audio_path):
    model = _get_model()
    if not model:
        # Fallback to Google if no model found
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        with sr.AudioFile(audio_path) as source:
            audio = recognizer.record(source)
        try:
            return recognizer.recognize_google(audio)
        except:
            return ""

    wf = wave.open(audio_path, "rb")
    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(True)

    results = []
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            part = json.loads(rec.Result())
            if part.get("text"):
                results.append(part["text"])
    
    final = json.loads(rec.FinalResult())
    if final.get("text"):
        results.append(final["text"])

    return " ".join(results).strip()
