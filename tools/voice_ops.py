"""
Voice operations for ANKITA - TTS and Speech-to-Text (STT) via Groq Whisper.
"""
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

import requests
from dotenv import load_dotenv

from llm.client import LLMRuntime, call_chat_once


def speak(text: str, rate: int = 150, volume: int = 100, runtime: Optional[LLMRuntime] = None) -> Dict[str, Any]:
    """
    Speak text aloud using Windows SAPI TTS.
    If LLM runtime is provided, can enhance text for more natural speech.
    """
    try:
        # Optional: Use LLM to make text more natural for speech
        speech_text = text
        if runtime and len(text) > 200:
            try:
                prompt = f"Convert this text to natural spoken language (remove markdown, make conversational): {text[:500]}"
                messages = [{"role": "user", "content": prompt}]
                response = call_chat_once(runtime, messages, tools=None, max_tokens=200)
                enhanced = response.get("content", "").strip()
                if enhanced:
                    speech_text = enhanced
            except:
                pass  # Use original text if LLM fails
        
        # Clean text for PowerShell
        safe_text = speech_text.replace('"', '').replace("'", "").replace("`", "")
        
        # Map rate to SAPI range (-10 to 10)
        sapi_rate = max(-10, min(10, (rate - 150) // 15))
        
        script = (
            f'$sp=New-Object -ComObject SAPI.SpVoice; '
            f'$sp.Rate={sapi_rate}; '
            f'$sp.Volume={volume}; '
            f'$sp.Speak("{safe_text}")'
        )
        
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            timeout=30,
            text=True
        )
        
        if result.returncode == 0:
            return {"ok": True, "spoke": text, "rate": rate, "volume": volume}
        else:
            return {"ok": False, "error": result.stderr or "Speech failed"}
    
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Speech timeout (text too long)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_voices() -> Dict[str, Any]:
    """List installed TTS voices."""
    try:
        script = (
            '$sp=New-Object -ComObject SAPI.SpVoice; '
            '$sp.GetVoices() | ForEach-Object { Write-Output $_.GetDescription() }'
        )
        
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            timeout=10,
            text=True
        )
        
        if result.returncode == 0:
            voices = [v.strip() for v in result.stdout.strip().split('\n') if v.strip()]
            return {"ok": True, "voices": voices, "count": len(voices)}
        else:
            return {"ok": False, "error": result.stderr or "Failed to list voices"}
    
    except Exception as e:
        return {"ok": False, "error": str(e)}


def speak_with_emotion(text: str, emotion: str, runtime: Optional[LLMRuntime] = None) -> Dict[str, Any]:
    """
    Speak text with emotional tone using LLM to adjust rate and volume.
    Emotions: happy, sad, excited, calm, urgent, angry
    """
    if not runtime:
        return speak(text, rate=150, volume=100)
    
    try:
        # Ask LLM for optimal speech parameters based on emotion
        prompt = f"For emotion '{emotion}', what speech rate (50-250) and volume (0-100) should I use? Reply in format: RATE=X VOLUME=Y"
        messages = [{"role": "user", "content": prompt}]
        response = call_chat_once(runtime, messages, tools=None, max_tokens=50)
        
        content = response.get("content", "").upper()
        
        # Parse LLM response
        rate = 150
        volume = 100
        
        if "RATE=" in content:
            try:
                rate = int(content.split("RATE=")[1].split()[0])
                rate = max(50, min(250, rate))
            except:
                pass
        
        if "VOLUME=" in content:
            try:
                volume = int(content.split("VOLUME=")[1].split()[0])
                volume = max(0, min(100, volume))
            except:
                pass
        
        return speak(text, rate=rate, volume=volume, runtime=runtime)
    
    except Exception as e:
        # Fallback to default parameters
        return speak(text, rate=150, volume=100)


def voice_control(action: str, runtime: Optional[LLMRuntime] = None, **kwargs) -> Dict[str, Any]:
    """
    Main voice control dispatcher with LLM integration.
    Actions: speak, list_voices, speak_with_emotion
    """
    if action == "speak":
        text = kwargs.get("text", "")
        rate = kwargs.get("rate", 150)
        volume = kwargs.get("volume", 100)
        return speak(text, rate, volume, runtime)
    
    elif action == "list_voices":
        return list_voices()
    
    elif action == "speak_with_emotion":
        text = kwargs.get("text", "")
        emotion = kwargs.get("emotion", "neutral")
        return speak_with_emotion(text, emotion, runtime)
    
    else:
        return {"ok": False, "error": f"Unknown voice action: {action}"}


# ---------------------------------------------------------------------------
# Speech-to-Text — Groq Whisper (supports 97+ languages)
# ---------------------------------------------------------------------------

# Groq Whisper endpoint (OpenAI-compatible)
_GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_WHISPER_MODEL = "whisper-large-v3-turbo"

# Supported extensions for Whisper
_WHISPER_EXTENSIONS = {".ogg", ".oga", ".mp3", ".mp4", ".m4a", ".wav", ".webm", ".flac"}


def transcribe_audio(
    file_path: Path,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file to text using Groq Whisper.

    Args:
        file_path: Path to audio file (ogg, mp3, wav, m4a, webm, flac).
        language: Optional ISO-639-1 code (e.g. 'en', 'hi', 'es').
                  If omitted Whisper auto-detects the language.

    Returns:
        {"ok": True, "text": "...", "language": "..."} on success,
        {"ok": False, "error": "..."} on failure.
    """
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "error": "GROQ_API_KEY not set — cannot transcribe audio."}

    fp = Path(file_path)
    if not fp.exists() or not fp.is_file():
        return {"ok": False, "error": f"Audio file not found: {fp}"}

    if fp.suffix.lower() not in _WHISPER_EXTENSIONS:
        return {"ok": False, "error": f"Unsupported audio format: {fp.suffix}"}

    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        data: Dict[str, str] = {
            "model": _WHISPER_MODEL,
            "response_format": "verbose_json",
        }
        if language:
            data["language"] = language

        with fp.open("rb") as fh:
            files = {"file": (fp.name, fh, "audio/ogg")}
            resp = requests.post(
                _GROQ_WHISPER_URL,
                headers=headers,
                data=data,
                files=files,
                timeout=120,
            )

        if resp.status_code != 200:
            return {"ok": False, "error": f"Whisper API {resp.status_code}: {resp.text[:300]}"}

        result = resp.json()
        transcript = result.get("text", "").strip()
        detected_lang = result.get("language", "unknown")

        if not transcript:
            return {"ok": False, "error": "Whisper returned empty transcript."}

        return {"ok": True, "text": transcript, "language": detected_lang}

    except requests.Timeout:
        return {"ok": False, "error": "Whisper API timed out."}
    except Exception as exc:
        return {"ok": False, "error": f"Transcription failed: {exc}"}
