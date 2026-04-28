import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("J.A.R.V.I.S")


@dataclass
class SystemControlResult:
    ok: bool
    message: str


class SystemControl:
    APP_ALIASES = {
        "chrome": ("chrome", "chrome"),
        "google chrome": ("chrome", "chrome"),
        "edge": ("msedge", "msedge"),
        "microsoft edge": ("msedge", "msedge"),
        "firefox": ("firefox", "firefox"),
        "vscode": ("code", "Code"),
        "vs code": ("code", "Code"),
        "visual studio code": ("code", "Code"),
        "notepad": ("notepad", "notepad"),
        "calculator": ("calc", "CalculatorApp"),
        "calc": ("calc", "CalculatorApp"),
        "terminal": ("wt", "WindowsTerminal"),
        "powershell": ("powershell", "powershell"),
        "cmd": ("cmd", "cmd"),
        "spotify": ("spotify", "Spotify"),
        "settings": ("ms-settings:", "SystemSettings"),
        "paint": ("mspaint", "mspaint"),
        "explorer": ("explorer", "explorer"),
        "file explorer": ("explorer", "explorer"),
        "task manager": ("taskmgr", "Taskmgr"),
    }

    _SAFE_APP_RE = re.compile(r"^[a-zA-Z0-9 ._:+-]{1,80}$")

    @classmethod
    def is_known_app(cls, app_name: str) -> bool:
        cleaned = cls.clean_app_name(app_name).lower()
        return cleaned in cls.APP_ALIASES

    @classmethod
    def clean_app_name(cls, app_name: str) -> str:
        cleaned = (app_name or "").strip().strip(".!?")
        return re.sub(r"^(?:the\s+)?app\s+", "", cleaned, flags=re.I).strip()

    def open_app(self, app_name: str) -> SystemControlResult:
        name = self.clean_app_name(app_name)
        if not self._is_safe_app_name(name):
            return SystemControlResult(False, "I couldn't open that app because the app name looked unsafe.")

        command, _ = self.APP_ALIASES.get(name.lower(), (name, name))

        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", "Start-Process", command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
            logger.info("[SYSTEM] Opened app: %s -> %s", app_name, command)
            return SystemControlResult(True, f"Opened {app_name.strip() or command}.")
        except Exception as exc:
            logger.warning("[SYSTEM] Failed to open app %s: %s", app_name, exc)
            return SystemControlResult(False, f"I couldn't open {app_name}.")

    def close_app(self, app_name: str) -> SystemControlResult:
        name = self.clean_app_name(app_name)
        if not self._is_safe_app_name(name):
            return SystemControlResult(False, "I couldn't close that app because the app name looked unsafe.")

        _, process_name = self.APP_ALIASES.get(name.lower(), (name, name))
        process_name = process_name.replace(".exe", "")
        target = process_name.replace("'", "''")
        script = f"""
$target = ('{target}' -replace '\\.exe$', '').Trim()
$targetLower = $target.ToLowerInvariant()
$matches = Get-Process -ErrorAction SilentlyContinue | Where-Object {{
    $processLower = $_.ProcessName.ToLowerInvariant()
    $processLower -eq $targetLower -or
    $processLower.Contains($targetLower)
}}
if (-not $matches) {{ exit 3 }}
$matches | Stop-Process -Force -ErrorAction Stop
"""

        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=8,
                shell=False,
            )
            if completed.returncode == 0:
                logger.info("[SYSTEM] Closed app: %s -> %s", app_name, process_name)
                return SystemControlResult(True, f"Closed {app_name}.")

            logger.warning("[SYSTEM] Close app failed %s: %s", app_name, completed.stderr[:200])
            return SystemControlResult(False, f"I couldn't find {app_name} running.")
        except Exception as exc:
            logger.warning("[SYSTEM] Failed to close app %s: %s", app_name, exc)
            return SystemControlResult(False, f"I couldn't close {app_name}.")

    def set_volume(self, level: int) -> SystemControlResult:
        level = max(0, min(100, int(level)))
        script = (
            "$obj = New-Object -ComObject WScript.Shell; "
            "$obj.SendKeys([char]173); Start-Sleep -Milliseconds 80; "
            "1..50 | ForEach-Object { $obj.SendKeys([char]174); Start-Sleep -Milliseconds 5 }; "
            f"1..{level // 2} | ForEach-Object {{ $obj.SendKeys([char]175); Start-Sleep -Milliseconds 5 }}"
        )
        return self._run_powershell_control(script, f"Set volume to {level}%.")

    def volume_up(self, steps: int = 5) -> SystemControlResult:
        steps = max(1, min(20, int(steps)))
        script = f"$obj = New-Object -ComObject WScript.Shell; 1..{steps} | ForEach-Object {{ $obj.SendKeys([char]175); Start-Sleep -Milliseconds 15 }}"
        return self._run_powershell_control(script, "Turned the volume up.")

    def volume_down(self, steps: int = 5) -> SystemControlResult:
        steps = max(1, min(20, int(steps)))
        script = f"$obj = New-Object -ComObject WScript.Shell; 1..{steps} | ForEach-Object {{ $obj.SendKeys([char]174); Start-Sleep -Milliseconds 15 }}"
        return self._run_powershell_control(script, "Turned the volume down.")

    def mute_volume(self) -> SystemControlResult:
        script = "$obj = New-Object -ComObject WScript.Shell; $obj.SendKeys([char]173)"
        return self._run_powershell_control(script, "Toggled mute.")

    def set_brightness(self, level: int) -> SystemControlResult:
        level = max(0, min(100, int(level)))
        script = (
            "$m = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods -ErrorAction Stop; "
            f"$m.WmiSetBrightness(1, {level})"
        )
        return self._run_powershell_control(script, f"Set brightness to {level}%.")

    def brightness_up(self, amount: int = 10) -> SystemControlResult:
        return self._change_brightness(abs(int(amount)))

    def brightness_down(self, amount: int = 10) -> SystemControlResult:
        return self._change_brightness(-abs(int(amount)))

    def lock_screen(self) -> SystemControlResult:
        try:
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return SystemControlResult(True, "Locked the screen.")
        except Exception as exc:
            logger.warning("[SYSTEM] Failed to lock screen: %s", exc)
            return SystemControlResult(False, "I couldn't lock the screen.")

    def _is_safe_app_name(self, name: str) -> bool:
        return bool(name and self._SAFE_APP_RE.match(name))

    def _change_brightness(self, delta: int) -> SystemControlResult:
        script = (
            "$b = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness -ErrorAction Stop | Select-Object -First 1; "
            "$m = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods -ErrorAction Stop | Select-Object -First 1; "
            f"$level = [Math]::Max(0, [Math]::Min(100, $b.CurrentBrightness + ({delta}))); "
            "$m.WmiSetBrightness(1, $level)"
        )
        message = "Increased brightness." if delta > 0 else "Decreased brightness."
        return self._run_powershell_control(script, message)

    def _run_powershell_control(self, script: str, success_message: str) -> SystemControlResult:
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
            if completed.returncode == 0:
                logger.info("[SYSTEM] %s", success_message)
                return SystemControlResult(True, success_message)

            logger.warning("[SYSTEM] Control failed: %s", completed.stderr[:200])
            return SystemControlResult(False, "That system control is not available on this device.")
        except Exception as exc:
            logger.warning("[SYSTEM] Control error: %s", exc)
            return SystemControlResult(False, "That system control failed.")


def parse_percent(text: Optional[str], default: int) -> int:
    match = re.search(r"\d{1,3}", text or "")
    if not match:
        return default
    return max(0, min(100, int(match.group(0))))
