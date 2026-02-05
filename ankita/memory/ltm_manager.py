import json
import os
from datetime import datetime


_MEMORY_DIR = os.path.dirname(__file__)
_LTM_PATH = os.path.join(_MEMORY_DIR, "ltm.json")


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_ltm() -> dict:
    return _load_json(
        _LTM_PATH,
        {
            "preferences": {},
            "corrections": {},
            "habits": [],
            "habit_stats": {},
            "suggestion_history": {},
            "stats": {},
            "meta": {"version": 1},
        },
    )


def save_ltm(ltm: dict) -> None:
    _save_json(_LTM_PATH, ltm)


def _ensure_schema(ltm: dict) -> dict:
    if not isinstance(ltm, dict):
        ltm = {}
    ltm.setdefault("preferences", {})
    ltm.setdefault("corrections", {})
    ltm.setdefault("habits", [])
    ltm.setdefault("habit_stats", {})
    ltm.setdefault("suggestion_history", {})
    ltm.setdefault("stats", {})
    ltm.setdefault("meta", {"version": 1})
    return ltm


def _today_key() -> str:
    return datetime.now().date().isoformat()


def was_suggested_today(suggestion_key: str) -> bool:
    ltm = _ensure_schema(load_ltm())
    sh = ltm.get("suggestion_history", {})
    if not isinstance(sh, dict):
        return False
    today = sh.get(_today_key(), {})
    if not isinstance(today, dict):
        return False
    return str(suggestion_key) in today


def mark_suggested_today(suggestion_key: str, payload: dict | None = None) -> None:
    ltm = _ensure_schema(load_ltm())
    sh = ltm.setdefault("suggestion_history", {})
    today_k = _today_key()
    today = sh.get(today_k)
    if not isinstance(today, dict):
        today = {}
        sh[today_k] = today

    entry = {"time": datetime.now().isoformat(), "status": "shown"}
    if isinstance(payload, dict):
        entry.update(payload)
    today[str(suggestion_key)] = entry
    save_ltm(ltm)


def mark_suggestion_dismissed_today(suggestion_key: str) -> None:
    mark_suggested_today(str(suggestion_key), {"status": "dismissed"})


def get_preference(key: str, default=None):
    ltm = load_ltm()
    entry = ltm.get("preferences", {}).get(key)
    if not isinstance(entry, dict):
        return default
    return entry.get("value", default)


def get_preference_confidence(key: str) -> float:
    ltm = load_ltm()
    entry = ltm.get("preferences", {}).get(key)
    if not isinstance(entry, dict):
        return 0.0
    try:
        return float(entry.get("confidence", 0.0))
    except Exception:
        return 0.0


def set_correction(key: str, value: str) -> None:
    ltm = load_ltm()
    ltm.setdefault("corrections", {})[key] = {
        "value": value,
        "updated": datetime.now().isoformat(),
    }
    save_ltm(ltm)


def get_correction(key: str, default=None):
    ltm = load_ltm()
    entry = ltm.get("corrections", {}).get(key)
    if isinstance(entry, dict):
        return entry.get("value", default)
    return default


def _bump_stat(stat_key: str) -> int:
    ltm = load_ltm()
    stats = ltm.setdefault("stats", {})
    n = int(stats.get(stat_key, 0) or 0) + 1
    stats[stat_key] = n
    save_ltm(ltm)
    return n


def record_preference_observation(key: str, value: str) -> dict:
    ltm = _ensure_schema(load_ltm())
    prefs = ltm.setdefault("preferences", {})

    entry = prefs.get(key)
    if not isinstance(entry, dict) or entry.get("value") != value:
        entry = {
            "value": value,
            "count": 0,
            "confidence": 0.0,
            "updated": datetime.now().isoformat(),
        }

    entry["count"] = int(entry.get("count", 0) or 0) + 1

    # Confidence ramp: 1->0.55, 2->0.65, 3->0.75, 4->0.85, 5->0.92 ... cap 0.95
    c = entry["count"]
    confidence = min(0.45 + 0.10 * c, 0.95)
    entry["confidence"] = round(confidence, 2)
    entry["updated"] = datetime.now().isoformat()

    prefs[key] = entry
    save_ltm(ltm)
    return entry


def should_write_memory(entry: dict, min_repeats: int = 3, min_confidence: float = 0.75) -> bool:
    if not isinstance(entry, dict):
        return False
    try:
        return int(entry.get("count", 0) or 0) >= min_repeats and float(entry.get("confidence", 0.0) or 0.0) >= min_confidence
    except Exception:
        return False


def _habit_key(trigger: str, action: str, target: str) -> str:
    return f"{trigger}|{action}|{target}".lower()


def _upsert_habit(trigger: str, action: str, target: str, count: int, confidence: float) -> None:
    ltm = _ensure_schema(load_ltm())
    key = _habit_key(trigger, action, target)

    habits = ltm.setdefault("habits", [])
    found = None
    for h in habits:
        if isinstance(h, dict) and h.get("key") == key:
            found = h
            break

    payload = {
        "key": key,
        "trigger": trigger,
        "action": action,
        "target": target,
        "count": int(count),
        "confidence": round(float(confidence), 2),
        "updated": datetime.now().isoformat(),
    }

    if found is None:
        habits.append(payload)
    else:
        found.update(payload)

    save_ltm(ltm)


def observe_time_habit(intent: str, entities: dict) -> None:
    if intent not in ("system.app.open", "system.app.focus"):
        return

    app = (entities or {}).get("app")
    if not app:
        return

    app_l = str(app).strip().lower()
    if not app_l:
        return

    now = datetime.now()
    trigger = f"time:{now.strftime('%H:00')}"
    action = "open_app" if intent.endswith(".open") else "focus_app"
    target = app_l

    ltm = _ensure_schema(load_ltm())
    habit_stats = ltm.setdefault("habit_stats", {})
    k = _habit_key(trigger, action, target)
    n = int(habit_stats.get(k, 0) or 0) + 1
    habit_stats[k] = n
    save_ltm(ltm)

    confidence = min(0.45 + 0.10 * n, 0.95)
    if n >= 3 and confidence >= 0.75:
        _upsert_habit(trigger=trigger, action=action, target=target, count=n, confidence=confidence)


def get_habits() -> list[dict]:
    ltm = _ensure_schema(load_ltm())
    habits = ltm.get("habits", [])
    return habits if isinstance(habits, list) else []


def find_time_habits(hour: int | None = None) -> list[dict]:
    habits = get_habits()
    if hour is None:
        return [h for h in habits if isinstance(h, dict) and str(h.get("trigger", "")).startswith("time:")]
    hh = f"{int(hour):02d}:00"
    trig = f"time:{hh}"
    return [h for h in habits if isinstance(h, dict) and h.get("trigger") == trig]


def observe_success(intent: str, entities: dict, result: dict | None = None) -> None:
    if intent not in ("system.app.open", "system.app.focus"):
        return

    app = (entities or {}).get("app")
    if not app:
        return

    app_l = str(app).strip().lower()

    # Basic preference learning: browser choice
    if app_l in ("chrome", "google chrome", "msedge", "edge"):
        normalized = "chrome" if "chrome" in app_l else "edge"
        entry = record_preference_observation("preferred_browser", normalized)
        if should_write_memory(entry):
            _bump_stat("preferred_browser_committed")

    observe_time_habit(intent, entities)

