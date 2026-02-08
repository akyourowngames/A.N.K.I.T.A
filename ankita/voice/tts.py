import asyncio
import edge_tts
import os
import tempfile
import subprocess
import random
import time

# Global variable to track current player process for barge-in
_current_player = None

# Natural, expressive voices
VOICES = {
    "en": "en-IN-NeerjaExpressiveNeural",
    "hi": "hi-IN-SwaraNeural",
}
DEFAULT_VOICE_EN = "en-IN-NeerjaExpressiveNeural"
DEFAULT_VOICE_HI = "hi-IN-SwaraNeural"

# Prosody settings for natural speech
RATE = "+5%"      # Slightly faster (more natural)
PITCH = "+0Hz"    # Natural pitch


def _detect_language(text: str) -> str:
    """Detect if the text is primarily Hindi or English."""
    # Check for Devanagari script (Hindi)
    if any("\u0900" <= char <= "\u097f" for char in text):
        return "hi"
    
    # Common Hindi words written in Roman script
    hindi_roman_keywords = ["hai", "hai", "karo", "kijiye", "shukriya", "dhanyawad", "namaste", "kaise"]
    text_lower = text.lower()
    if any(word in text_lower for word in hindi_roman_keywords):
        # This is a bit naive but works for mixed Roman script
        # However, it might misidentify English. 
        # For now, we prioritize Devanagari detection.
        pass

    return "en"


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
    if not voice:
        lang = _detect_language(text)
        voice = VOICES.get(lang, DEFAULT_VOICE_EN)
    
    # Make text more natural
    text = _add_natural_pauses(text)
    
    communicate = edge_tts.Communicate(
        text,
        voice=voice,
        rate=RATE,
        pitch=PITCH
    )
    await communicate.save(path)


def stop_speaking():
    """Stop the current TTS playback (Barge-in)."""
    global _current_player
    if _current_player:
        try:
            print("[TTS] Interruption detected. Stopping speech.")
            _current_player.terminate()
            # Also kill any powershell processes started by the tts
            subprocess.run(["taskkill", "/F", "/IM", "powershell.exe", "/T"], capture_output=True)
            _current_player = None
        except Exception as e:
            print(f"[TTS] Error stopping speech: {e}")


def speak(text: str, voice: str = None):
    """Generate speech and play it directly (no window, no popup)."""
    global _current_player
    
    # Ensure any previous speech is stopped
    stop_speaking()
    
    temp_dir = tempfile.gettempdir()
    # Use unique filename to avoid file lock issues
    unique_id = int(time.time() * 1000)
    mp3_file = os.path.join(temp_dir, f"ankita_speech_{unique_id}.mp3")
    
    # Generate audio with natural prosody
    # Fix for asyncio.run() in running event loop
    try:
        loop = asyncio.get_running_loop()
        # We're in an async context, use create_task
        import threading
        def run_in_thread():
            asyncio.run(_speak_async(text, mp3_file, voice))
        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join()  # Wait for completion
    except RuntimeError:
        # No running loop, safe to use asyncio.run()
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
    
    _current_player = subprocess.Popen(["powershell", "-Command", ps_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Wait for the process to finish if not interrupted
    try:
        _current_player.wait(timeout=30)
    except subprocess.TimeoutExpired:
        _current_player.terminate()
    finally:
        _current_player = None
        
    # Cleanup temp file
    try:
        if os.path.exists(mp3_file):
            os.remove(mp3_file)
    except:
        pass  # Ignore cleanup errors


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


