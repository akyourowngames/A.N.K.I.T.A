import asyncio
import logging
import os
import time
from pathlib import Path

import aiohttp

from server import channel_store
from core import run_store
from server.telegram_execution import TelegramExecution, actor_id

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
                if not data.get('ok'):
                    if method == 'editMessageText' and 'message is not modified' in str(data.get('description', '')):
                        return data
                    raise RuntimeError(f"Telegram {method} rejected: {data.get('error_code', r.status)} {str(data.get('description', ''))[:180]}")
                return data
        except aiohttp.ClientError as e:
            err = RuntimeError(f"tg_net:{type(e).__name__}")
            err.retry_after = 0  # type: ignore
            raise err

    async def get_updates(self, offset: int, timeout: int = 30) -> list[dict]:
        data = await self._post("getUpdates", {"offset": offset, "timeout": timeout, "allowed_updates": ["message", "edited_message", "callback_query"]}, timeout=timeout + 15)
        if not data.get("ok"):
            raise RuntimeError(f"getUpdates failed: {str(data)[:200]}")
        return data.get("result") or []

    async def send_message(self, chat_id: int, text: str, reply_markup=None) -> int | None:
        first_id = None
        for chunk in split_message(text):
            payload = {"chat_id": chat_id, "text": chunk or "(empty)"}
            if reply_markup is not None:
                payload['reply_markup'] = reply_markup
            data = await self._post("sendMessage", payload, timeout=30)
            first_id = first_id or (data.get('result') or {}).get('message_id')
        return first_id

    async def edit_message(self, chat_id, message_id, text, reply_markup=None):
        payload = {'chat_id': chat_id, 'message_id': message_id, 'text': text[:TG_LIMIT]}
        if reply_markup is not None:
            payload['reply_markup'] = reply_markup
        return await self._post('editMessageText', payload, timeout=15)

    async def answer_callback(self, query_id, text):
        return await self._post('answerCallbackQuery', {'callback_query_id': query_id, 'text': text[:200]}, timeout=10)

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
            data = await r.json(content_type=None)
            if not data.get('ok'):
                raise RuntimeError(f"Telegram sendVoice rejected: {data.get('error_code', r.status)}")


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


_CAL_PENDING: dict[int, float] = {}
_CAL_PENDING_TTL = 10 * 60.0


def _cal_prune_pending(now: float = 0) -> None:
    """Drop expired OAuth-wait entries (no leak, m7)."""
    try:
        ts = now or time.time()
        for cid, at in list(_CAL_PENDING.items()):
            if ts - at > _CAL_PENDING_TTL:
                _CAL_PENDING.pop(cid, None)
    except Exception:
        pass


def _cal_looks_like_code(text: str) -> bool:
    """Strict Google authorization-code shape only ('4/...').

    Access tokens (ya29...) are deliberately rejected here — they must go
    through `/cal token`, never the code-exchange endpoint (M2: no exfil of
    arbitrary chat text to Google).
    """
    try:
        from tools.calendar import is_auth_code
        return is_auth_code(text)
    except Exception:
        t = (text or "").strip()
        return len(t) >= 20 and t.startswith("4/") and " " not in t


