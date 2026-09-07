import asyncio
import logging
import os
import time
from pathlib import Path

import aiohttp

from server import channel_store

log = logging.getLogger("zumba.telegram")
CHANNEL = "telegram"
TG_LIMIT = 4096

_stt_model = None
_stt_lock = asyncio.Lock()


def get_token() -> str:
    return (os.getenv("ZUMBA_TG_BOT_TOKEN") or "").strip()


def get_allowed_chats() -> set[int]:
    raw = os.getenv("ZUMBA_TG_ALLOWED_CHAT_IDS", "")
    out: set[int] = set()
    for p in raw.replace(";", ",").split(","):
        p = p.strip()
        if p.lstrip("-").isdigit():
            out.add(int(p))
    return out


def voice_reply_enabled() -> bool:
    return (os.getenv("ZUMBA_TG_VOICE_REPLY", "1") or "1").strip() not in ("0", "false", "no", "off")


def voice_max_sec() -> int:
    try:
        return max(10, int(os.getenv("ZUMBA_TG_VOICE_MAX_SEC", "300") or "300"))
    except Exception:
        return 300


def split_message(text: str, limit: int = TG_LIMIT) -> list[str]:
    t = text or ""
    if len(t) <= limit:
        return [t] if t else [""]
    chunks: list[str] = []
    while len(t) > limit:
        cut = t.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = t.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(t[:cut].rstrip())
        t = t[cut:].lstrip()
    if t:
        chunks.append(t)
    return chunks


class TelegramAPI:
    def __init__(self, token: str, session: aiohttp.ClientSession | None = None):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"
        self._own = session is None
        self._session = session

    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=75))
            self._own = True
        return self._session

    async def close(self):
        if self._own and self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None

    async def _post(self, method: str, payload: dict, timeout: int = 70) -> dict:
        s = await self._sess()
        try:
            async with s.post(f"{self.base}/{method}", json=payload,
                              timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                data = await r.json(content_type=None)
                if r.status in (429, 500, 502, 503, 504):
                    retry = 0
                    try:
                        retry = int((data.get("parameters") or {}).get("retry_after", 0) or 0)
                    except Exception:
                        retry = 0
                    err = RuntimeError(f"tg_retry:{r.status}:{retry}")
                    err.retry_after = retry  # type: ignore
                    raise err
                return data
        except aiohttp.ClientError as e:
            err = RuntimeError(f"tg_net:{e}")
            err.retry_after = 0  # type: ignore
            raise err

    async def get_updates(self, offset: int, timeout: int = 30) -> list[dict]:
        data = await self._post("getUpdates", {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]}, timeout=timeout + 15)
        if not data.get("ok"):
            raise RuntimeError(f"getUpdates failed: {str(data)[:200]}")
        return data.get("result") or []

    async def send_message(self, chat_id: int, text: str) -> None:
        for chunk in split_message(text):
            await self._post("sendMessage", {"chat_id": chat_id, "text": chunk or "(empty)"}, timeout=30)

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        try:
            await self._post("sendChatAction", {"chat_id": chat_id, "action": action}, timeout=15)
        except Exception:
            pass

    async def get_file_path(self, file_id: str) -> str:
        data = await self._post("getFile", {"file_id": file_id}, timeout=30)
        if not data.get("ok"):
            raise RuntimeError(f"getFile failed: {str(data)[:200]}")
        return str((data.get("result") or {}).get("file_path", ""))

    async def download_file(self, file_path: str, dest: Path) -> Path:
        s = await self._sess()
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=120)) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in r.content.iter_chunked(64 * 1024):
                    f.write(chunk)
        return dest

    async def send_voice(self, chat_id: int, mp3: bytes, caption: str = "") -> None:
        s = await self._sess()
        form = aiohttp.FormData()
        form.add_field("chat_id", str(chat_id))
        form.add_field("voice", mp3, filename="reply.mp3", content_type="audio/mpeg")
        if caption:
            form.add_field("caption", caption[:1024])
        async with s.post(f"{self.base}/sendVoice", data=form,
                          timeout=aiohttp.ClientTimeout(total=60)) as r:
            await r.read()


async def _transcribe_ogg(path: Path) -> str:
    global _stt_model
    async with _stt_lock:
        if _stt_model is None:
            from faster_whisper import WhisperModel
            _stt_model = await asyncio.to_thread(WhisperModel, "small", device="cpu", compute_type="int8")
    def _run():
        segs, _ = _stt_model.transcribe(str(path), task="translate", beam_size=1)
        return "".join(s.text for s in segs).strip()
    return await asyncio.to_thread(_run)


class _Bucket:
    def __init__(self, rate: float = 1.0, burst: int = 5):
        self.rate = rate
        self.burst = burst
        self._state: dict[int, tuple[float, float]] = {}

    def allow(self, chat_id: int) -> bool:
        now = time.time()
        tokens, ts = self._state.get(chat_id, (float(self.burst), now))
        tokens = min(float(self.burst), tokens + (now - ts) * self.rate)
        if tokens < 1.0:
            self._state[chat_id] = (tokens, now)
            return False
        self._state[chat_id] = (tokens - 1.0, now)
        return True


_limiter = _Bucket()


