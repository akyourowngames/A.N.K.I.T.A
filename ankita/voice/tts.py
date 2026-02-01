import asyncio
import edge_tts
import os
import tempfile
import subprocess

VOICE = "en-IN-NeerjaNeural"

async def _speak(text, path):
    communicate = edge_tts.Communicate(text, voice=VOICE)
    await communicate.save(path)

def speak(text):
    """Generate speech and play it directly (no window, no popup)."""
    temp_dir = tempfile.gettempdir()
    mp3_file = os.path.join(temp_dir, "ankita_speech.mp3")
    
    # Generate audio
    asyncio.run(_speak(text, mp3_file))
    
    # Play using Windows Media Player COM object (silent, no window)
    ps_cmd = f'''
    Add-Type -AssemblyName presentationCore
    $player = New-Object System.Windows.Media.MediaPlayer
    $player.Open([Uri]"{mp3_file}")
    Start-Sleep -Milliseconds 500
    $player.Play()
    while ($player.NaturalDuration.HasTimeSpan -eq $false) {{ Start-Sleep -Milliseconds 100 }}
    $duration = $player.NaturalDuration.TimeSpan.TotalMilliseconds
    Start-Sleep -Milliseconds $duration
    $player.Close()
    '''
    subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True)


