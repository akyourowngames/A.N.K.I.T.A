"""Window switch feature (title-match first, CV fallback later).

Public API:
  handle_window_switch(query: str) -> dict

This feature is designed to be called by Ankita (via an adapter). It will try
to find a window by title and bring it to foreground. It writes an episode to
memory recording the attempt/result and logs focus method attempts to
`ankita/logs/window_switch.log`.
"""
from typing import Optional
import os
import logging

# Logging setup
_LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'logs'))
os.makedirs(_LOG_DIR, exist_ok=True)
logger = logging.getLogger('ankita.window_switch')
if not logger.handlers:
    fh = logging.FileHandler(os.path.join(_LOG_DIR, 'window_switch.log'), encoding='utf-8')
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)


def _record_episode(query: str, matched: Optional[str], status: str):
    try:
        from ankita.memory.memory_manager import add_episode
        add_episode('system.window_switch', {'query': query, 'matched': matched}, {'status': status})
    except Exception:
        pass


def handle_gesture_switch(gesture: str) -> dict:
    """Map a detected gesture to a window switch action.

    For example, swipe_left -> previous window, swipe_right -> next window.
    This cycles through available windows (excluding Ankita windows).
    """
    try:
        from ankita.memory.memory_manager import get_pref
    except Exception:
        # If memory isn't available, continue with defaults
        def get_pref(k, d=None):
            return d

    enabled = get_pref('features.window_switch.enabled', True)
    if not enabled:
        return {'status': 'unavailable', 'matched_window': None, 'message': 'feature disabled by preference'}

    try:
        import pygetwindow as gw
    except Exception as e:
        return {'status': 'unavailable', 'matched_window': None, 'message': f'cannot enumerate windows: {e}'}

    titles = [t for t in gw.getAllTitles() if t and not t.startswith('Ankita')]
    if len(titles) < 1:
        return {'status': 'fail', 'matched_window': None, 'message': 'no other windows found'}

    # Determine active window index
    try:
        active = gw.getActiveWindow()
        current_title = active.title if active else None
    except Exception:
        current_title = None

    current_idx = -1
    if current_title:
        for i, title in enumerate(titles):
            if current_title in title:
                current_idx = i
                break

    if gesture == 'swipe_left':
        target_idx = (current_idx - 1) % len(titles)
    elif gesture == 'swipe_right':
        target_idx = (current_idx + 1) % len(titles)
    else:
        return {'status': 'fail', 'matched_window': None, 'message': f'unknown gesture: {gesture}'}

    target_title = titles[target_idx]
    return handle_window_switch(target_title, from_gesture=True)