class TelegramChannel:
    def __init__(self, api: TelegramAPI | None = None):
        self.api = api or TelegramAPI(get_token())
        self._stop = asyncio.Event()

    def stop(self):
        self._stop.set()

    async def run(self):
        offset = channel_store.get_next_offset(CHANNEL)
        backoff = 1.0
        log.info("telegram channel started (offset=%s)", offset)
        while not self._stop.is_set():
            try:
                updates = await self.api.get_updates(offset, timeout=30)
                backoff = 1.0
                for u in updates:
                    uid = int(u.get("update_id", 0) or 0)
                    offset = max(offset, uid + 1)
                    channel_store.set_next_offset(CHANNEL, offset)
                    if not channel_store.claim_update(CHANNEL, uid):
                        log.info("skipping duplicate update %s", uid)
                        continue
                    try:
                        await self.handle_update(u)
                    except Exception as e:
                        log.exception("handle_update failed: %s", e)
            except Exception as e:
                retry = getattr(e, "retry_after", 0) or 0
                wait = max(float(retry or 0), min(backoff, 30.0))
                log.warning("poll error %s; sleeping %.1fs", e, wait)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 30.0)
        try:
            await self.api.close()
        except Exception:
            pass

    async def handle_update(self, update: dict) -> None:
        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = int(chat.get("id", 0) or 0)
        if not chat_id:
            return
        allowed = get_allowed_chats()
        if chat_id not in allowed:
            try:
                await self.api.send_message(chat_id, f"Not authorized. This chat id is {chat_id}. Ask the owner to add it to ZUMBA_TG_ALLOWED_CHAT_IDS.")
            except Exception:
                pass
            log.warning("rejected tg chat %s", chat_id)
            return
        if not _limiter.allow(chat_id):
            await self.api.send_message(chat_id, "Slow down — one message at a time please.")
            return
        text = (msg.get("text") or "").strip()
        voice = msg.get("voice") or msg.get("audio")
        if text.startswith("/new"):
            channel_store.set_session_for_chat(CHANNEL, str(chat_id), f"tg-{chat_id}-{int(time.time())}")
            await self.api.send_message(chat_id, "Fresh session started.")
            return
        if text.startswith("/help"):
            await self.api.send_message(chat_id, "Send text or a voice note. Commands: /new (fresh session), /help, /memory <query>.")
            return
        if text.startswith("/memory"):
            q = text[7:].strip() or "recent conversation"
            try:
                from memory import get_memory
                hits = await asyncio.to_thread(get_memory().recall, q, 8, 2000)
                await self.api.send_message(chat_id, str(hits)[:3500] or "(nothing recalled)")
            except Exception as e:
                await self.api.send_message(chat_id, f"memory error: {e}"[:500])
            return
        is_voice = voice is not None
        if is_voice:
            dur = int(voice.get("duration", 0) or 0)
            if dur > voice_max_sec():
                await self.api.send_message(chat_id, f"Voice note too long ({dur}s > {voice_max_sec()}s). Send a shorter one.")
                return
            text = await self._handle_voice(chat_id, msg, voice)
            if not text:
                return
        if not text:
            return
        await self.api.send_chat_action(chat_id, "typing")
        sid = channel_store.resolve_session(CHANNEL, str(chat_id))
        nudge = asyncio.create_task(self._nudge(chat_id))
        try:
            from core.chat_pipeline import aanswer
            reply = await aanswer(sid, text)
        except Exception as e:
            reply = f"Zumba error: {e}"[:1000]
        finally:
            nudge.cancel()
        if not reply.strip():
            reply = "(empty response)"
        await self.api.send_message(chat_id, reply)
        if is_voice and voice_reply_enabled():
            await self._maybe_voice_reply(chat_id, reply)

    async def _nudge(self, chat_id: int, delay: float = 10.0):
        try:
            await asyncio.sleep(delay)
            await self.api.send_message(chat_id, "Still working…")
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _handle_voice(self, chat_id: int, msg: dict, voice: dict) -> str:
        await self.api.send_chat_action(chat_id, "typing")
        try:
            file_id = str(voice.get("file_id", ""))
            remote = await self.api.get_file_path(file_id)
            dest = Path.home() / ".zumba" / "tg_audio" / f"{msg.get('message_id', int(time.time()))}.ogg"
            await self.api.download_file(remote, dest)
            transcript = await _transcribe_ogg(dest)
            if not transcript:
                await self.api.send_message(chat_id, "Couldn't hear anything in that voice note — try again.")
                return ""
            return transcript
        except Exception as e:
            await self.api.send_message(chat_id, f"Voice transcription failed: {e}"[:500])
            return ""

    async def _maybe_voice_reply(self, chat_id: int, reply: str):
        try:
            await self.api.send_chat_action(chat_id, "record_voice")
            from server.tts import synthesize_mp3
            mp3, _v, short = await synthesize_mp3(reply)
            await self.api.send_voice(chat_id, mp3, caption=short[:200])
        except Exception as e:
            log.warning("voice reply failed: %s", e)


_channel_task: asyncio.Task | None = None


def start_if_configured(app=None) -> asyncio.Task | None:
    global _channel_task
    if not get_token():
        return None
    if _channel_task is not None and not _channel_task.done():
        return _channel_task
    async def _runner():
        ch = TelegramChannel()
        try:
            await ch.run()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.exception("telegram channel crashed: %s", e)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    _channel_task = loop.create_task(_runner())
    return _channel_task
