from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PyQt5.QtCore import QObject, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QKeyEvent, QMovie, QPainter
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


PROJECT_ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Launch the minimal JARVIS frontend.")
    parser.add_argument("--demo", action="store_true", help="Open without loading the assistant Brain.")
    parser.add_argument("--windowed", action="store_true", help="Open in a normal window instead of fullscreen.")
    parser.add_argument("--screenshot", type=Path, help="Save a preview screenshot and exit.")
    parser.add_argument("--width", type=int, default=1280, help="Windowed/screenshot width.")
    parser.add_argument("--height", type=int, default=720, help="Windowed/screenshot height.")
    args = parser.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("JARVIS")
    app.setFont(QFont("Segoe UI", 11))

    window = JarvisWindow(PROJECT_ROOT, load_brain=not args.demo and not args.screenshot)
    if args.windowed or args.screenshot:
        window.resize(args.width, args.height)
        window.show()
    else:
        window.showFullScreen()

    if args.screenshot:
        output_path = args.screenshot.resolve()

        def save_and_quit() -> None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(output_path))
            app.quit()

        QTimer.singleShot(900, save_and_quit)

    app.exec_()


class BrainLoader(QObject):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self.project_root = project_root

    def run(self) -> None:
        try:
            from core.brain import Brain

            self.ready.emit(Brain.create(self.project_root))
        except Exception as error:
            self.failed.emit(str(error))


class AssistantWorker(QObject):
    chunk = pyqtSignal(str)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, brain: object, prompt: str) -> None:
        super().__init__()
        self.brain = brain
        self.prompt = prompt

    def run(self) -> None:
        parts: list[str] = []
        try:
            for chunk in getattr(self.brain, "answer_stream")(self.prompt):
                text = str(chunk)
                if not text:
                    continue
                parts.append(text)
                self.chunk.emit(text)
            self.finished.emit("".join(parts).strip())
        except Exception as error:
            self.failed.emit(str(error))


class TTSWorker(QObject):
    finished = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, project_root: Path, text: str) -> None:
        super().__init__()
        self.project_root = project_root
        self.text = text

    def run(self) -> None:
        try:
            from core.speech import TTSConfig, create_text_to_speech

            config = TTSConfig.from_env(self.project_root)
            if not config.enabled or not self.text.strip():
                self.finished.emit()
                return
            create_text_to_speech(config).speak(self.text)
            self.finished.emit()
        except Exception as error:
            self.failed.emit(str(error))


class VoiceWorker(QObject):
    transcript = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, project_root: Path, brain: object) -> None:
        super().__init__()
        self.project_root = project_root
        self.brain = brain

    def run(self) -> None:
        audio_path: Path | None = None
        try:
            from core.speech import MicrophoneListener, SpeechConfig, create_speech_to_text, speech_to_english

            config = SpeechConfig.from_env(self.project_root)
            speech = create_speech_to_text(config)
            listener = MicrophoneListener(config)
            audio_path = listener.listen_to_wav()
            text = speech_to_english(audio_path, speech, getattr(self.brain, "llm"), config).strip()
            if text:
                self.transcript.emit(text)
            else:
                self.failed.emit("I could not detect speech.")
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            if audio_path is not None:
                audio_path.unlink(missing_ok=True)


class DarkCanvas(QWidget):
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        super().paintEvent(event)


