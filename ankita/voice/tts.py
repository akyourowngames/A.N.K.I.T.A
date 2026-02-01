import asyncio
import edge_tts
import os
import tempfile
import subprocess
import random

# Natural, expressive voices (female, Indian English)
VOICES = [
    "en-IN-NeerjaNeural",      # Default - warm, friendly
    "en-IN-NeerjaExpressiveNeural",  # More expressive
]
DEFAULT_VOICE = "en-IN-NeerjaExpressiveNeural"

# Prosody settings for natural speech
RATE = "+5%"      # Slightly faster (more natural)
PITCH = "+0Hz"    # Natural pitch


def _add_natural_pauses(text: str) -> str:
    """Add natural pauses and emphasis using SSML-like markers."""
    # Add slight pauses after punctuation
    text = text.replace(". ", "... ")
    text = text.replace("! ", "!... ")
    text = text.replace("? ", "?... ")
    text = text.replace(", ", ", ")
    return text


async def _speak_async(text: str, path: str, voice: str = None):
    """Generate speech with natural prosody."""
    voice = voice or DEFAULT_VOICE
    
    # Make text more natural
    text = _add_natural_pauses(text)
    
    communicate = edge_tts.Communicate(
        text,
        voice=voice,
        rate=RATE,
        pitch=PITCH
    )
    await communicate.save(path)


def speak(text: str, voice: str = None):
    """Generate speech and play it directly (no window, no popup)."""
    temp_dir = tempfile.gettempdir()
    mp3_file = os.path.join(temp_dir, "ankita_speech.mp3")
    
    # Generate audio with natural prosody
    asyncio.run(_speak_async(text, mp3_file, voice))
    
    # Play using Windows Media Player COM object (silent, no window)
    ps_cmd = f'''
    Add-Type -AssemblyName presentationCore
    $player = New-Object System.Windows.Media.MediaPlayer
    $player.Open([Uri]"{mp3_file}")
    Start-Sleep -Milliseconds 300
    $player.Play()
    while ($player.NaturalDuration.HasTimeSpan -eq $false) {{ Start-Sleep -Milliseconds 50 }}
    $duration = $player.NaturalDuration.TimeSpan.TotalMilliseconds
    Start-Sleep -Milliseconds $duration
    $player.Close()
    '''
    subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True)


def speak_emotion(text: str, emotion: str = "friendly"):
    """Speak with a specific emotion/style."""
    # Adjust prosody based on emotion
    emotions = {
        "friendly": ("+5%", "+2Hz"),
        "excited": ("+15%", "+5Hz"),
        "calm": ("-5%", "-2Hz"),
        "serious": ("+0%", "-3Hz"),
    }
    
    global RATE, PITCH
    old_rate, old_pitch = RATE, PITCH
    RATE, PITCH = emotions.get(emotion, ("+5%", "+0Hz"))
    
    speak(text)
    
    RATE, PITCH = old_rate, old_pitch


