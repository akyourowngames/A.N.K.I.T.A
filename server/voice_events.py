"""Bounded STT event bridge shared by HTTP and WebSocket transports."""
import queue
import threading

from core import speech


def transcription_events(data):
    events = queue.Queue(maxsize=32)
    cancelled = threading.Event()

    def emit(kind, body):
        while not cancelled.is_set():
            try:
                events.put((kind, body), timeout=.1)
                return
            except queue.Full:
                continue

    def run():
        try:
            result = speech.transcribe(data, abort=cancelled,
                on_partial=lambda text: emit('partial', {'transcript': text}))
            emit('done', result)
        except Exception as exc:
            emit('error', {'error': str(exc)})

    threading.Thread(target=run, daemon=True, name='voice-transcribe').start()
    try:
        yield 'start', {'engine': 'local-first'}
        while True:
            try:
                event = events.get(timeout=10)
            except queue.Empty:
                yield 'status', {'message': 'Transcribing...'}
                continue
            yield event
            if event[0] in ('done', 'error'):
                return
    finally:
        cancelled.set()