def handle_window_switch(query: str, from_gesture: bool = False) -> dict:
    """Attempt to switch to a window matching `query`.

    Returns: {status, matched_window, message}
    status: 'success' | 'fail' | 'unavailable'
    """
    try:
        from ankita.memory.memory_manager import get_pref
    except Exception:
        def get_pref(k, d=None):
            return d

    enabled = get_pref('features.window_switch.enabled', True)
    if not enabled:
        return {'status': 'unavailable', 'matched_window': None, 'message': 'feature disabled by preference'}

    q = (query or '').strip().lower()
    if not q:
        return {'status': 'fail', 'matched_window': None, 'message': 'empty query'}

    # If user explicitly asked for gesture mode, and we're not already inside gesture
    if not from_gesture and ('gesture' in q or 'hand' in q or 'wave' in q):
        try:
            from .gestures import run_gesture_mode
        except Exception as e:
            return {'status': 'unavailable', 'matched_window': None, 'message': f'gesture module unavailable: {e}'}

        gesture_res = run_gesture_mode()
        if gesture_res.get('status') == 'success' and 'gesture' in gesture_res:
            gesture_switch_res = handle_gesture_switch(gesture_res['gesture'])
            _record_episode(query, gesture_switch_res.get('matched_window'), gesture_switch_res.get('status', 'fail'))
            return gesture_switch_res
        else:
            _record_episode(query, None, gesture_res.get('status', 'fail'))
            return {'status': gesture_res.get('status', 'fail'), 'matched_window': None, 'message': f'gesture result: {gesture_res}'}

    # Title-based matching
    try:
        import pygetwindow as gw
    except Exception as e:
        return {'status': 'unavailable', 'matched_window': None, 'message': f'pygetwindow unavailable: {e}'}

    try:
        titles = [t for t in gw.getAllTitles() if t]
    except Exception as e:
        return {'status': 'unavailable', 'matched_window': None, 'message': f'failed to enumerate windows: {e}'}

    # simple substring match
    match = None
    for t in titles:
        if q in t.lower():
            match = t
            break

    # token fallback
    if not match:
        tokens = q.split()
        best = None
        best_score = 0
        for t in titles:
            low = t.lower()
            score = sum(1 for tok in tokens if tok and tok in low)
            if score > best_score:
                best_score = score
                best = t
        if best_score > 0:
            match = best

    if not match:
        _record_episode(query, None, 'fail')
        return {'status': 'fail', 'matched_window': None, 'message': 'no matching window title found'}

    # Try to bring the matched window to foreground
    message = ''
    status = 'fail'
    try:
        wins = gw.getWindowsWithTitle(match)
        if wins:
            w = wins[0]
            # 1) Try pygetwindow activate
            try:
                w.activate()
                message = f'Activated "{match}" via pygetwindow.activate'
                status = 'success'
                logger.info('pygetwindow.activate succeeded for title: %s', match)
            except Exception as e_activate:
                logger.warning('pygetwindow.activate failed for %s: %s', match, e_activate)
                # 2) Try win32 methods with fallbacks
                try:
                    import win32gui
                    import win32con

                    hwnd = getattr(w, '_hWnd', None)
                    if not hwnd:
                        hwnd = win32gui.FindWindow(None, match)

                    if not hwnd:
                        message = 'could not obtain hwnd for window'
                        logger.error('could not obtain hwnd for title: %s', match)
                    else:
                        try:
                            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                            win32gui.SetForegroundWindow(hwnd)
                            try:
                                win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
                            except Exception:
                                pass
                            message = f'Activated "{match}" via win32 (maximized)'
                            status = 'success'
                            logger.info('win32 ShowWindow/SetForeground succeeded and maximized for hwnd %s (title: %s)', hwnd, match)
                        except Exception as e_win:
                            logger.warning('win32 Show/SetForeground failed for hwnd %s: %s', hwnd, e_win)
                            # AttachThreadInput fallback
                            try:
                                import ctypes
                                user32 = ctypes.windll.user32
                                kernel32 = ctypes.windll.kernel32
                                fg = win32gui.GetForegroundWindow()
                                if fg:
                                    fg_thread = user32.GetWindowThreadProcessId(fg, None)
                                else:
                                    fg_thread = 0
                                cur_thread = kernel32.GetCurrentThreadId()
                                user32.AttachThreadInput(cur_thread, fg_thread, True)
                                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                                win32gui.SetForegroundWindow(hwnd)
                                user32.AttachThreadInput(cur_thread, fg_thread, False)
                                try:
                                    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
                                except Exception:
                                    pass
                                message = f'Activated "{match}" via win32 (attach-thread fallback)'
                                status = 'success'
                                logger.info('AttachThreadInput fallback succeeded for hwnd %s (title: %s)', hwnd, match)
                            except Exception as e:
                                message = f'focus attempt failed: {e}'
                                logger.error('AttachThreadInput fallback failed for hwnd %s: %s', hwnd, e)
                except Exception as e:
                    message = f'focus attempt failed: {e}'
                    logger.error('win32 fallback import/operation failed for %s: %s', match, e)
        else:
            message = 'no window object found for matched title'
    except Exception as e:
        message = f'error while focusing: {e}'

    _record_episode(query, match if status == 'success' else None, status)
    return {'status': status, 'matched_window': match if status == 'success' else None, 'message': message}
    if current_title:
        for i, title in enumerate(titles):
            if current_title in title:
                current_idx = i
                break

    # Determine target window based on gesture
    if gesture == 'swipe_left':
        # Switch to previous window
        target_idx = (current_idx - 1) % len(titles)
    elif gesture == 'swipe_right':
        # Switch to next window
        target_idx = (current_idx + 1) % len(titles)
    else:
        return {'status': 'fail', 'matched_window': None, 'message': f'unknown gesture: {gesture}'}

    target_title = titles[target_idx]
    return handle_window_switch(target_title, from_gesture=True)


