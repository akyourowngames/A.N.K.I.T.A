"""Private binary-audio/JSON protocol worker; never imports Qt or application state."""
import contextlib
import json
import os
import sys


def recognize(model, samples, language=None, languages=()):
    options = dict(task='transcribe', beam_size=1, vad_filter=False,
                   condition_on_previous_text=False)
    segments, info = model.transcribe(samples, language=language, **options)
    if language is None and languages and info.language not in languages:
        candidates = [(probability, code) for code, probability in (info.all_language_probs or [])
                      if code in languages]
        if not candidates:
            raise ValueError('Configured STT language codes are not supported by this model.')
        # Whisper's audio classifier decides among the user's configured languages.
        selected = max(candidates)[1]
        segments, info = model.transcribe(samples, language=selected, **options)
    return segments, info


def main():
    model = None
    output = sys.stdout
    def emit(event):
        output.write(json.dumps(event) + '\n')
        output.flush()
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return
        try:
            request = json.loads(line)
            size = int(request.get('bytes', 0))
            if not 0 <= size <= 16000 * 60 * 4:
                raise ValueError('Invalid audio size')
            audio = sys.stdin.buffer.read(size)
            if len(audio) != size:
                return
            with contextlib.redirect_stdout(sys.stderr):
                if model is None:
                    from faster_whisper import WhisperModel
                    model = WhisperModel(os.getenv('ZUMBA_STT_MODEL', 'tiny'), device='cpu',
                        compute_type='int8', cpu_threads=2, local_files_only=True)
                if request['op'] == 'prepare':
                    emit({'type': 'ready'})
                    continue
                import numpy as np
                samples = np.frombuffer(audio, dtype='<f4').copy()
                segments, info = recognize(model, samples, language=request.get('language'),
                                           languages=request.get('languages') or ())
                emit({'type': 'info', 'language': info.language})
                for segment in segments:
                    emit({'type': 'segment', 'text': segment.text})
                emit({'type': 'done'})
        except Exception as exc:
            emit({'type': 'error', 'error': 'Local STT failed. Cache the model with '
                'python desktop/mic_test.py --download-model. ' + str(exc)})


if __name__ == '__main__':
    main()
