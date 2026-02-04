def run(action: str = "", value: int | None = None, step: int | None = None, **kwargs):
    action = (action or "").strip().lower()

    try:
        import screen_brightness_control as sbc

        if action in ("set",):
            if value is None:
                return {"status": "fail", "reason": "Missing brightness value"}
            v = max(0, min(int(value), 100))
            sbc.set_brightness(v)
            return {"status": "success", "message": f"Brightness set to {v}"}

        s = 10 if step is None else max(1, min(int(step), 100))
        curr = int(sbc.get_brightness(display=0)[0])

        if action in ("up",):
            v = min(curr + s, 100)
            sbc.set_brightness(v)
            return {"status": "success", "message": f"Brightness increased to {v}"}

        if action in ("down",):
            v = max(curr - s, 0)
            sbc.set_brightness(v)
            return {"status": "success", "message": f"Brightness decreased to {v}"}

        if action in ("status", "get"):
            return {"status": "success", "message": "Brightness status", "value": curr}

        return {"status": "fail", "reason": "Unknown brightness action"}

    except Exception as e:
        return {
            "status": "fail",
            "reason": "Brightness control unavailable. Install dependency: pip install screen-brightness-control",
            "error": str(e),
        }