def handle_window_switch(query: str, from_gesture: bool = False) -> dict:
    """Attempt to switch to a window matching `query`.

    Returns: {status, matched_window, message}
    status: 'success' | 'fail' | 'unavailable'
    """
    from ankita.memory.memory_manager import get_pref

    enabled = get_pref('features.window_switch.enabled', True)
    if not enabled:
        return {'status': 'unavailable', 'matched_window': None, 'message': 'feature disabled by preference'}

    q = (query or '').strip().lower()
    if not q:
        return {'status': 'fail', 'matched_window': None, 'message': 'empty query'}

    # If user requested gesture mode explicitly (query contains 'gesture' or 'hand')
    # But don't do this if we're already in gesture mode to avoid recursion
    if not from_gesture and ('gesture' in q or 'hand' in q or 'wave' in q):
        try:
            from .gestures import run_gesture_mode
        except Exception as e:
            return {'status': 'unavailable', 'matched_window': None, 'message': f'gesture module unavailable: {e}'}

        gesture_res = run_gesture_mode()
        if gesture_res.get('status') == 'success' and 'gesture' in gesture_res:
            # If gesture detected, perform the switch
            gesture_switch_res = handle_gesture_switch(gesture_res['gesture'])
            _record_episode(query, gesture_switch_res.get('matched_window'), gesture_switch_res.get('status', 'fail'))
            return gesture_switch_res
        else:
            # No gesture detected or error
            _record_episode(query, None, gesture_res.get('status', 'fail'))
            return {'status': gesture_res.get('status', 'fail'), 'matched_window': None, 'message': f'gesture result: {gesture_res}'}

    # Try title-based matching via pygetwindow (lightweight)
    try:
        import pygetwindow as gw
    except Exception as e:
        return {'status': 'unavailable', 'matched_window': None, 'message': f'pygetwindow unavailable: {e}'}

    try:
        titles = [t for t in gw.getAllTitles() if t]
    except Exception as e:
        return {'status': 'unavailable', 'matched_window': None, 'message': f'failed to enumerate windows: {e}'}

    # 1) simple substring match
    match = None
    for t in titles:
        if q in t.lower():
            match = t
            break

    # 2) token-based fallback
    if not match:
        tokens = q.split()
        best = None
        best_score = 0
        for t in titles:
            low = t.lower()
            score = sum(1 for tok in tokens if tok and tok in low)
            if score > best_score:
                best_score = score
                best = t
        if best_score > 0:
            match = best

    if not match:
        _record_episode(query, None, 'fail')
        return {'status': 'fail', 'matched_window': None, 'message': 'no matching window title found'}

    # Try to bring the matched window to foreground
    message = ''
    status = 'fail'
    try:
        wins = gw.getWindowsWithTitle(match)
        if wins:
            w = wins[0]
            # 1) Try pygetwindow activate
            try:
                w.activate()
                message = f'Activated "{match}"'
                status = 'success'
            except Exception:
                # 2) Try win32 methods with a couple fallbacks to work around foreground lock
                try:
                    import win32gui
                    import win32con
                    import time

                    hwnd = getattr(w, '_hWnd', None)
                    if not hwnd:
                        # try finding by title
                        hwnd = win32gui.FindWindow(None, match)

                    if not hwnd:
                        message = 'could not obtain hwnd for window'
                    else:
                        try:
                            # Restore and bring to foreground
                            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                            win32gui.SetForegroundWindow(hwnd)
                            # Ensure window is maximized (so it launches full-screen like requested)
                            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
                            message = f'Activated "{match}" via win32'
                            status = 'success'
                        except Exception:
                            # Try AttachThreadInput trick if SetForegroundWindow fails
                            try:
                                import ctypes
                                user32 = ctypes.windll.user32
                                kernel32 = ctypes.windll.kernel32
                                fg = win32gui.GetForegroundWindow()
                                if fg:
                                    fg_thread = user32.GetWindowThreadProcessId(fg, None)
                                else:
                                    fg_thread = 0
                                cur_thread = kernel32.GetCurrentThreadId()
                                # Attach and set foreground
                                user32.AttachThreadInput(cur_thread, fg_thread, True)
                                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                                win32gui.SetForegroundWindow(hwnd)
                                user32.AttachThreadInput(cur_thread, fg_thread, False)
                                message = f'Activated "{match}" via win32 (attach-thread fallback)'
                                status = 'success'
                            except Exception as e:
                                message = f'focus attempt failed: {e}'
                except Exception as e:
                    message = f'focus attempt failed: {e}'
        else:
            message = 'no window object found for matched title'
    except Exception as e:
        message = f'error while focusing: {e}'

    _record_episode(query, match if status == 'success' else None, status)
    return {'status': status, 'matched_window': match if status == 'success' else None, 'message': message}
