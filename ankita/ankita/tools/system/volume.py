def run(action: str = "", value: int | None = None, step: int | None = None, **kwargs):
    action = (action or "").strip().lower()

    try:
        from pycaw.pycaw import AudioUtilities

        device = AudioUtilities.GetSpeakers()
        # Newer pycaw exposes endpoint volume directly on the AudioDevice.
        # (Older examples used .Activate(...) which isn't present in this build.)
        vol = device.EndpointVolume

        if action in ("mute",):
            vol.SetMute(1, None)
            return {"status": "success", "message": "Volume muted"}

        if action in ("unmute",):
            vol.SetMute(0, None)
            return {"status": "success", "message": "Volume unmuted"}

        if action in ("set",):
            if value is None:
                return {"status": "fail", "reason": "Missing volume value"}
            v = max(0, min(int(value), 100)) / 100.0
            vol.SetMasterVolumeLevelScalar(v, None)
            return {"status": "success", "message": f"Volume set to {int(value)}"}

        s = 10 if step is None else max(1, min(int(step), 100))
        delta = s / 100.0
        curr = float(vol.GetMasterVolumeLevelScalar())

        if action in ("up",):
            vol.SetMasterVolumeLevelScalar(min(curr + delta, 1.0), None)
            return {"status": "success", "message": f"Volume increased by {s}"}

        if action in ("down",):
            vol.SetMasterVolumeLevelScalar(max(curr - delta, 0.0), None)
            return {"status": "success", "message": f"Volume decreased by {s}"}

        if action in ("status", "get"):
            return {"status": "success", "message": "Volume status", "value": int(round(curr * 100))}

        return {"status": "fail", "reason": "Unknown volume action"}

    except Exception as e:
        return {"status": "fail", "reason": "Volume control failed", "error": str(e)}
