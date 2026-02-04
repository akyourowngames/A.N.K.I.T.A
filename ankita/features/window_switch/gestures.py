"""Gesture mode for window switching using MediaPipe + OpenCV.

This module implements a simple webcam loop that detects hand landmarks
and recognizes a couple of gestures (swipe left/right, open-palm point).

MediaPipe is REQUIRED for gesture detection.
"""
from typing import Dict

# ---- Helpers (module-level so they can be tested directly) ----

def maximize_active_window() -> bool:
    """Maximize the currently active window (best-effort)."""
    try:
        import win32gui, win32con
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return False
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        return True
    except Exception:
        try:
            import pygetwindow as gw
            w = gw.getActiveWindow()
            if w:
                w.maximize()
                return True
        except Exception:
            try:
                import pyautogui
                pyautogui.hotkey('win', 'up')
                return True
            except Exception:
                return False


def perform_swipe_action(gesture_name: str) -> dict:
    """Perform OS-level Alt+Tab action for gesture and maximize the resulting window.

    Returns a dict with status/message.
    """
    try:
        import time
        import pyautogui

        if gesture_name == 'swipe_left':
            # Alt+Shift+Tab → move RIGHT in Alt-Tab list
            pyautogui.keyDown('alt')
            pyautogui.keyDown('shift')
            pyautogui.press('tab')
            pyautogui.keyUp('shift')
            pyautogui.keyUp('alt')
        elif gesture_name == 'swipe_right':
            # Alt+Tab → move LEFT in Alt-Tab list
            pyautogui.keyDown('alt')
            pyautogui.press('tab')
            pyautogui.keyUp('alt')
        else:
            return {'status': 'fail', 'message': f'unknown gesture {gesture_name}'}

        # short pause to let OS complete the switch, then maximize
        time.sleep(0.12)
        maximized = maximize_active_window()
        return {'status': 'success' if maximized else 'partial', 'message': 'swipe action performed'}
    except Exception as e:
        return {'status': 'fail', 'message': str(e)}

# ---------------------------------------------------------------


