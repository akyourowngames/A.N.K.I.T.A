"""Speech-to-text through headless Chrome + the Web Speech API.

Same approach as the Jarvis reference (Backend/SpeechToText.py): a tiny
local page runs webkitSpeechRecognition in continuous mode and the driver
reads the accumulated transcript. Free, no API key, works with the default
system microphone. All selenium imports stay inside this module so the rest
of the desktop app keeps working when the voice stack is unavailable.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head><title>Zumba Speech Recognition</title></head>
<body>
    <button id="start" onclick="startRecognition()">Start Recognition</button>
    <button id="end" onclick="stopRecognition()">Stop Recognition</button>
    <p id="output"></p>
    <p id="interim"></p>
    <script>
        const output = document.getElementById('output');
        const interim = document.getElementById('interim');
        let recognition;
        function startRecognition() {{
            recognition = new webkitSpeechRecognition() || new SpeechRecognition();
            recognition.lang = '{lang}';
            recognition.continuous = true;
            recognition.interimResults = true;
            recognition.onresult = function(event) {{
                let interimText = '';
                for (let i = event.resultIndex; i < event.results.length; i++) {{
                    const transcript = event.results[i][0].transcript;
                    if (event.results[i].isFinal) {{
                        output.textContent += transcript + ' ';
                    }} else {{
                        interimText += transcript;
                    }}
                }}
                interim.textContent = interimText;
            }};
            recognition.onend = function() {{
                try {{ recognition.start(); }} catch (e) {{}}
            }};
            recognition.start();
        }}
        function stopRecognition() {{
            try {{ recognition.stop(); }} catch (e) {{}}
            output.innerHTML = "";
            interim.innerHTML = "";
        }}
    </script>
</body>
</html>"""


class STTUnavailable(RuntimeError):
    pass


class ChromeSTT:
    """Blocking, single-utterance listener. Create once, reuse, close at exit."""

    def __init__(self, lang: str = "en-US"):
        self.lang = lang
        self._driver = None
        self._page_url = ""
        self._lock = threading.Lock()

    def _ensure_driver(self):
        if self._driver is not None:
            return self._driver
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
        except ImportError as exc:
            raise STTUnavailable(
                "selenium is not installed (pip install -r requirements-desktop.txt)"
            ) from exc
        page = HTML_PAGE.format(lang=self.lang)
        fd, path = tempfile.mkstemp(prefix="zumba_voice_", suffix=".html")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(page)
        self._page_url = "file:///" + path.replace("\\", "/")
        options = Options()
        # Auto-grant the mic permission prompt, but NEVER substitute a fake
        # audio device: --use-fake-device-for-media-stream hides the real
        # microphone and feeds silence/a test tone, so nothing transcribes.
        options.add_argument("--use-fake-ui-for-media-stream")
        options.add_argument("--headless=new")
        options.add_argument("--log-level=3")
        service = Service(ChromeDriverManager().install())
        self._driver = webdriver.Chrome(service=service, options=options)
        return self._driver

    def _element_text(self, element_id: str) -> str:
        from selenium.webdriver.common.by import By

        try:
            return self._driver.find_element(by=By.ID, value=element_id).text or ""
        except Exception:
            return ""

    def listen_once(self, timeout: float = 30.0,
                    abort: "threading.Event | None" = None,
                    poll: float = 0.4,
                    on_interim=None) -> str:
        """Wait for one utterance. Returns the transcript or "" on timeout/abort.

        on_interim, when given, is called with the live partial transcript so
        the GUI can show words as they are spoken.
        """
        with self._lock:
            try:
                driver = self._ensure_driver()
            except STTUnavailable:
                raise
            except Exception as exc:
                raise STTUnavailable(f"could not start Chrome STT: {exc}") from exc
            from selenium.webdriver.common.by import By

            try:
                driver.get(self._page_url)
                driver.find_element(by=By.ID, value="start").click()
            except Exception as exc:
                raise STTUnavailable(f"STT page failed: {exc}") from exc
            baseline = len(self._element_text("output"))
            last_interim = ""
            deadline = time.monotonic() + timeout
            try:
                while time.monotonic() < deadline:
                    if abort is not None and abort.is_set():
                        return ""
                    text = self._element_text("output")
                    if len(text) > baseline and text[baseline:].strip():
                        return text[baseline:].strip()
                    if on_interim is not None:
                        partial = self._element_text("interim").strip()
                        if partial and partial != last_interim:
                            last_interim = partial
                            try:
                                on_interim(partial)
                            except Exception:
                                pass
                    time.sleep(poll)
                return ""
            finally:
                try:
                    driver.find_element(by=By.ID, value="end").click()
                except Exception:
                    pass

    def close(self) -> None:
        with self._lock:
            if self._driver is not None:
                try:
                    self._driver.quit()
                except Exception:
                    pass
                self._driver = None
