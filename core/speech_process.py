"""Keep Whisper's native DLLs out of the Qt/web process on Windows."""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from types import SimpleNamespace


class WhisperProcess:
    def __init__(self, model):
        self.model = model
        self.process = None
        self.events = None
        atexit.register(self.close)

    def close(self):
        proc, self.process = self.process, None
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
            for pipe in (proc.stdin, proc.stdout):
                if pipe:
                    pipe.close()

    def _start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        env = os.environ.copy()
        env['ZUMBA_STT_MODEL'] = self.model
        root = str(Path(__file__).resolve().parent.parent)
        env['PYTHONPATH'] = root + os.pathsep + env.get('PYTHONPATH', '')
        proc = subprocess.Popen([sys.executable, '-u', '-m', 'core.speech_worker'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, cwd=root,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.process = proc
        events = queue.Queue()
        self.events = events
        def read():
            try:
                for line in proc.stdout:
                    events.put(json.loads(line))
            except (ValueError, OSError):
                pass
            finally:
                events.put({'type': 'error', 'error': 'Local STT worker exited unexpectedly.'})
        threading.Thread(target=read, daemon=True, name='stt-worker-output').start()

    def _next(self, abort=None):
        from core.speech import STTUnavailable
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if abort is not None and abort.is_set():
                self.close()
                raise STTUnavailable('Speech recognition cancelled.')
            try:
                event = self.events.get(timeout=.05)
            except queue.Empty:
                continue
            if event.get('type') == 'error':
                self.close()
                raise STTUnavailable(event.get('error', 'Local STT failed.'))
            return event
        self.close()
        raise STTUnavailable('Local STT timed out. Try a smaller cached model.')

    def _send(self, message, samples=None):
        from core.speech import STTUnavailable
        self._start()
        raw = samples.astype('<f4', copy=False).tobytes() if samples is not None else b''
        try:
            self.process.stdin.write((json.dumps({**message, 'bytes': len(raw)}) + '\n').encode())
            self.process.stdin.write(raw)
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            self.close()
            raise STTUnavailable('Local STT worker disconnected.') from exc

    def prepare(self, abort=None):
        self._send({'op': 'prepare'})
        self._next(abort)

    def transcribe(self, samples, abort=None, **kwargs):
        from core.speech import allowed_languages
        self._send({'op': 'transcribe', 'language': kwargs.get('language'),
                    'languages': allowed_languages()}, samples)
        info = self._next(abort)
        def segments():
            while True:
                event = self._next(abort)
                if event['type'] == 'done':
                    return
                yield SimpleNamespace(text=event['text'])
        return segments(), SimpleNamespace(language=info['language'])
