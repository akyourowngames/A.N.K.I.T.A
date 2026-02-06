"""
Setup Vosk Model - Downloads the recommended Vosk model for passive listening.

Run this script once to download the model.
"""

import os
import sys
import zipfile
import urllib.request
from pathlib import Path

# Vosk model URLs
MODELS = {
    "small-en-us": {
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "folder": "vosk-model-small-en-us-0.15",
        "size_mb": 40,
        "desc": "Small, fast, lower accuracy"
    },
    "en-us": {
        "url": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip",
        "folder": "vosk-model-en-us-0.22",
        "size_mb": 1800,
        "desc": "Large US English, best accuracy"
    },
    "en-in": {
        "url": "https://alphacephei.com/vosk/models/vosk-model-en-in-0.5.zip", 
        "folder": "vosk-model-en-in-0.5",
        "size_mb": 1000,
        "desc": "Indian English, good for Indian accent"
    }
}

def download_model(model_key: str = "small-en-us", target_dir: str = None):
    """Download and extract Vosk model."""
    
    if model_key not in MODELS:
        print(f"Unknown model: {model_key}")
        print(f"Available: {list(MODELS.keys())}")
        return False
    
    model_info = MODELS[model_key]
    
    if target_dir is None:
        target_dir = Path(__file__).parent.parent
    else:
        target_dir = Path(target_dir)
    
    target_dir.mkdir(parents=True, exist_ok=True)
    
    model_path = target_dir / model_info["folder"]
    if model_path.exists():
        print(f"✅ Model already exists: {model_path}")
        return True
    
    zip_path = target_dir / f"{model_info['folder']}.zip"
    
    print(f"Downloading Vosk model: {model_key}")
    print(f"Size: ~{model_info['size_mb']} MB")
    print(f"URL: {model_info['url']}")
    print()
    
    try:
        # Download with progress
        def show_progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            percent = min(100, (downloaded * 100) // total_size)
            bar_len = 40
            filled = int(bar_len * percent / 100)
            bar = "█" * filled + "░" * (bar_len - filled)
            sys.stdout.write(f"\r[{bar}] {percent}% ({downloaded // (1024*1024)} MB)")
            sys.stdout.flush()
        
        urllib.request.urlretrieve(
            model_info["url"],
            str(zip_path),
            reporthook=show_progress
        )
        print()
        
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return False
    
    print("Extracting...")
    try:
        with zipfile.ZipFile(str(zip_path), 'r') as zf:
            zf.extractall(str(target_dir))
        
        # Clean up zip
        zip_path.unlink()
        
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        return False
    
    print(f"✅ Model installed: {model_path}")
    
    # Set environment variable hint
    print()
    print("To use this model, set the environment variable:")
    print(f"  VOSK_MODEL_PATH={model_path}")
    print()
    print("Or the model will be auto-detected from the project directory.")
    
    return True


def main():
    print("="*60)
    print("VOSK MODEL SETUP")
    print("="*60)
    print()
    print("This script will download the Vosk speech recognition model")
    print("for passive listening (zero hallucination).")
    print()
    
    print("Available models:")
    for key, info in MODELS.items():
        print(f"  {key}: ~{info['size_mb']} MB")
    print()
    
    # Default to small model
    model = "small-en-us"
    
    print(f"Downloading: {model}")
    print()
    
    success = download_model(model)
    
    if success:
        print()
        print("🎉 Setup complete! You can now run the hybrid STT test:")
        print("  python tests/test_hybrid_stt.py")
    else:
        print()
        print("❌ Setup failed. You can manually download from:")
        print("  https://alphacephei.com/vosk/models")


if __name__ == "__main__":
    main()
