import os
import time
from typing import Any, Dict, Optional

import requests


_ASSEMBLYAI_BASE = "https://api.assemblyai.com/v2"


def _get_key() -> Optional[str]:
    k = os.getenv("ASSEMBLYAI_API_KEY")
    if k:
        k = k.strip()
    return k or None


def upload_audio(file_path: str, api_key: Optional[str] = None) -> str:
    key = api_key or _get_key()
    if not key:
        raise RuntimeError("ASSEMBLYAI_API_KEY is not set")

    url = f"{_ASSEMBLYAI_BASE}/upload"
    headers = {"authorization": key}
    with open(file_path, "rb") as f:
        r = requests.post(url, headers=headers, data=f, timeout=120)
    r.raise_for_status()
    data = r.json()
    upload_url = data.get("upload_url")
    if not upload_url:
        raise RuntimeError("AssemblyAI upload failed: missing upload_url")
    return upload_url


def request_transcription(
    audio_url: str,
    api_key: Optional[str] = None,
    speaker_labels: bool = True,
    auto_chapters: bool = True,
    entity_detection: bool = True,
) -> str:
    key = api_key or _get_key()
    if not key:
        raise RuntimeError("ASSEMBLYAI_API_KEY is not set")

    url = f"{_ASSEMBLYAI_BASE}/transcript"
    headers = {"authorization": key, "content-type": "application/json"}
    payload: Dict[str, Any] = {
        "audio_url": audio_url,
        "speaker_labels": speaker_labels,
        "auto_chapters": auto_chapters,
        "entity_detection": entity_detection,
    }
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    tid = data.get("id")
    if not tid:
        raise RuntimeError("AssemblyAI transcript request failed: missing id")
    return tid


def get_transcription(transcript_id: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    key = api_key or _get_key()
    if not key:
        raise RuntimeError("ASSEMBLYAI_API_KEY is not set")

    url = f"{_ASSEMBLYAI_BASE}/transcript/{transcript_id}"
    headers = {"authorization": key}
    r = requests.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()


def poll_transcription(
    transcript_id: str,
    api_key: Optional[str] = None,
    timeout_s: float = 120.0,
    interval_s: float = 2.0,
) -> Dict[str, Any]:
    start = time.time()
    while True:
        data = get_transcription(transcript_id, api_key=api_key)
        status = (data.get("status") or "").lower()
        if status in ("completed", "error"):
            return data
        if time.time() - start > timeout_s:
            raise TimeoutError("AssemblyAI transcription timed out")
        time.sleep(interval_s)
