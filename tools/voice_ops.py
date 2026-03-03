"""
Voice operations for ANKITA - Text-to-Speech with LLM-enhanced natural speech.
"""
import subprocess
from typing import Dict, Any, List, Optional
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