class JarvisWindow(QMainWindow):
    def __init__(self, project_root: Path, *, load_brain: bool = True) -> None:
        super().__init__()
        self.project_root = project_root
        self.brain: object | None = None
        self.ai_name = "JARVIS"
        self.user_name = "You"
        self.loader_thread: QThread | None = None
        self.loader_worker: BrainLoader | None = None
        self.stream_thread: QThread | None = None
        self.stream_worker: AssistantWorker | None = None
        self.tts_thread: QThread | None = None
        self.tts_worker: TTSWorker | None = None
        self.voice_thread: QThread | None = None
        self.voice_worker: VoiceWorker | None = None
        self.response_buffer = ""
        self.response_max_height = 180

        self.setWindowTitle("JARVIS")
        self.setStyleSheet(APP_QSS)
        self.setMinimumSize(900, 560)

        root = DarkCanvas()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(48, 44, 48, 38)
        layout.setSpacing(18)
        layout.addStretch(1)

        self.orb = QLabel()
        self.orb.setAlignment(Qt.AlignCenter)
        self.orb_movie: QMovie | None = None
        orb_path = find_orb_gif(project_root)
        if orb_path:
            self.orb_movie = QMovie(str(orb_path))
            self.orb_movie.setCacheMode(QMovie.CacheAll)
            self.orb.setMovie(self.orb_movie)
            self.orb_movie.start()
        else:
            self.orb.setText("O")
            self.orb.setObjectName("FallbackOrb")
        layout.addWidget(self.orb, 0, Qt.AlignCenter)

        self.response_scroll = QScrollArea()
        self.response_scroll.setObjectName("ResponseScroll")
        self.response_scroll.setWidgetResizable(False)
        self.response_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.response_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.response_scroll.setMinimumHeight(54)

        self.response = QLabel("Waking up...")
        self.response.setObjectName("Response")
        self.response.setAlignment(Qt.AlignCenter)
        self.response.setWordWrap(True)
        self.response.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.response.setMinimumHeight(34)
        self.response_scroll.setWidget(self.response)
        layout.addWidget(self.response_scroll, 2, Qt.AlignHCenter)

        layout.addStretch(1)

        prompt_row = QHBoxLayout()
        prompt_row.setContentsMargins(0, 0, 0, 0)
        prompt_row.setSpacing(0)
        prompt_row.addStretch(1)

        self.prompt_shell = QFrame()
        self.prompt_shell.setObjectName("PromptShell")
        prompt_shell_layout = QHBoxLayout(self.prompt_shell)
        prompt_shell_layout.setContentsMargins(18, 7, 7, 7)
        prompt_shell_layout.setSpacing(10)

        self.input = QLineEdit()
        self.input.setObjectName("Prompt")
        self.input.setPlaceholderText("Ask JARVIS...")
        self.input.returnPressed.connect(self.submit_current_prompt)
        prompt_shell_layout.addWidget(self.input, 1)

        self.mic_button = QPushButton("MIC")
        self.mic_button.setObjectName("MicButton")
        self.mic_button.setCursor(Qt.PointingHandCursor)
        self.mic_button.setFixedSize(70, 42)
        self.mic_button.clicked.connect(self.listen_once)
        prompt_shell_layout.addWidget(self.mic_button)

        prompt_row.addWidget(self.prompt_shell)
        prompt_row.addStretch(1)
        layout.addLayout(prompt_row)

        self.setCentralWidget(root)

        if load_brain:
            self.start_brain_loader()
        else:
            self.brain = None
            self.input.setEnabled(True)
            self.set_response("Yes, Sir.")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.orb_movie is not None:
            side = min(int(self.width() * 0.37), int(self.height() * 0.50), 470)
            side = max(side, 240)
            self.orb_movie.setScaledSize(QSize(side, side))
        self.prompt_shell.setFixedWidth(min(720, max(360, int(self.width() * 0.48))))
        response_width = min(920, max(420, int(self.width() * 0.72)))
        self.response_max_height = max(130, int(self.height() * 0.32))
        self.response_scroll.setFixedWidth(response_width)
        self.response.setFixedWidth(response_width - 18)
        self.update_response_geometry()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        if event.key() == Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            return
        super().keyPressEvent(event)

    def start_brain_loader(self) -> None:
        self.input.setEnabled(False)
        self.mic_button.setEnabled(False)
        self.set_response("Loading core...")
        self.loader_thread = QThread(self)
        self.loader_worker = BrainLoader(self.project_root)
        self.loader_worker.moveToThread(self.loader_thread)
        self.loader_thread.started.connect(self.loader_worker.run)
        self.loader_worker.ready.connect(self.brain_ready)
        self.loader_worker.failed.connect(self.brain_failed)
        self.loader_worker.ready.connect(self.loader_worker.deleteLater)
        self.loader_worker.failed.connect(self.loader_worker.deleteLater)
        self.loader_thread.finished.connect(self.loader_thread_finished)
        self.loader_thread.start()

    def brain_ready(self, brain: object) -> None:
        self.brain = brain
        self.ai_name = str(getattr(brain, "ai_name", "JARVIS"))
        self.user_name = str(getattr(brain, "user_name", "You"))
        self.input.setEnabled(True)
        self.mic_button.setEnabled(True)
        self.set_response("Yes, Sir.")
        quit_thread(self.loader_thread)

    def brain_failed(self, message: str) -> None:
        self.input.setEnabled(True)
        self.mic_button.setEnabled(True)
        self.set_response(f"Core error: {message}")
        quit_thread(self.loader_thread)

    def loader_thread_finished(self) -> None:
        self.loader_thread = None
        self.loader_worker = None

    def submit_current_prompt(self) -> None:
        prompt = self.input.text().strip()
        if not prompt:
            return
        self.input.clear()
        self.submit_prompt(prompt)

    def submit_prompt(self, prompt: str) -> None:
        if self.brain is None:
            self.set_response("Brain is still loading.")
            return
        if qt_thread_is_running(self.stream_thread):
            self.set_response("Still thinking.")
            return

        self.response_buffer = ""
        self.set_response("Thinking...")
        self.input.setEnabled(False)
        self.mic_button.setEnabled(False)

        self.stream_thread = QThread(self)
        self.stream_worker = AssistantWorker(self.brain, prompt)
        self.stream_worker.moveToThread(self.stream_thread)
        self.stream_thread.started.connect(self.stream_worker.run)
        self.stream_worker.chunk.connect(self.stream_chunk)
        self.stream_worker.finished.connect(self.stream_finished)
        self.stream_worker.failed.connect(self.stream_failed)
        self.stream_worker.finished.connect(self.stream_worker.deleteLater)
        self.stream_worker.failed.connect(self.stream_worker.deleteLater)
        self.stream_thread.finished.connect(self.stream_thread_finished)
        self.stream_thread.start()

    def stream_chunk(self, chunk: str) -> None:
        self.response_buffer += chunk
        self.set_response(self.response_buffer.strip() or "Thinking...")

    def stream_finished(self, answer: str) -> None:
        final_answer = answer or self.response_buffer or "Done."
        self.set_response(final_answer)
        self.input.setEnabled(True)
        self.mic_button.setEnabled(True)
        self.input.setFocus()
        self.speak(final_answer)
        quit_thread(self.stream_thread)

    def stream_failed(self, message: str) -> None:
        self.set_response(f"Error: {message}")
        self.input.setEnabled(True)
        self.mic_button.setEnabled(True)
        self.input.setFocus()
        quit_thread(self.stream_thread)

    def stream_thread_finished(self) -> None:
        self.stream_thread = None
        self.stream_worker = None

    def set_response(self, text: str) -> None:
        clean = text.strip() or "..."
        self.response.setText(clean)
        self.response.setAlignment(Qt.AlignCenter)
        self.update_response_geometry()
        self.response_scroll.verticalScrollBar().setValue(0)

    def update_response_geometry(self) -> None:
        self.response.adjustSize()
        content_height = max(40, self.response.height() + 8)
        self.response_scroll.setFixedHeight(min(self.response_max_height, content_height))

    def speak(self, text: str) -> None:
        if qt_thread_is_running(self.tts_thread):
            quit_thread(self.tts_thread)
        self.tts_thread = QThread(self)
        self.tts_worker = TTSWorker(self.project_root, text)
        self.tts_worker.moveToThread(self.tts_thread)
        self.tts_thread.started.connect(self.tts_worker.run)
        self.tts_worker.finished.connect(self.tts_done)
        self.tts_worker.failed.connect(self.tts_failed)
        self.tts_worker.finished.connect(self.tts_worker.deleteLater)
        self.tts_worker.failed.connect(self.tts_worker.deleteLater)
        self.tts_thread.finished.connect(self.tts_thread_finished)
        self.tts_thread.start()

    def tts_done(self) -> None:
        quit_thread(self.tts_thread)

    def tts_failed(self, message: str) -> None:
        print(f"TTS error: {message}")
        quit_thread(self.tts_thread)

    def tts_thread_finished(self) -> None:
        self.tts_thread = None
        self.tts_worker = None

    def listen_once(self) -> None:
        if self.brain is None:
            self.set_response("Brain is still loading.")
            return
        if qt_thread_is_running(self.voice_thread) or qt_thread_is_running(self.stream_thread):
            return
        self.set_response("Listening...")
        self.input.setEnabled(False)
        self.mic_button.setEnabled(False)
        self.voice_thread = QThread(self)
        self.voice_worker = VoiceWorker(self.project_root, self.brain)
        self.voice_worker.moveToThread(self.voice_thread)
        self.voice_thread.started.connect(self.voice_worker.run)
        self.voice_worker.transcript.connect(self.voice_transcript)
        self.voice_worker.failed.connect(self.voice_failed)
        self.voice_worker.transcript.connect(self.voice_worker.deleteLater)
        self.voice_worker.failed.connect(self.voice_worker.deleteLater)
        self.voice_thread.finished.connect(self.voice_thread_finished)
        self.voice_thread.start()

    def voice_transcript(self, text: str) -> None:
        quit_thread(self.voice_thread)
        self.input.setEnabled(True)
        self.mic_button.setEnabled(True)
        self.submit_prompt(text)

    def voice_failed(self, message: str) -> None:
        self.set_response(f"Mic error: {message}")
        self.input.setEnabled(True)
        self.mic_button.setEnabled(True)
        self.input.setFocus()
        quit_thread(self.voice_thread)

    def voice_thread_finished(self) -> None:
        self.voice_thread = None
        self.voice_worker = None

    def closeEvent(self, event) -> None:  # noqa: N802
        quit_thread(self.loader_thread)
        quit_thread(self.stream_thread)
        quit_thread(self.tts_thread)
        quit_thread(self.voice_thread)
        super().closeEvent(event)


