import subprocess
import time


APP_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "chromium": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "cmd": "cmd",
    "command prompt": "cmd",
    "powershell": "powershell",
    "terminal": "wt",
    "windows terminal": "wt",
    "vs code": "code",
    "vscode": "code",
    "code": "code",
}

APP_TITLES = {
    "chrome": ["chrome", "google chrome"],
    "msedge": ["edge", "microsoft edge"],
    "code": ["visual studio code", "vs code", "code"],
    "notepad": ["notepad"],
    "explorer": ["file explorer", "this pc", "explorer"],
    "wt": ["windows terminal", "terminal"],
    "cmd": ["command prompt", "cmd"],
    "powershell": ["powershell"],
}


def _resolve_app(app: str | None) -> str | None:
    if not app:
        return None
    a = (app or "").strip().lower()
    if not a:
        return None
    return APP_ALIASES.get(a, a)


def _start_app(app_cmd: str) -> None:
    subprocess.Popen(f'start "" "{app_cmd}"', shell=True)


def _close_active() -> None:
    try:
        import pyautogui

        pyautogui.hotkey("alt", "f4")
    except Exception:
        pass


def _taskkill(process_name: str, force: bool) -> subprocess.CompletedProcess:
    exe = process_name
    if not exe.lower().endswith(".exe"):
        exe = exe + ".exe"

    cmd = ["taskkill", "/IM", exe]
    if force:
        cmd.append("/F")

    return subprocess.run(cmd, capture_output=True, text=True, shell=False)


def _find_window_by_title_keywords(app_cmd: str) -> tuple[int, str] | None:
    """Return (hwnd, title) for a matching top-level window, else None."""
    try:
        import win32gui
    except Exception:
        return None

    keys = APP_TITLES.get(app_cmd.lower(), [app_cmd.lower()])
    matches: list[tuple[int, str]] = []

    def _enum_cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd) or ""
            t = title.lower().strip()
            if not t:
                return
            if any(k in t for k in keys):
                matches.append((hwnd, title))
        except Exception:
            return

    try:
        win32gui.EnumWindows(_enum_cb, None)
    except Exception:
        return None

    if not matches:
        return None

    # Prefer non-minimized windows.
    try:
        import win32gui

        for hwnd, title in matches:
            try:
                if not win32gui.IsIconic(hwnd):
                    return hwnd, title
            except Exception:
                continue
    except Exception:
        pass

    return matches[0]


def _focus_hwnd(hwnd: int) -> tuple[bool, str]:
    """Try hard to bring a window to foreground. Returns (ok, error_message)."""
    try:
        import win32api
        import win32con
        import win32gui
        import win32process
    except Exception as e:
        return False, f"Missing win32 libs: {e}"

    try:
        if not win32gui.IsWindow(hwnd):
            return False, "Invalid window handle"

        # Restore and show
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.BringWindowToTop(hwnd)

        # Foreground restrictions workaround
        fg = win32gui.GetForegroundWindow()
        cur_tid = win32api.GetCurrentThreadId()
        fg_tid, _ = win32process.GetWindowThreadProcessId(fg)
        tgt_tid, _ = win32process.GetWindowThreadProcessId(hwnd)

        attached_fg = False
        attached_tgt = False
        try:
            if fg_tid and fg_tid != cur_tid:
                win32process.AttachThreadInput(cur_tid, fg_tid, True)
                attached_fg = True
            if tgt_tid and tgt_tid != cur_tid:
                win32process.AttachThreadInput(cur_tid, tgt_tid, True)
                attached_tgt = True

            # Topmost toggle is a common reliable trick
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOPMOST,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
            )
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_NOTOPMOST,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
            )

            win32gui.SetForegroundWindow(hwnd)
            win32gui.SetActiveWindow(hwnd)
        finally:
            try:
                if attached_tgt:
                    win32process.AttachThreadInput(cur_tid, tgt_tid, False)
            except Exception:
                pass
            try:
                if attached_fg:
                    win32process.AttachThreadInput(cur_tid, fg_tid, False)
            except Exception:
                pass

        time.sleep(0.08)
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        return True, ""
    except Exception as e:
        return False, str(e)


def run(action: str = "", app: str | None = None, force: bool = False, **kwargs) -> dict:
    action = (action or "").strip().lower()
    resolved = _resolve_app(app)

    if action in ("focus", "switch", "switch_to"):
        if not resolved:
            return {"status": "fail", "reason": "Missing app name"}

        found = _find_window_by_title_keywords(resolved)
        if not found:
            return {"status": "fail", "reason": "Window not found", "app": app}

        hwnd, title = found
        ok, err = _focus_hwnd(hwnd)
        if ok:
            return {"status": "success", "message": f"Focused {app}", "window_title": title}
        return {"status": "fail", "reason": "Failed to focus window", "app": app, "window_title": title, "error": err}

    if action in ("open", "launch", "start"):
        if not resolved:
            return {"status": "fail", "reason": "Missing app name"}
        try:
            _start_app(resolved)
            return {"status": "success", "message": f"Opened {app}"}
        except Exception as e:
            return {"status": "fail", "reason": "Failed to open app", "error": str(e)}

    if action in ("close_active", "close_this"):
        _close_active()
        return {"status": "success", "message": "Closed active app"}

    if action in ("close", "kill"):
        if not resolved:
            return {"status": "fail", "reason": "Missing app name"}
        try:
            r = _taskkill(resolved, force=bool(force))
            out = (r.stdout or "").strip()
            err = (r.stderr or "").strip()

            if r.returncode == 0:
                mode = "force closed" if force else "closed"
                return {"status": "success", "message": f"{mode} {app}"}

            if not force:
                return {
                    "status": "fail",
                    "reason": "Failed to close app",
                    "error": err or out,
                    "hint": "Try 'force close <app>'",
                }

            return {"status": "fail", "reason": "Failed to force close app", "error": err or out}
        except Exception as e:
            return {"status": "fail", "reason": "Failed to close app", "error": str(e)}

    return {"status": "fail", "reason": "Unknown app action"}
