from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PLATFORM = platform.system()
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


@dataclass(slots=True)
class OpenTargetResult:
    ok: bool
    target: str
    kind: str
    method: str
    opened: bool = False
    verified: bool = False
    process: dict[str, Any] | None = None
    matching_windows: list[dict[str, Any]] | None = None
    error: str = ""
    stdout: str = ""
    stderr: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["matching_windows"] = payload.get("matching_windows") or []
        return payload


def is_url_target(target: str) -> bool:
    parsed = urllib.parse.urlparse(str(target).strip())
    return parsed.scheme in {"http", "https", "file", "mailto", "ms-settings"}


def open_target(target: str | Path, *, wait_seconds: float = 1.5) -> OpenTargetResult:
    target_text = str(target)
    if is_url_target(target_text):
        kind = "url"
    else:
        path = Path(target_text)
        kind = "dir" if path.exists() and path.is_dir() else "file" if path.exists() and path.is_file() else "path"
    if PLATFORM == "Windows":
        return _open_windows(target_text, kind=kind, wait_seconds=wait_seconds)
    if PLATFORM == "Darwin":
        return _open_subprocess(["open", target_text], target_text, kind=kind, method="open", wait_seconds=wait_seconds)
    return _open_subprocess(["xdg-open", target_text], target_text, kind=kind, method="xdg-open", wait_seconds=wait_seconds)


def _open_subprocess(command: list[str], target: str, *, kind: str, method: str, wait_seconds: float) -> OpenTargetResult:
    try:
        proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(max(0.0, min(wait_seconds, 5.0)))
        running = proc.poll() is None
        return OpenTargetResult(
            ok=True,
            target=target,
            kind=kind,
            method=method,
            opened=True,
            verified=running,
            process={"pid": proc.pid, "running": running},
        )
    except Exception as exc:  # noqa: BLE001
        return OpenTargetResult(ok=False, target=target, kind=kind, method=method, error=str(exc))


def _open_windows(target: str, *, kind: str, wait_seconds: float) -> OpenTargetResult:
    wait_ms = int(max(100, min(wait_seconds, 10.0) * 1000))
    match_token = _match_token(target, kind)
    script = r'''
$ErrorActionPreference = "Stop"
$target = __TARGET__
$waitMs = __WAIT_MS__
$matchToken = __MATCH_TOKEN__
if ($null -eq $matchToken) { $matchToken = "" }
$matchToken = $matchToken.ToLowerInvariant()
$started = $null
$ok = $false
$errorText = ""
try {
    if (Test-Path -LiteralPath $target) {
        Invoke-Item -LiteralPath $target -ErrorAction Stop
    } else {
        $started = Start-Process -FilePath $target -PassThru -ErrorAction Stop
    }
    $ok = $true
    Start-Sleep -Milliseconds $waitMs
    if ($started -and -not $started.HasExited) {
        try {
            $shell = New-Object -ComObject WScript.Shell
            [void]$shell.AppActivate($started.Id)
        } catch {}
    }
} catch {
    $errorText = $_.Exception.Message
}
$windows = @(Get-Process | Where-Object { $_.MainWindowTitle } | Select-Object Id,ProcessName,MainWindowTitle)
$matches = @()
if ($matchToken) {
    $matches = @($windows | Where-Object {
        $_.MainWindowTitle.ToLowerInvariant().Contains($matchToken) -or
        $_.ProcessName.ToLowerInvariant().Contains($matchToken)
    })
}
$processPayload = $null
if ($started) {
    $processPayload = [pscustomobject]@{
        id = $started.Id
        process_name = $started.ProcessName
        has_exited = $started.HasExited
        main_window_title = $started.MainWindowTitle
    }
}
[pscustomobject]@{
    ok = $ok
    error = $errorText
    process = $processPayload
    matching_windows = $matches
} | ConvertTo-Json -Depth 5 -Compress
'''
    script = (
        script.replace("__TARGET__", _ps_single(target))
        .replace("__WAIT_MS__", str(wait_ms))
        .replace("__MATCH_TOKEN__", _ps_single(match_token))
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(10, int(wait_seconds) + 10),
    )
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode != 0:
        fallback = _open_windows_cmd_start(target, kind=kind, wait_seconds=wait_seconds)
        fallback.stdout = stdout
        fallback.stderr = stderr or fallback.stderr
        return fallback
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        payload = {}
    ok = bool(payload.get("ok"))
    process = payload.get("process") if isinstance(payload.get("process"), dict) else None
    matching_windows = payload.get("matching_windows", [])
    if isinstance(matching_windows, dict):
        matching_windows = [matching_windows]
    if not isinstance(matching_windows, list):
        matching_windows = []
    if not ok:
        fallback = _open_windows_cmd_start(target, kind=kind, wait_seconds=wait_seconds)
        if fallback.ok:
            return fallback
    verified = bool(process) or bool(matching_windows)
    result = OpenTargetResult(
        ok=ok,
        target=target,
        kind=kind,
        method="powershell Invoke-Item/Start-Process",
        opened=ok,
        verified=verified,
        process=process,
        matching_windows=matching_windows,
        error=str(payload.get("error", "")),
        stdout=stdout,
        stderr=stderr,
    )
    if result.ok and not result.verified and _is_image_path(target):
        fallback = _open_windows_image_fallback(target, wait_seconds=wait_seconds)
        if fallback.ok:
            fallback.method = f"{result.method} -> {fallback.method}"
            fallback.stdout = result.stdout
            fallback.stderr = result.stderr
            return fallback
    if result.ok and not result.verified and kind == "dir":
        fallback = _open_windows_folder_fallback(target, wait_seconds=wait_seconds)
        if fallback.ok:
            fallback.method = f"{result.method} -> {fallback.method}"
            fallback.stdout = result.stdout
            fallback.stderr = result.stderr
            return fallback
    return result