def find_orb_gif(root: Path) -> Path | None:
    explicit = os.getenv("JARVIS_ORB_GIF", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = root / path
        if path.exists():
            return path
    gifs = sorted(root.glob("*.gif"), key=lambda item: item.stat().st_mtime, reverse=True)
    return gifs[0] if gifs else None


def qt_thread_is_running(thread: QThread | None) -> bool:
    return bool(thread is not None and thread.isRunning())


def quit_thread(thread: QThread | None) -> None:
    if thread is None:
        return
    try:
        thread.quit()
        thread.wait(1500)
    except RuntimeError:
        pass


APP_QSS = """
QMainWindow, QWidget {
    background: #000000;
    color: #ffffff;
    font-family: "Segoe UI";
}

#Response {
    color: rgba(255, 255, 255, 232);
    font-size: 19px;
    font-weight: 500;
    line-height: 1.35;
    padding: 0 10px;
    selection-background-color: rgba(255, 255, 255, 76);
}

#ResponseScroll {
    background: transparent;
    border: 0;
}

#ResponseScroll QWidget {
    background: transparent;
}

#ResponseScroll QScrollBar:vertical {
    background: transparent;
    border: 0;
    width: 7px;
    margin: 2px 0;
}

#ResponseScroll QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 70);
    border-radius: 3px;
    min-height: 32px;
}

#ResponseScroll QScrollBar::add-line:vertical,
#ResponseScroll QScrollBar::sub-line:vertical {
    height: 0;
}

#ResponseScroll QScrollBar:horizontal {
    height: 0;
}

#PromptShell {
    background: rgba(255, 255, 255, 12);
    border: 1px solid rgba(255, 255, 255, 46);
    border-radius: 25px;
}

#PromptShell:hover {
    background: rgba(255, 255, 255, 15);
    border: 1px solid rgba(255, 255, 255, 72);
}

#Prompt {
    background: transparent;
    border: 0;
    color: rgba(255, 255, 255, 238);
    font-size: 16px;
    padding: 8px 4px;
    selection-background-color: rgba(255, 255, 255, 76);
}

#MicButton {
    background: rgba(255, 255, 255, 22);
    border: 1px solid rgba(255, 255, 255, 70);
    border-radius: 21px;
    color: rgba(255, 255, 255, 238);
    font-size: 12px;
    font-weight: 800;
}

#MicButton:hover {
    border: 1px solid rgba(255, 255, 255, 150);
    background: rgba(255, 255, 255, 36);
}

#MicButton:disabled {
    color: rgba(255, 255, 255, 55);
    border: 1px solid rgba(255, 255, 255, 18);
}

#Prompt:focus {
    color: #ffffff;
}

#Prompt:disabled {
    color: rgba(255, 255, 255, 70);
}

#FallbackOrb {
    color: #ffffff;
    font-size: 180px;
    font-weight: 200;
}
"""


if __name__ == "__main__":
    main()
