import base64
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv

from agent_runtime import AgentRuntime, new_session
from corn import CornRunner
from llm import build_runtime_from_env

WORKSPACE_ROOT = Path.cwd().resolve()
SARVAM_BASE_URL = "https://api.sarvam.ai"
VALID_TTS_SPEAKERS = {
    "anushka",
    "abhilash",
    "manisha",
    "vidya",
    "arya",
    "karun",
    "hitesh",
    "aditya",
    "ritu",
    "priya",
    "neha",
    "rahul",
    "pooja",
    "rohan",
    "simran",
    "kavya",
    "amit",
    "dev",
    "ishita",
    "shreya",
    "ratan",
    "varun",
    "manan",
    "sumit",
    "roopa",
    "kabir",
    "aayan",
    "shubh",
    "ashutosh",
    "advait",
    "amelia",
    "sophia",
    "anand",
    "tanya",
    "tarun",
    "sunny",
    "mani",
    "gokul",
    "vijay",
    "shruti",
    "suhani",
    "mohit",
    "kavitha",
    "rehan",
    "soham",
    "rupali",
}
SPEAKER_ALIASES = {
    "preiya": "priya",
}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _sarvam_headers(api_key: str) -> Dict[str, str]:
    return {"api-subscription-key": api_key}


def _extract_audio_b64(tts_payload: Dict[str, Any]) -> str:
    audios = tts_payload.get("audios")
    if isinstance(audios, list) and audios and isinstance(audios[0], str):
        return audios[0]
    audio = tts_payload.get("audio")
    if isinstance(audio, str):
        return audio
    raise RuntimeError("Sarvam TTS response missing audio payload")


def _sarvam_stt(api_key: str, audio_bytes: bytes, mime: str) -> Dict[str, Any]:
    model = os.getenv("SARVAM_STT_MODEL", "saaras:v3").strip() or "saaras:v3"
    mode = os.getenv("SARVAM_STT_MODE", "transcribe").strip() or "transcribe"
    url = f"{SARVAM_BASE_URL}/speech-to-text"
    files = {"file": ("speech.webm", audio_bytes, mime or "audio/webm")}
    data = {"model": model, "mode": mode}
    res = requests.post(url, headers=_sarvam_headers(api_key), files=files, data=data, timeout=120)
    res.raise_for_status()
    out = res.json()
    if not isinstance(out, dict):
        raise RuntimeError("Sarvam STT returned invalid JSON")
    return out


def _sarvam_tts(api_key: str, text: str, lang_code: str) -> Dict[str, Any]:
    model = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3").strip() or "bulbul:v3"
    raw_speaker = (os.getenv("SARVAM_TTS_SPEAKER", "priya").strip() or "priya").lower()
    speaker = SPEAKER_ALIASES.get(raw_speaker, raw_speaker)
    if speaker not in VALID_TTS_SPEAKERS:
        speaker = "priya"
    sample_rate = int(os.getenv("SARVAM_TTS_SAMPLE_RATE", "24000"))
    pace = float(os.getenv("SARVAM_TTS_PACE", "1.0"))
    url = f"{SARVAM_BASE_URL}/text-to-speech"
    payload = {
        "text": text[:2500],
        "target_language_code": lang_code,
        "model": model,
        "speaker": speaker,
        "sample_rate": sample_rate,
        "pace": pace,
    }
    res = requests.post(url, headers={**_sarvam_headers(api_key), "Content-Type": "application/json"}, json=payload, timeout=120)
    res.raise_for_status()
    out = res.json()
    if not isinstance(out, dict):
        raise RuntimeError("Sarvam TTS returned invalid JSON")
    return out