def run_gesture_mode(timeout_seconds: int = 0, headless: bool = False) -> Dict:
    """Run webcam gesture loop. Blocks until user quits (press 'q')

    Returns a dict describing the outcome or an 'unavailable' reason.
    """
    try:
        import cv2
        import mediapipe as mp
        import time
        from collections import deque
        from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions, HandLandmarker, HandLandmarkerOptions
        # pyautogui and win32 are used only when a swipe is detected
        import pyautogui
    except Exception as e:
        return {'status': 'unavailable', 'message': f'required dependencies missing: {e}. Install: pip install opencv-python mediapipe pyautogui'}

    # Swipe tuning constants (normalized coords)
    SWIPE_THRESHOLD = 0.045   # normalized X movement (nose tip)
    STABLE_FRAMES = 6
    COOLDOWN = 0.9

    # Scroll constants
    SCROLL_DEADZONE = 0.03  # vertical dead zone
    SCROLL_GAIN = 1600      # proportional gain
    MAX_SCROLL = 300        # clamp
    NEUTRAL_ALPHA = 0.95    # smoothing factor for neutral recentering
    SCROLL_STABLE_FRAMES = 4

    def lock_screen():
        """Lock the workstation using Windows API; fallback to Win+L keypress."""
        try:
            import ctypes
            ctypes.windll.user32.LockWorkStation()
        except Exception:
            try:
                import pyautogui
                pyautogui.hotkey('win', 'l')
            except Exception:
                pass

    # runtime state
    x_history = deque(maxlen=STABLE_FRAMES)
    neutral_y = None  # dynamic neutral Y
    scroll_counter = 0
    lock_start: float | None = None  # timer for fist hold
    last_lock = 0.0  # last lock timestamp
    last_action = 0.0

    # MediaPipe is now REQUIRED - use FaceLandmarker (Tasks API)
    try:
        import os
        import urllib.request

        model_path = os.path.join(os.path.dirname(__file__), 'face_landmarker.task')
        if not os.path.exists(model_path):
            urllib.request.urlretrieve(
                'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
                model_path,
            )

        options = FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=0.6,
            min_face_presence_confidence=0.6,
            min_tracking_confidence=0.6,
        )
        face_landmarker = FaceLandmarker.create_from_options(options)

        # Hand landmarker for fist detection (lock screen)
        hand_model = os.path.join(os.path.dirname(__file__), 'hand_landmarker.task')
        if not os.path.exists(hand_model):
            urllib.request.urlretrieve(
                'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
                hand_model)
        h_opts = HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=hand_model),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_hands=1,
            min_hand_detection_confidence=0.6,
            min_hand_presence_confidence=0.6,
            min_tracking_confidence=0.5,
        )
        hand_landmarker = HandLandmarker.create_from_options(h_opts)
    except Exception as e:
        return {'status': 'unavailable', 'message': f'MediaPipe FaceLandmarker initialization failed: {e}. Try reinstalling mediapipe.'}

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return {'status': 'fail', 'message': 'could not open webcam'}

    prev_x = None
    start = time.time()
    gesture = None

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                # Try one quick reopen if read fails (some cameras/drivers are flaky)
                try:
                    cap.release()
                except Exception:
                    pass
                time.sleep(0.2)
                cap = cv2.VideoCapture(0)
                ret, frame = cap.read()
                if not ret:
                    break
            img = cv2.flip(frame, 1)

            h, w, _ = img.shape
            gesture = None  # Reset gesture each frame

            delta = 0.0
            mp_image = None
            try:
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                results = face_landmarker.detect(mp_image)
            except Exception:
                results = None

            mouth_open = False
            nose = None
            if results and getattr(results, 'face_landmarks', None):
                face = results.face_landmarks[0]
                try:
                    nose = face[1]
                except Exception:
                    nose = None

                if nose is not None:
                    cx, cy = int(nose.x * w), int(nose.y * h)
                    cv2.circle(img, (cx, cy), 6, (255, 0, 0), -1)

                    x_norm = nose.x
                    x_history.append(x_norm)

                    if len(x_history) == STABLE_FRAMES:
                        delta = x_history[-1] - x_history[0]

                        if delta > SWIPE_THRESHOLD and (time.time() - last_action) > COOLDOWN:
                            gesture = 'swipe_right'
                            last_action = time.time()
                            x_history.clear()
                        elif delta < -SWIPE_THRESHOLD and (time.time() - last_action) > COOLDOWN:
                            gesture = 'swipe_left'
                            last_action = time.time()
                            x_history.clear()

            # ---------------- Fist → Lock Screen ----------------
            LOCK_HOLD_TIME = 0.3  # seconds to hold fist
            LOCK_COOLDOWN = 3.0   # min seconds between locks

            def is_fist(lm):
                try:
                    tips = [8, 12, 16, 20]
                    pips = [6, 10, 14, 18]
                    return all(lm[tip].y > lm[pip].y for tip, pip in zip(tips, pips))
                except Exception:
                    return False

            hand_res = None
            try:
                if mp_image is not None:
                    hand_res = hand_landmarker.detect(mp_image)
            except Exception:
                hand_res = None

            if hand_res and getattr(hand_res, 'hand_landmarks', None):
                hand_lm = hand_res.hand_landmarks[0]
                if is_fist(hand_lm):
                    if lock_start is None:
                        lock_start = time.time()
                    elif (time.time() - lock_start) >= LOCK_HOLD_TIME and (time.time() - last_lock) > LOCK_COOLDOWN:
                        lock_screen()
                        last_lock = time.time()
                        lock_start = None
                else:
                    lock_start = None
            else:
                lock_start = None

            if lock_start is not None:
                remaining = max(0.0, LOCK_HOLD_TIME - (time.time() - lock_start))
                cv2.putText(img, f"Lock in {remaining:.1f}s", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,255), 2)

            # Overlay instructions
            cv2.putText(img, "MediaPipe: Move head left/right to trigger. Press 'a'/'d' for test gestures. Press 'q' to quit.", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)

            # Apply scrolling with dynamic neutral + stability filter
            if nose is None:
                neutral_y = None
                scroll_counter = 0
                scroll_delta = 0.0
            else:
                if neutral_y is None:
                    neutral_y = nose.y

                # Exponential moving average for neutral recentering
                neutral_y = (NEUTRAL_ALPHA * neutral_y) + ((1 - NEUTRAL_ALPHA) * nose.y)

                scroll_delta = neutral_y - nose.y  # +ve = head up

            if abs(scroll_delta) > SCROLL_DEADZONE:
                scroll_counter += 1
            else:
                scroll_counter = 0

            if scroll_counter >= SCROLL_STABLE_FRAMES and not mouth_open:
                scroll_amount = int(scroll_delta * SCROLL_GAIN)
                scroll_amount = max(-MAX_SCROLL, min(MAX_SCROLL, scroll_amount))
                try:
                    pyautogui.scroll(scroll_amount)
                except Exception:
                    pass

            # Show swipe delta (normalized) for tuning/debug
            try:
                disp_delta = delta if 'delta' in locals() else 0.0
            except Exception:
                disp_delta = 0.0
            cv2.putText(img, f'Head X: {disp_delta:.2f}', (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,0), 2)

            if gesture:
                direction = 'UP' if scroll_delta>0 else 'DOWN'
                if abs(scroll_delta) > SCROLL_DEADZONE:
                    cv2.putText(img, f'SCROLL {direction}', (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,255), 2)

                cv2.putText(img, f'Gesture: {gesture}', (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
                # Perform OS-level swipe action (non-blocking) and maximize the resulting window
                try:
                    # run action in background to keep UI smooth
                    import threading

                    def _perform_and_feedback(g):
                        try:
                            res = perform_swipe_action(g)
                        except Exception as e:
                            res = {'status': 'fail', 'message': str(e)}
                        return res

                    bg = threading.Thread(target=_perform_and_feedback, args=(gesture,), daemon=True)
                    bg.start()

                    if not headless:
                        cv2.putText(img, 'Action: sent', (10, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)
                except Exception as e:
                    if not headless:
                        cv2.putText(img, f'Error: {str(e)}', (10, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 2)

            if not headless:
                cv2.imshow('Ankita - Window Switch (gesture)', img)

            if headless:
                # In headless mode, no keyboard handling - rely on timeout
                pass
            else:
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('a'):
                    gesture = 'swipe_left'
                    perform_swipe_action('swipe_left')
                elif key == ord('d'):
                    gesture = 'swipe_right'
                    perform_swipe_action('swipe_right')

                if gesture:
                    # show feedback for key-based test
                    cv2.putText(img, f'Action: test-{gesture}', (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

            if timeout_seconds and (time.time() - start) > timeout_seconds:
                break

    finally:
        try:
            cap.release()
        except Exception:
            pass
        try:
            if not headless:
                cv2.destroyAllWindows()
        except Exception:
            pass
        try:
            if hand_landmarker:
                hand_landmarker.close()
            if face_landmarker:
                face_landmarker.close()
        except Exception:
            pass

    return {'status': 'stopped', 'message': 'gesture mode exited'}
