"""Adapter tool to run gesture mode for window switching.

This module provides a `run(args)` entrypoint compatible with the executor.
Args can include `mode` (default: 'headless') and optional `timeout_seconds`.
"""
import threading


def run(mode: str = "headless", timeout_seconds: int = 0) -> dict:
    """
    Run gesture mode for window switching.
    
    Args:
        mode: 'headless' (no UI window) or 'visible' (with UI window)
        timeout_seconds: How long to run (0 = until user quits in visible mode, or indefinite in headless)
    
    Returns:
        dict with status and message
    """
    headless = (mode != "visible")
    
    try:
        from features.window_switch.gestures import run_gesture_mode
    except Exception as e:
        return {'status': 'error', 'error': f'gesture module import failed: {e}'}

    # Run in background thread so Ankita doesn't block
    result = {"status": "running", "message": "Gesture mode started"}
    
    def _run_gesture():
        try:
            res = run_gesture_mode(timeout_seconds=timeout_seconds, headless=headless)
            # In headless mode with no timeout, this runs indefinitely
            # The result is not directly returned since we're in a thread
        except Exception as e:
            pass  # Silent fail in background thread
    
    # Start gesture mode in background
    bg_thread = threading.Thread(target=_run_gesture, daemon=True)
    bg_thread.start()
    
    if headless:
        return {
            'status': 'success', 
            'message': 'Gesture mode started in headless mode. Move your head left/right to switch windows. Gesture mode will run until you stop Ankita or restart.'
        }
    else:
        return {
            'status': 'success',
            'message': 'Gesture mode started with visible window. Press q in the window to quit.'
        }
