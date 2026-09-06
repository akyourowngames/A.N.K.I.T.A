"""God-mode shell tool: unrestricted, persistent command execution.

One long-lived ``powershell`` subprocess per process (state like cwd and env
vars persists across calls), exposed to the model as built-in tools and to
humans via ``/shell`` / ``python main.py shell``. No allowlists, no
blocklists, no approval prompts — safety is an audit log, not gates.

Conventions (match the rest of zumba):
- Errors use the ``ERROR:`` text prefix (see ``mcpclient/builtin.py``).
- Kill-switch: ``ZUMBA_NO_SHELL=1`` hides the tools entirely.
- Tunables: ``ZUMBA_SHELL_TIMEOUT`` (default 60s), ``ZUMBA_SHELL_MAX_OUTPUT``
  (default 8000 chars, head+tail truncation).
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

_DONE_PREFIX = "__ZUMBA_DONE__:"
_PWD_PREFIX = "__ZUMBA_PWD__:"


# ---- Unix -> PowerShell translation (Friday-pattern, hardened for flags) ----
# Lets the model speak bash; Windows still works. `ls -la` is the classic
# breaker: bare `ls -> Get-ChildItem` leaves `-la` behind, which Get-ChildItem
# rejects. So ls flags are mapped explicitly instead of passed through.
_UNIX_TO_PS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"^\s*cat(\s)"), "Get-Content", "\\1"),
    (re.compile(r"^\s*pwd\s*$"), "Get-Location", ""),
    (re.compile(r"^\s*grep(\s)"), "Select-String", "\\1"),
    (re.compile(r"^\s*head(\s)"), "Select-Object -First", "\\1"),
    (re.compile(r"^\s*tail(\s)"), "Select-Object -Last", "\\1"),
    (re.compile(r"^\s*wc(\s)"), "Measure-Object", "\\1"),
    (re.compile(r"^\s*mkdir\s+-p\s+"), "New-Item -ItemType Directory -Force ", ""),
    (re.compile(r"^\s*touch\s+"), "New-Item -ItemType File -Force ", ""),
    (re.compile(r"^\s*rm\s+-rf\s+"), "Remove-Item -Recurse -Force ", ""),
    (re.compile(r"^\s*rm(\s)"), "Remove-Item", "\\1"),
    (re.compile(r"^\s*cp(\s)"), "Copy-Item", "\\1"),
    (re.compile(r"^\s*mv(\s)"), "Move-Item", "\\1"),
    (re.compile(r"^\s*which(\s)"), "Get-Command", "\\1"),
    (re.compile(r"^\s*env\s*\|\s*grep\s+"), "Get-ChildItem env: | Select-String ", ""),
    (re.compile(r"^\s*df(\s)"), "Get-PSDrive", "\\1"),
    (re.compile(r"^\s*du(\s)"), "Get-ChildItem -Recurse | Measure-Object", "\\1"),
    (re.compile(r"^\s*diff(\s)"), "Compare-Object", "\\1"),
    (re.compile(r"^\s*ps\s*$"), "Get-Process", ""),
    (re.compile(r"^\s*clear\s*$"), "Clear-Host", ""),
]

_LS_FLAGS = {
    "-la": "-Force", "-al": "-Force", "-lla": "-Force",
    "-l": "", "-a": "-Force", "-lh": "", "-lah": "-Force",
}


def _translate_ls(cmd: str) -> str | None:
    m = re.match(r"^\s*ls\s*(.*)$", cmd)
    if not m:
        return None
    rest = (m.group(1) or "").strip()
    if not rest:
        return "Get-ChildItem"
    parts = rest.split()
    flags = [p for p in parts if p.startswith("-")]
    paths = [p for p in parts if not p.startswith("-")]
    ps_flags = " ".join(_LS_FLAGS.get(f, "") for f in flags).strip()
    ps_flags = re.sub(r"\s+", " ", ps_flags).strip()
    path = " ".join(paths).strip()
    out = "Get-ChildItem"
    if ps_flags:
        out += f" {ps_flags}"
    if path:
        out += f" {path}"
    return out


_PS_PREFIXES = ("powershell", "pwsh", "Get-", "Set-", "New-", "Remove-",
                "Invoke-", "Select-", "Where-", "ForEach-", "Test-",
                "Write-", "Import-", "Export-", "Start-", "Stop-",
                "Clear-", "Get-PS", "Compare-", "Measure-", "Copy-",
                "Move-", "Out-")

_WIN_CMDS = ("dir", "type", "copy", "del", "ren", "move", "mkdir", "rmdir",
             "cls", "echo", "cd", "chdir", "path", "set", "date", "time",
             "find", "findstr", "sort", "tasklist", "taskkill", "ipconfig",
             "ping", "tracert", "netstat", "systeminfo", "whoami", "hostname")


def translate_to_powershell(command: str) -> str:
    """Translate common Unix commands to PowerShell equivalents on Windows."""
    if sys.platform != "win32":
        return command
    stripped = (command or "").strip()
    if not stripped:
        return command
    if any(stripped.startswith(p) for p in _PS_PREFIXES):
        return command
    ls = _translate_ls(stripped)
    if ls is not None:
        return ls
    first = stripped.split()[0].lower().split("/")[-1].split("\\")[-1]
    args = stripped.split()[1:] if len(stripped.split()) > 1 else []
    has_unix_flags = any(a.startswith("-") and len(a) > 1 and a[1] in "prf" for a in args)
    if first in _WIN_CMDS and not has_unix_flags:
        return command
    # sleep 5 -> Start-Sleep -Seconds 5 ; export FOO=bar -> $env:FOO="bar"
    m = re.match(r"^\s*sleep\s+(\d+)\s*$", stripped)
    if m:
        return f"Start-Sleep -Seconds {m.group(1)}"
    m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", stripped)
    if m and "|" not in stripped and ";" not in stripped:
        return f'$env:{m.group(1)}="{m.group(2).strip().strip(chr(34)).strip(chr(39))}"'
    for pattern, replacement, suffix in _UNIX_TO_PS:
        if pattern.match(stripped):
            return pattern.sub(replacement + suffix, stripped, count=1)
    return command


def enabled() -> bool:
    return os.getenv("ZUMBA_NO_SHELL", "") != "1"


def default_timeout() -> float:
    try:
        return max(1.0, float(os.getenv("ZUMBA_SHELL_TIMEOUT", "60") or 60))
    except Exception:
        return 60.0


def max_output() -> int:
    try:
        return max(500, int(os.getenv("ZUMBA_SHELL_MAX_OUTPUT", "8000") or 8000))
    except Exception:
        return 8000


def _audit_log_path() -> str:
    try:
        from store import zumba_home

        return str(zumba_home() / "shell_audit.log")
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".zumba", "shell_audit.log")


def _audit(command: str, exit_code, duration_ms: int) -> None:
    try:
        path = _audit_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"{ts} exit={exit_code} {duration_ms}ms :: {command[:2000]}\n")
    except Exception:
        pass


def truncate_output(text: str, cap: int = 0) -> tuple[str, bool]:
    cap = cap or max_output()
    if len(text) <= cap:
        return text, False
    head = cap * 3 // 4
    tail = cap - head
    note = f"\n... [truncated {len(text) - cap} chars; showing head+tail] ...\n"
    return text[:head] + note + text[-tail:], True


class _Job:
    def __init__(self, cmd: str, cwd: str | None):
        self.id = uuid.uuid4().hex[:8]
        try:
            cmd = translate_to_powershell(cmd)
        except Exception:
            pass
        self.command = cmd
        self.started_at = time.time()
        self._buf: list[str] = []
        self._done = threading.Event()
        self.exit_code: int | None = None
        try:
            self._proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NoLogo", "-Command", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                cwd=cwd or None,
            )
        except Exception as exc:
            self._proc = None
            self._buf.append(f"ERROR: failed to start background job: {exc}")
            self._done.set()
            return
        threading.Thread(target=self._reap, daemon=True, name=f"zumba-shell-job-{self.id}").start()

    def _reap(self) -> None:
        try:
            out, _ = self._proc.communicate()
            if out:
                self._buf.append(out)
            self.exit_code = self._proc.returncode
        except Exception as exc:
            self._buf.append(f"ERROR: job reap failed: {exc}")
        finally:
            self._done.set()

    def status(self) -> dict:
        running = not self._done.is_set()
        return {
            "job_id": self.id,
            "command": self.command[:200],
            "running": running,
            "exit_code": self.exit_code,
            "elapsed_s": round(time.time() - self.started_at, 1),
        }

    def output(self) -> str:
        return "".join(self._buf)

    def kill(self) -> None:
        try:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.kill()
        except Exception:
            pass


class ShellSession:
    """Singleton persistent powershell session. Get via :func:`get_session`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._q: queue.Queue = queue.Queue()
        self.cwd = os.getcwd()
        self.jobs: dict[str, _Job] = {}

    # ---- lifecycle ----
    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        self._proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NoLogo", "-Command", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            bufsize=1,
        )
        threading.Thread(target=self._reader, args=(self._proc.stdout, "o"), daemon=True, name="zumba-shell-out").start()
        threading.Thread(target=self._reader, args=(self._proc.stderr, "e"), daemon=True, name="zumba-shell-err").start()
        self._send("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8")
        self._drain(seconds=1.0)

    def _reader(self, stream, tag: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                self._q.put((tag, line))
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _send(self, text: str) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(text + "\n")
        self._proc.stdin.flush()

    def _drain(self, seconds: float = 0.2) -> None:
        end = time.time() + seconds
        while time.time() < end:
            try:
                self._q.get(timeout=max(0.01, end - time.time()))
            except queue.Empty:
                break

    def close(self) -> None:
        proc, self._proc = self._proc, None
        try:
            if proc is not None and proc.poll() is None:
                proc.kill()
        except Exception:
            pass

    def _restart(self) -> None:
        self.close()
        self._drain(seconds=0.1)
        self.start()

    # ---- foreground ----
    def run(self, cmd: str, timeout_s: float = 0, cwd: str | None = None, run_in_background: bool = False) -> dict:
        """Run a command. Returns {exit_code, stdout, stderr, truncated,
        duration_ms, timed_out}."""
        try:
            cmd = translate_to_powershell(cmd)
        except Exception:
            pass
        if run_in_background:
            return self.run_background(cmd, cwd=cwd)
        timeout = timeout_s or default_timeout()
        started = time.time()
        with self._lock:
            self.start()
            assert self._proc is not None
            if cwd:
                try:
                    self._send(f"Set-Location -LiteralPath '{cwd}'")
                    self.cwd = cwd
                except Exception:
                    pass
            # Merge stderr into the stdout stream for this command so the
            # model sees errors inline, in order.
            self._send(f"$__ZUMBA_TMP_OUT = & {{ {cmd} }} 2>&1 | Out-String; $__ZUMBA_EXIT = $LASTEXITCODE; Write-Output $__ZUMBA_TMP_OUT")
            self._send(f'Write-Output "{_DONE_PREFIX}$__ZUMBA_EXIT"')
            self._send(f'Write-Output "{_PWD_PREFIX}$PWD"')
            out_lines: list[str] = []
            err_lines: list[str] = []
            exit_code: int | None = None
            new_cwd: str | None = None
            timed_out = False
            dead = False
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    tag, line = self._q.get(timeout=min(0.5, max(0.05, deadline - time.time())))
                except queue.Empty:
                    if self._proc is not None and self._proc.poll() is not None:
                        dead = True
                        break
                    continue
                text = line.rstrip("\n")
                if tag == "o" and text.startswith(_DONE_PREFIX):
                    try:
                        exit_code = int(text[len(_DONE_PREFIX):].strip().split()[0])
                    except Exception:
                        exit_code = 0
                    continue
                if tag == "o" and text.startswith(_PWD_PREFIX):
                    new_cwd = text[len(_PWD_PREFIX):].strip()
                    break
                (out_lines if tag == "o" else err_lines).append(line)
            else:
                timed_out = True
            if exit_code is None and not timed_out:
                # Done marker never arrived within budget — treat as timeout.
                try:
                    left = self._q.get(timeout=0.5)
                    (out_lines if left[0] == "o" else err_lines).append(left[1])
                except queue.Empty:
                    pass
                if exit_code is None:
                    timed_out = time.time() >= deadline
            if dead:
                partial = "".join(out_lines)
                ms = int((time.time() - started) * 1000)
                _audit(cmd, "session-died", ms)
                self._restart()
                text, trunc = truncate_output(
                    partial + "\nERROR: shell session ended (the command likely called 'exit'); session restarted.")
                return {"exit_code": None, "stdout": text, "stderr": "".join(err_lines),
                        "truncated": trunc, "duration_ms": ms, "timed_out": True}
            if timed_out:
                partial = "".join(out_lines)
                ms = int((time.time() - started) * 1000)
                _audit(cmd, "timeout", ms)
                self._restart()
                text, trunc = truncate_output(partial + "\nERROR: timed out after %.0fs; shell session restarted." % timeout)
                return {"exit_code": None, "stdout": text, "stderr": "".join(err_lines),
                        "truncated": trunc, "duration_ms": ms, "timed_out": True}
            if new_cwd:
                self.cwd = new_cwd
            # Brief drain for trailing stderr lines.
            end = time.time() + 0.2
            while time.time() < end:
                try:
                    tag, line = self._q.get(timeout=max(0.01, end - time.time()))
                    if not (tag == "o" and (line.startswith(_DONE_PREFIX) or line.startswith(_PWD_PREFIX))):
                        (out_lines if tag == "o" else err_lines).append(line)
                except queue.Empty:
                    break
            ms = int((time.time() - started) * 1000)
            _audit(cmd, exit_code, ms)
            text, trunc = truncate_output("".join(out_lines))
            return {"exit_code": exit_code if exit_code is not None else 0, "stdout": text,
                    "stderr": "".join(err_lines), "truncated": trunc, "duration_ms": ms, "timed_out": False}

    # ---- background ----
    def run_background(self, cmd: str, cwd: str | None = None) -> dict:
        job = _Job(cmd, cwd or self.cwd)
        self.jobs[job.id] = job
        _audit(cmd + "  [background]", "bg", 0)
        return {"exit_code": 0, "stdout": f"Started background job {job.id}. Poll with shell_jobs / shell_kill.",
                "stderr": "", "truncated": False, "duration_ms": 0, "timed_out": False, "job_id": job.id}

    def job_list(self) -> list[dict]:
        return [j.status() for j in self.jobs.values()]

    def job_output(self, job_id: str) -> str:
        job = self.jobs.get(job_id)
        if job is None:
            return f"ERROR: unknown job '{job_id}'."
        out, trunc = truncate_output(job.output() or "(no output yet)")
        state = "running" if job.status()["running"] else f"done exit={job.exit_code}"
        return f"[{job.id}] {state} :: {job.command[:200]}\n{out}" + (" [truncated]" if trunc else "")

    def job_kill(self, job_id: str) -> str:
        job = self.jobs.get(job_id)
        if job is None:
            return f"ERROR: unknown job '{job_id}'."
        job.kill()
        return f"Killed job {job_id}."


_session: ShellSession | None = None
_session_lock = threading.Lock()


def get_session() -> ShellSession:
    global _session
    with _session_lock:
        if _session is None:
            _session = ShellSession()
        return _session


def run(cmd: str, timeout_s: float = 0, cwd: str | None = None, run_in_background: bool = False) -> dict:
    return get_session().run(cmd, timeout_s=timeout_s, cwd=cwd, run_in_background=run_in_background)


def format_result(res: dict, cwd: str = "") -> str:
    """Render a run() dict as model-facing text with the ERROR: convention."""
    if res.get("timed_out"):
        return f"ERROR: {res.get('stdout', '')}"
    out = (res.get("stdout") or "").rstrip("\n")
    err = (res.get("stderr") or "").rstrip("\n")
    head = f"exit={res.get('exit_code')} in {res.get('duration_ms')}ms" + (f" cwd={cwd}" if cwd else "")
    body = out
    if err:
        body += ("\n" if body else "") + "[stderr]\n" + err
    if not body.strip():
        body = "(no output)"
    if res.get("truncated"):
        body += "\n[output truncated]"
    if (res.get("exit_code") or 0) != 0:
        return f"ERROR: shell {head}\n{body}"
    return f"{head}\n{body}"
