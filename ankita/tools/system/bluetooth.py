import subprocess


def _run_ps(cmd: str):
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
    )


def run(action: str = "", **kwargs):
    action = (action or "").strip().lower()

    if action == "on":
        r = _run_ps("Get-PnpDevice -Class Bluetooth | Enable-PnpDevice -Confirm:$false")
        if r.returncode == 0:
            return {"status": "success", "message": "Bluetooth turned on"}
        err = (r.stderr or "").strip()
        out = (r.stdout or "").strip()
        return {
            "status": "fail",
            "reason": "Failed to enable Bluetooth (may require running PowerShell as Administrator)",
            "error": err or out,
        }

    if action == "off":
        r = _run_ps("Get-PnpDevice -Class Bluetooth | Disable-PnpDevice -Confirm:$false")
        if r.returncode == 0:
            return {"status": "success", "message": "Bluetooth turned off"}
        err = (r.stderr or "").strip()
        out = (r.stdout or "").strip()
        return {
            "status": "fail",
            "reason": "Failed to disable Bluetooth (may require running PowerShell as Administrator)",
            "error": err or out,
        }

    if action in ("status", "get"):
        r = _run_ps("Get-PnpDevice -Class Bluetooth | Select-Object -First 5 | Format-Table -AutoSize")
        if r.returncode == 0:
            out = (r.stdout or "").strip()
            return {"status": "success", "message": "Bluetooth status", "data": {"output": out}}
        return {"status": "fail", "reason": "Failed to read Bluetooth status", "error": r.stderr.strip()}

    return {"status": "fail", "reason": "Unknown bluetooth action"}
