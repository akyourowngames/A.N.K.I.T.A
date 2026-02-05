import os
import time

# Reduce optional dependency scanning during transformers import (helps on Windows)
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("TRANSFORMERS_NO_FLAX", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_t0 = time.time()
print("Importing torch/soundfile...")
import torch
import soundfile as sf

print("Importing qwen_tts (this may be slow the first time on Windows)...")
from qwen_tts import Qwen3TTSModel
print(f"Imports done in {time.time() - _t0:.1f}s")

# 1. Force CPU usage
device = "cpu"

# 2. Use the 0.6B model for much faster CPU performance
# This version is optimized for machines without a GPU
print("Loading model (first run may download weights)...")
_t1 = time.time()
model = Qwen3TTSModel.from_pretrained(
    "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice", 
    device_map=device,
    dtype=torch.float32 # Use float32 for CPU compatibility
)
print(f"Model loaded in {time.time() - _t1:.1f}s")

# 3. Generate speech
print("Generating audio on CPU (this may take a moment)...")
_t2 = time.time()
wavs, sr = model.generate_custom_voice(
    text="Hello! I am running Qwen TTS on my CPU without a graphics card.",
    language="English",
    speaker="Vivian"
)
print(f"Generation done in {time.time() - _t2:.1f}s")

# 4. Save to file
# We use wavs[0] to get the actual audio data from the generation list
sf.write("qwen_cpu_output.wav", wavs[0], sr)
print("Done! Check qwen_cpu_output.wav in your folder.")
