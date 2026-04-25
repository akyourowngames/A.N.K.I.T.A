from __future__ import annotations

import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path


def _import_cv2():
    try:
        import cv2

        return cv2, None
    except ImportError:
        return None, "opencv-python is not installed. Run: pip install opencv-python"


@dataclass(slots=True)
class CameraStatus:
    active: bool
    device_index: int
    frame_width: int
    frame_height: int
    latest_frame_path: str
    last_frame_time: float
    error: str = ""


class CameraSession:
    def __init__(self, *, device_index: int = 0, frame_width: int = 960, frame_height: int = 540) -> None:
        self.device_index = int(device_index)
        self.frame_width = max(int(frame_width), 320)
        self.frame_height = max(int(frame_height), 240)
        self.window_name = "JAKATA Live Camera"
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest_frame = None
        self._latest_frame_path = ""
        self._last_frame_time = 0.0
        self._last_error = ""

    def start(self) -> CameraStatus:
        with self._lock:
            if self.is_active:
                return self.status()
            self._stop_event.clear()
            self._last_error = ""
            self._thread = threading.Thread(target=self._preview_loop, name="jakata-camera-preview", daemon=True)
            self._thread.start()

        deadline = time.time() + 5.0
        while time.time() < deadline:
            status = self.status()
            if status.active and status.last_frame_time > 0:
                return status
            if status.error:
                return status
            time.sleep(0.1)
        return self.status()

    def stop(self) -> CameraStatus:
        with self._lock:
            self._stop_event.set()
            thread = self._thread
            self._thread = None
        if thread is not None:
            thread.join(timeout=2.0)
        return self.status()

    @property
    def is_active(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive() and not self._stop_event.is_set())

    def status(self) -> CameraStatus:
        with self._lock:
            return CameraStatus(
                active=self.is_active,
                device_index=self.device_index,
                frame_width=self.frame_width,
                frame_height=self.frame_height,
                latest_frame_path=self._latest_frame_path,
                last_frame_time=self._last_frame_time,
                error=self._last_error,
            )

    def snapshot(self) -> str:
        with self._lock:
            if self._latest_frame is not None:
                frame = self._latest_frame.copy()
            else:
                frame = None
        if frame is None:
            frame = self._capture_one_shot()
        return self._write_frame(frame)

    def _capture_one_shot(self):
        cv2, error = _import_cv2()
        if cv2 is None:
            raise RuntimeError(error)
        capture = self._open_capture(cv2)
        if capture is None or not capture.isOpened():
            raise RuntimeError(f"Unable to open camera device {self.device_index}.")
        try:
            ok, frame = capture.read()
            if not ok or frame is None:
                raise RuntimeError("Camera did not return a frame.")
            return frame
        finally:
            capture.release()

    def _open_capture(self, cv2):
        if hasattr(cv2, "CAP_DSHOW"):
            capture = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
            if capture is not None and capture.isOpened():
                return capture
            if capture is not None:
                capture.release()
        return cv2.VideoCapture(self.device_index)

    def _preview_loop(self) -> None:
        cv2, error = _import_cv2()
        if cv2 is None:
            with self._lock:
                self._last_error = error or "opencv import failed"
            return

        capture = self._open_capture(cv2)
        if capture is None or not capture.isOpened():
            with self._lock:
                self._last_error = f"Unable to open camera device {self.device_index}."
            return

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
        capture.set(cv2.CAP_PROP_FPS, 24)

        try:
            cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.window_name, self.frame_width, self.frame_height)
            while not self._stop_event.is_set():
                ok, frame = capture.read()
                if not ok or frame is None:
                    with self._lock:
                        self._last_error = "Camera frame read failed."
                    time.sleep(0.1)
                    continue

                preview = frame.copy()
                cv2.putText(
                    preview,
                    "JAKATA live camera",
                    (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (64, 255, 160),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    preview,
                    "Ask JAKATA what it sees or use /camera ask <prompt>",
                    (12, 56),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
                with self._lock:
                    self._latest_frame = frame
                    self._last_frame_time = time.time()
                    self._last_error = ""
                cv2.imshow(self.window_name, preview)
                key = cv2.waitKey(1) & 0xFF
                if key == 27 or key == ord("q"):
                    self._stop_event.set()
                    break
                try:
                    visible = cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE)
                    if visible < 1:
                        self._stop_event.set()
                        break
                except Exception:
                    pass
        finally:
            capture.release()
            try:
                cv2.destroyWindow(self.window_name)
            except Exception:
                pass

    def _write_frame(self, frame) -> str:
        cv2, error = _import_cv2()
        if cv2 is None:
            raise RuntimeError(error)

        resized = self._resize_for_upload(cv2, frame)
        path = Path(tempfile.gettempdir()) / f"jakata_camera_{next(tempfile._get_candidate_names())}.jpg"
        for quality in (85, 75, 65, 55, 45):
            ok, encoded = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
            if not ok:
                continue
            payload = encoded.tobytes()
            if len(payload) <= 170_000 or quality == 45:
                path.write_bytes(payload)
                with self._lock:
                    self._latest_frame_path = str(path)
                return str(path)
        raise RuntimeError("Failed to encode camera frame.")

    def _resize_for_upload(self, cv2, frame):
        height, width = frame.shape[:2]
        max_width = 896
        if width <= max_width:
            return frame
        ratio = max_width / float(width)
        return cv2.resize(frame, (int(width * ratio), int(height * ratio)))
