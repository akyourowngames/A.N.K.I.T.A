"""Bounded per-session summary cache; generation never holds up a new turn."""
from collections import OrderedDict
import threading
from . import context_budget

_sessions = OrderedDict()
_lock = threading.Lock()


def fit(messages, session_id):
    with _lock:
        state = _sessions.setdefault(session_id, {"summary": "", "covered": -1, "pending": False})
        _sessions.move_to_end(session_id)
        while len(_sessions) > 128:
            _sessions.popitem(last=False)
        cache = {"summary": state["summary"], "covered": state["covered"]}
    def summarize(dropped):
        with _lock:
            if not state["pending"]:
                state["pending"] = True
                def run():
                    try:
                        text = context_budget._default_summarizer(dropped)
                        with _lock:
                            state.update(summary=text, covered=len(dropped))
                    finally:
                        with _lock:
                            state["pending"] = False
                threading.Thread(target=run, daemon=True, name="zumba-summary").start()
        return state["summary"] or "Earlier turns remain saved in session history; their summary is being prepared."
    return context_budget.build_window(messages, model_limit=context_budget.get_context_limit(), cache=cache, summarizer=summarize)