def _open_windows_cmd_start(target: str, *, kind: str, wait_seconds: float) -> OpenTargetResult:
    try:
        completed = subprocess.run(
            ["cmd", "/d", "/s", "/c", "start", "", target],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        time.sleep(max(0.0, min(wait_seconds, 5.0)))
        ok = completed.returncode == 0
        return OpenTargetResult(
            ok=ok,
            target=target,
            kind=kind,
            method="cmd start",
            opened=ok,
            verified=False,
            error="" if ok else completed.stderr.strip(),
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )
    except Exception as exc:  # noqa: BLE001
        return OpenTargetResult(ok=False, target=target, kind=kind, method="cmd start", error=str(exc))


def _open_windows_image_fallback(target: str, *, wait_seconds: float) -> OpenTargetResult:
    app = os.getenv("JAKATA_OPEN_IMAGE_APP", "mspaint.exe").strip()
    if not app:
        return OpenTargetResult(ok=False, target=target, kind="path", method="image fallback", error="image fallback disabled")
    try:
        proc = subprocess.Popen([app, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(max(0.0, min(wait_seconds, 5.0)))
        running = proc.poll() is None
        return OpenTargetResult(
            ok=True,
            target=target,
            kind="file",
            method=f"image fallback: {app}",
            opened=True,
            verified=running,
            process={"pid": proc.pid, "process_name": Path(app).stem, "running": running},
        )
    except Exception as exc:  # noqa: BLE001
        return OpenTargetResult(ok=False, target=target, kind="file", method=f"image fallback: {app}", error=str(exc))


def _open_windows_folder_fallback(target: str, *, wait_seconds: float) -> OpenTargetResult:
    try:
        proc = subprocess.Popen(["explorer.exe", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(max(0.0, min(wait_seconds, 5.0)))
        windows = _windows_matching_windows(_match_token(target, "path"))
        running = proc.poll() is None
        return OpenTargetResult(
            ok=True,
            target=target,
            kind="dir",
            method="folder fallback: explorer.exe",
            opened=True,
            verified=bool(windows) or running,
            process={"pid": proc.pid, "process_name": "explorer", "running": running},
            matching_windows=windows,
        )
    except Exception as exc:  # noqa: BLE001
        return OpenTargetResult(ok=False, target=target, kind="dir", method="folder fallback: explorer.exe", error=str(exc))


def _ps_single(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _is_image_path(target: str) -> bool:
    return Path(target).suffix.casefold() in _IMAGE_EXTENSIONS


def _windows_matching_windows(match_token: str) -> list[dict[str, Any]]:
    if not match_token:
        return []
    script = r'''
$matchToken = __MATCH_TOKEN__
$matchToken = $matchToken.ToLowerInvariant()
$matches = @(Get-Process | Where-Object {
    $_.MainWindowTitle -and (
        $_.MainWindowTitle.ToLowerInvariant().Contains($matchToken) -or
        $_.ProcessName.ToLowerInvariant().Contains($matchToken)
    )
} | Select-Object Id,ProcessName,MainWindowTitle)
$matches | ConvertTo-Json -Depth 4 -Compress
'''.replace("__MATCH_TOKEN__", _ps_single(match_token))
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return []
        payload = json.loads(completed.stdout)
    except Exception:
        return []
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _match_token(target: str, kind: str) -> str:
    if kind == "url":
        parsed = urllib.parse.urlparse(target)
        return (parsed.netloc or parsed.path).casefold()
    path = Path(target)
    return (path.name or path.stem).casefold()