def _html_page() -> str:
    return """<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>ANKITA Voice Gateway</title>
  <style>
    body{font-family:Segoe UI,Arial,sans-serif;max-width:760px;margin:24px auto;padding:0 16px}
    .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
    button{padding:12px 18px;border-radius:10px;border:1px solid #999;cursor:pointer}
    #talk{font-size:16px;background:#0d6efd;color:#fff;border:none}
    #talk.recording{background:#c62828}
    #log{white-space:pre-wrap;border:1px solid #ddd;border-radius:10px;padding:10px;min-height:220px}
    input,select{padding:8px}
  </style>
</head>
<body>
  <h2>ANKITA Voice (Sarvam STT/TTS)</h2>
  <div class="row">
    <label>Session</label><input id="session" value="">
    <label>Lang</label><select id="lang">
      <option value="en-IN">en-IN</option><option value="hi-IN">hi-IN</option>
      <option value="bn-IN">bn-IN</option><option value="ta-IN">ta-IN</option>
      <option value="te-IN">te-IN</option><option value="mr-IN">mr-IN</option>
      <option value="gu-IN">gu-IN</option><option value="kn-IN">kn-IN</option>
      <option value="ml-IN">ml-IN</option><option value="pa-IN">pa-IN</option>
      <option value="od-IN">od-IN</option>
    </select>
    <button id="talk">Hold to Talk</button>
    <button id="stop">Stop Audio</button>
  </div>
  <p>Press and hold Talk, release to send.</p>
  <audio id="player" controls></audio>
  <h3>Transcript</h3>
  <div id="log"></div>
  <script>
    const talk=document.getElementById('talk');
    const stop=document.getElementById('stop');
    const log=document.getElementById('log');
    const player=document.getElementById('player');
    const lang=document.getElementById('lang');
    const session=document.getElementById('session');
    if(!session.value){session.value=(crypto.randomUUID?crypto.randomUUID():String(Date.now()));}
    let mediaRecorder=null; let chunks=[]; let stream=null; let busy=false;
    function add(msg){ log.textContent += msg + "\\n\\n"; log.scrollTop = log.scrollHeight; }
    async function ensureMic(){
      if(stream) return stream;
      stream = await navigator.mediaDevices.getUserMedia({audio:true});
      return stream;
    }
    async function startRec(){
      if(busy) return;
      try{
        await ensureMic();
        chunks=[];
        mediaRecorder=new MediaRecorder(stream,{mimeType:'audio/webm'});
        mediaRecorder.ondataavailable=e=>{ if(e.data && e.data.size>0) chunks.push(e.data); };
        mediaRecorder.start();
        talk.classList.add('recording');
      }catch(e){ add('Mic error: '+e); }
    }
    async function stopRec(){
      if(!mediaRecorder) return;
      busy=true;
      await new Promise(resolve=>{ mediaRecorder.onstop=resolve; mediaRecorder.stop(); });
      talk.classList.remove('recording');
      const blob=new Blob(chunks,{type:'audio/webm'});
      if(blob.size<800){ busy=false; return; }
      const url='/api/voice-turn?lang='+encodeURIComponent(lang.value)+'&session='+encodeURIComponent(session.value);
      const r=await fetch(url,{method:'POST',headers:{'Content-Type':'audio/webm'},body:blob});
      const t=await r.text();
      if(!r.ok){ add('Error '+r.status+': '+t); busy=false; return; }
      const out=JSON.parse(t);
      add('You: '+(out.transcript||'')+'\\nAnkita: '+(out.reply_text||''));
      if(out.audio_b64){
        player.src='data:audio/wav;base64,'+out.audio_b64;
        player.play().catch(()=>{});
      }
      busy=false;
    }
    function pressStart(e){ e.preventDefault(); startRec(); }
    function pressEnd(e){ e.preventDefault(); stopRec(); }
    talk.addEventListener('mousedown',pressStart);
    talk.addEventListener('mouseup',pressEnd);
    talk.addEventListener('mouseleave',()=>{ if(talk.classList.contains('recording')) stopRec(); });
    talk.addEventListener('touchstart',pressStart,{passive:false});
    talk.addEventListener('touchend',pressEnd,{passive:false});
    stop.addEventListener('click',()=>{ player.pause(); player.currentTime=0; });
  </script>
</body>
</html>
"""


def main() -> None:
    load_dotenv()
    api_key = os.getenv("SARVAM_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Error: SARVAM_API_KEY is not set.")

    runtime = build_runtime_from_env()
    agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)
    sessions: Dict[str, List[Dict[str, Any]]] = {}
    sessions_lock = threading.Lock()

    runner: CornRunner | None = None
    if _env_bool("CORN_AUTO_RUN", True):
        runner = CornRunner(
            workspace_root=WORKSPACE_ROOT,
            poll_interval_sec=float(os.getenv("CORN_POLL_INTERVAL_SEC", "5")),
            max_jobs_per_tick=int(os.getenv("CORN_MAX_JOBS_PER_TICK", "5")),
        )
        runner.start()

    class Handler(BaseHTTPRequestHandler):
        def address_string(self) -> str:
            # Avoid reverse-DNS lookups that can block local responses on some Windows setups.
            return self.client_address[0]

        def log_message(self, format: str, *args: object) -> None:
            # Silence per-request logging to keep the handler non-blocking.
            return

        def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, code: int, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/voice"}:
                self._send_html(200, _html_page())
                return
            self._send_json(404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/voice-turn":
                self._send_json(404, {"ok": False, "error": "not_found"})
                return

            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = 0
            if n <= 0 or n > 20 * 1024 * 1024:
                self._send_json(400, {"ok": False, "error": "invalid_audio_size"})
                return

            mime = (self.headers.get("Content-Type", "audio/webm") or "audio/webm").split(";")[0].strip()
            audio = self.rfile.read(n)
            qs = parse_qs(parsed.query)
            session_id = (qs.get("session", [""])[0] or "").strip() or str(uuid.uuid4())
            tts_lang = (qs.get("lang", ["en-IN"])[0] or "en-IN").strip()

            try:
                stt = _sarvam_stt(api_key=api_key, audio_bytes=audio, mime=mime)
                transcript = str(stt.get("transcript", "")).strip()
                detected_lang = str(stt.get("language_code", "")).strip() or tts_lang
                if not transcript:
                    self._send_json(200, {"ok": True, "transcript": "", "reply_text": "I could not hear that clearly.", "audio_b64": ""})
                    return

                with sessions_lock:
                    if session_id not in sessions:
                        sessions[session_id] = new_session()
                    msgs = sessions[session_id]
                reply_text = agent.process_user_text(user_text=transcript, messages=msgs)

                tts = _sarvam_tts(api_key=api_key, text=reply_text, lang_code=detected_lang if "-" in detected_lang else tts_lang)
                audio_b64 = _extract_audio_b64(tts)
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "session": session_id,
                        "transcript": transcript,
                        "reply_text": reply_text,
                        "audio_b64": audio_b64,
                    },
                )
            except requests.HTTPError as err:
                status = err.response.status_code if err.response is not None else 500
                body = err.response.text[:800] if err.response is not None else str(err)
                self._send_json(status, {"ok": False, "error": "upstream_http_error", "detail": body})
            except Exception as err:
                self._send_json(500, {"ok": False, "error": str(err)})

    host = os.getenv("VOICE_WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("VOICE_WEB_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)

    print("ANKITA Voice Gateway started")
    print(f"Provider: {runtime.provider}")
    print(f"Model: {runtime.model}")
    print(f"Workspace: {WORKSPACE_ROOT}")
    print(f"URL: http://{host}:{port}")
    print(f"Corn scheduler: {'ON' if runner is not None else 'OFF'}")

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping voice gateway.")
    finally:
        server.server_close()
        if runner is not None:
            runner.stop()


if __name__ == "__main__":
    main()