class TelegramChannel:
    def __init__(self, api: TelegramAPI | None = None):
        self.api = api or TelegramAPI(get_token())
        self._stop = asyncio.Event()
        self._limiter = _Bucket()
        self.execution = TelegramExecution(self.api)
        self._tasks = {}
        self._chat_locks = {}

    def stop(self):
        self._stop.set()
        for control in self.execution.active.values():
            control.cancel()

    async def drain(self):
        if self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    async def close(self):
        self.stop()
        pending = list(self._tasks.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=5)
        await self.api.close()

    @staticmethod
    def command(text):
        first = text.split(maxsplit=1)[0] if text else ''
        return first.split('@', 1)[0].lower() if first.startswith('/') else ''

    def _schedule(self, run):
        if run['id'] in self._tasks or run['status'] != 'queued':
            return
        async def work():
            lock = self._chat_locks.setdefault(run['chat_id'], asyncio.Lock())
            async with lock:
                if self._stop.is_set() or not run_store.claim(run['id']):
                    return
                if time.time() - run['created_at'] > 300:
                    run_store.finish(run['id'], 'interrupted', 'This request waited more than five minutes. It was not executed; send a fresh request if it is still relevant.')
                    return
                try:
                    await self.handle_update(run['payload'], run=run)
                    # Non-agent commands, locations and rejected input also settle.
                    if run_store.get(run['id'])['status'] == 'running':
                        run_store.finish(run['id'], 'completed', 'Handled without tool execution.')
                        run_store.delivered(run['id'])
                except asyncio.CancelledError:
                    run_store.finish(run['id'], 'interrupted', 'Execution interrupted; no action has been replayed.')
                    raise
                except Exception as exc:
                    run_store.finish(run['id'], 'failed', 'Task failed. Use /status.', error=type(exc).__name__ + ': ' + str(exc))
                    log.warning('Run %s failed (%s)', run['id'], type(exc).__name__)
        task = asyncio.create_task(work())
        self._tasks[run['id']] = task
        task.add_done_callback(lambda done: self._tasks.pop(run['id'], None))

    async def dispatch_update(self, update):
        query = update.get('callback_query')
        if query:
            chat_id = int(((query.get('message') or {}).get('chat') or {}).get('id') or 0)
            actor = int((query.get('from') or {}).get('id') or 0)
            data = str(query.get('data') or '')
            answer = 'This control is unavailable.'
            if chat_id in get_allowed_chats() and data.startswith('cancel:'):
                run = run_store.get(data.partition(':')[2])
                if run and run['chat_id'] == str(chat_id):
                    answer = self.execution.cancel(run, actor)
            elif chat_id in get_allowed_chats() and data.partition(':')[0] in ('approve', 'deny'):
                answer = self.execution.resolve_approval(data, chat_id, actor)
            await self.api.answer_callback(query['id'], answer)
            return
        msg = update.get('message') or update.get('edited_message') or {}
        chat_id = int((msg.get('chat') or {}).get('id') or 0)
        if not chat_id:
            return
        if chat_id not in get_allowed_chats():
            await self.handle_update(update)
            return
        text = str(msg.get('text') or '').strip()
        cmd = self.command(text)
        if cmd in ('/cancel', '/status'):
            runs = [r for r in run_store.recent(CHANNEL, chat_id, limit=100)
                    if actor_id(r['payload']) == actor_id(update)]
            if cmd == '/cancel':
                active = [r for r in runs if r['status'] in ('queued', 'running')]
                replies = [self.execution.cancel(r, actor_id(update)) for r in active]
                await self.api.send_message(chat_id, replies[0] if replies else 'No active task to cancel.')
            else:
                lines = []
                for run in runs[:3]:
                    steps = [e for e in run_store.events(run['id']) if e['kind'] in ('tool_start', 'tool_end', 'tool_observation')]
                    lines.append(f"{run['id']} · {run['status']} · {run['stage']}")
                    for e in steps[-4:]:
                        d = e['data']
                        lines.append(f"  {e['kind']}: {d.get('name', '?')} {str(d.get('result', ''))[:350]}")
                    if run['reply']:
                        lines.append(run['reply'][:1800])
                await self.api.send_message(chat_id, '\n'.join(lines) if lines else 'No tasks yet.')
            return
        # Editing a message is not consent to repeat a tool action. Live locations
        # are the only edited-message payload with an explicit update contract.
        if 'edited_message' in update and not msg.get('location'):
            return
        run = run_store.create(CHANNEL, chat_id, int(update['update_id']), update)
        self._schedule(run)

    async def run(self):
        run_store.recover(CHANNEL)
        for pending in run_store.queued(CHANNEL):
            self._schedule(pending)
        offset = channel_store.get_next_offset(CHANNEL)
        backoff = 1.0
        log.info("telegram channel started (offset=%s)", offset)
        while not self._stop.is_set():
            try:
                for pending in run_store.queued(CHANNEL):
                    self._schedule(pending)
                updates = await self.api.get_updates(offset, timeout=30)
                backoff = 1.0
                for u in updates:
                    uid = int(u.get("update_id", 0) or 0)
                    await self.dispatch_update(u)
                    # Durable intake succeeds before Telegram's cursor advances.
                    offset = max(offset, uid + 1)
                    channel_store.set_next_offset(CHANNEL, offset)
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

    async def _handle_cal(self, chat_id: int, text: str) -> None:
        """Interactive calendar setup + reads (one global token, shared)."""
        parts = (text or "").split(None, 2)
        sub = (parts[1] if len(parts) > 1 else "today").lower() or "today"
        rest = parts[2] if len(parts) > 2 else ""
        try:
            from tools import calendar as _cal
        except Exception as e:
            await self.api.send_message(chat_id, f"calendar error: {e}"[:500])
            return
        if not _cal.enabled():
            await self.api.send_message(chat_id, "Calendar is disabled (ZUMBA_NO_CALENDAR=1).")
            return
        try:
            if sub in ("today", ""):
                out = await asyncio.to_thread(_cal.today, 10)
            elif sub == "brief":
                out = await asyncio.to_thread(_cal.brief)
            elif sub == "status":
                out = await asyncio.to_thread(_cal.status_text)
            elif sub == "search" and rest.strip():
                out = await asyncio.to_thread(_cal.search, rest.strip())
            elif sub == "search":
                out = "Usage: /cal search <text>"
            elif sub == "auth":
                if rest.strip():
                    out = await asyncio.to_thread(_cal.auth_finish, rest.strip())
                    if not out.startswith("ERROR"):
                        # N1: explicit exchange consumed the code — drop any
                        # lingering pending entry so it can't double-exchange.
                        _CAL_PENDING.pop(chat_id, None)
                    # Paste flow carries no CSRF state (same user, manual copy);
                    # the stored state is verified on web-redirect callbacks.
                else:
                    out = await asyncio.to_thread(_cal.auth_start)
                    if not out.startswith("ERROR"):
                        _cal_prune_pending()
                        _CAL_PENDING[chat_id] = time.time()
                        out += ("\n\nNow paste ONLY the Google code (starts with '4/') here "
                                "as your next message (expires in 10 min). "
                                "Prefer explicit `/cal auth <code>` — safer than auto-detect.")
            elif sub == "token" and rest.strip():
                # /cal token <access> [refresh] — pasted secret never echoed.
                bits = rest.strip().split()
                tok, ref = (bits[0], bits[1] if len(bits) > 1 else "")
                out = await asyncio.to_thread(_cal.set_token, tok, ref)
            elif sub == "token":
                out = "Usage: /cal token <access_token> [refresh_token]"
            elif sub == "forget" and rest.strip().lower() in ("yes", "y", "confirm"):
                forgotten = await asyncio.to_thread(_cal.clear_token)
                out = ("Global calendar token forgotten." if forgotten
                       else "Nothing was saved.")
            elif sub == "forget":
                out = ("This forgets the ONE global token for all chats. "
                       "Confirm with `/cal forget yes`.")
            else:
                out = "Usage: /cal [today|search <q>|brief|status|auth [code]|token <access>|forget]"
            await self.api.send_message(chat_id, out[:3500])
        except Exception as e:
            await self.api.send_message(chat_id, f"calendar error: {e}"[:500])

    async def handle_location(self, chat_id: int, msg: dict) -> bool:
        loc = msg.get("location")
        if not isinstance(loc, dict):
            return False
        try:
            lat, lon = float(loc.get("latitude")), float(loc.get("longitude"))
        except Exception:
            return True
        try:
            from server import geo_store as _gs
            live = msg.get("live_period") or (msg.get("location") or {}).get("live_period")
            src = "live" if live else "point"
            _gs.record_ping(str(chat_id), lat, lon, 0.0, src)
            if live and _gs.track_active(str(chat_id)):
                pass  # window already active; pings accumulate silently
        except Exception as e:
            log.warning("geo ping failed: %s", e)
        if not (msg.get("live_period")):
            try: await self.api.send_message(chat_id, "\U0001f4cd Got it.")
            except Exception: pass
        return True

    async def handle_update(self, update: dict, run=None) -> None:
        msg = update.get("message") or update.get("edited_message") or {}
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
        if not self._limiter.allow(chat_id):
            await self.api.send_message(chat_id, "Slow down — one message at a time please.")
            return
        text = (msg.get("text") or "").strip()
        voice = msg.get("voice") or msg.get("audio")
        cmd = self.command(text)
        if cmd == '/new':
            channel_store.set_session_for_chat(CHANNEL, str(chat_id), f"tg-{chat_id}-{int(time.time())}")
            await self.api.send_message(chat_id, "Fresh session started.")
            return
        if cmd == '/help':
            await self.api.send_message(chat_id, "Send text or a voice note. Commands: /status (saved tasks and results), /cancel (stop your active/queued tasks), /new (fresh session), /help, /memory <query>, /cal [today|search|brief|status|auth|forget].")
            return
        if cmd == '/memory':
            parts = text.split(maxsplit=1)
            q = parts[1] if len(parts) > 1 else 'recent conversation'
            try:
                from memory import get_memory
                hits = await asyncio.to_thread(get_memory().recall, q, 8, 2000)
                await self.api.send_message(chat_id, str(hits)[:3500] or "(nothing recalled)")
            except Exception as e:
                await self.api.send_message(chat_id, f"memory error: {e}"[:500])
            return
        if cmd == '/cal' or text.strip().lower().startswith('/cal '):
            await self._handle_cal(chat_id, text)
            return
        # Pending OAuth code paste: after `/cal auth`, the next message that
        # strictly matches an auth-code shape finishes auth. Anything else
        # (incl. access tokens) falls through to the agent — never POSTed
        # to Google implicitly (M2).
        _cal_prune_pending()
        if not cmd and _cal_looks_like_code(text) and _CAL_PENDING.get(chat_id, 0) > time.time() - _CAL_PENDING_TTL:
            _CAL_PENDING.pop(chat_id, None)
            try:
                from tools import calendar as _cal
                out = await asyncio.to_thread(_cal.auth_finish, text.strip())
                # Never echo the pasted code back.
                await self.api.send_message(chat_id, out[:3500])
            except Exception as e:
                await self.api.send_message(chat_id, f"calendar auth error: {e}"[:500])
            return
        if await self.handle_location(chat_id, msg):
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
        sid = channel_store.resolve_session(CHANNEL, str(chat_id))
        if run is None:
            run = run_store.create(CHANNEL, chat_id, int(update['update_id']), update)
            if not run_store.claim(run['id']):
                return
        result = await self.execution.execute(run, sid, text)
        if is_voice and voice_reply_enabled() and result['status'] == 'completed':
            await self._maybe_voice_reply(chat_id, result['reply'])

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
_channel: TelegramChannel | None = None


def start_if_configured(app=None) -> asyncio.Task | None:
    global _channel_task, _channel
    if not get_token():
        return None
    if _channel_task is not None and not _channel_task.done():
        return _channel_task
    async def _runner():
        global _channel
        ch = TelegramChannel()
        _channel = ch
        try:
            await ch.run()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.exception("telegram channel crashed: %s", e)
        finally:
            await ch.close()
            _channel = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    _channel_task = loop.create_task(_runner())
    return _channel_task


async def stop_if_running():
    if _channel:
        _channel.stop()
    if _channel_task and not _channel_task.done():
        _channel_task.cancel()
        await asyncio.wait([_channel_task], timeout=6)
