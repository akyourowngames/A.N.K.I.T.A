import speech_recognition as sr

recognizer = sr.Recognizer()

def transcribe(audio_path):
    with sr.AudioFile(audio_path) as source:
        audio = recognizer.record(source)
    try:
        return recognizer.recognize_google(audio)
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as e:
        print(f"[STT] Error: {e}")
        return ""
