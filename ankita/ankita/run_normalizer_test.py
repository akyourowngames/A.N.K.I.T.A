import ankita_core

# Monkeypatch LLM functions to avoid external API calls during tests
try:
    from ankita.llm import llm_client as _llm
except Exception:
    _llm = None

def _mock_generate_response(context):
    if _llm:
        return _llm._TEMPLATES.get(context.get("intent", "unknown"), _llm._TEMPLATES["unknown"])
    return "(mock response)"

def _mock_ask_llm(text):
    return "(mocked LLM reply)"

ankita_core.generate_response = _mock_generate_response
ankita_core.ask_llm = _mock_ask_llm

from ankita_core import handle_text
# Prevent executing real tools (and external calls) during tests
def _mock_execute(plan):
    print(f"MOCK_EXECUTE: would run plan: {plan}")
    return {"status": "success", "results": [{"status": "success"}]}

ankita_core.execute = _mock_execute

from brain.entity_normalizer import normalize

def _assert_eq(label, got, expected):
    if got != expected:
        raise AssertionError(f"{label}: expected={expected!r}, got={got!r}")


direct_cases = [
    ("notepad.write_note", "write hi in notepad", {"content": "hi"}),
    ("notepad.write_note", "write physics notes", {"content": "physics notes"}),
    ("notepad.write_note", "save: hello, world! to notepad", {"content": "hello, world"}),
    ("notepad.write_note", "note - buy milk", {"content": "buy milk"}),
    ("notepad.write_note", "write    hello   in   notepad", {"content": "hello"}),
    ("notepad.write_note", "notepad write meeting agenda", {"content": "meeting agenda"}),
    ("notepad.continue_note", "continue add more details", {"content": "more details"}),
    ("notepad.continue_note", "append: final point.", {"content": "final point"}),
    ("youtube.play", "play song on yt", {"query": "song"}),
    ("youtube.play", "play lofi beats on youtube", {"query": "lofi beats"}),
    ("youtube.play", "youtube play lofi", {"query": "lofi"}),
    ("youtube.play", "play: lo-fi, beats!", {"query": "lo-fi, beats"}),
    ("youtube.play", "play   on   youtube   ", {"query": ""}),
]

print("=== DIRECT NORMALIZER TESTS ===")
for intent, raw, expected in direct_cases:
    got = normalize(intent, {}, raw)
    _assert_eq(f"{intent}::{raw}", got, expected)
    print(f"PASS: {intent} | {raw!r} -> {got}")

tests = [
    "write hi in notepad",
    "play lofi beats on youtube",
    "continue note add more details",
    "WRITE HI IN NOTEPAD!!",
    "play song on yt",
    "notepad write meeting agenda",
    "append: final point.",
    "youtube play lofi",
    "continue note add more details",
    "continue that",
]

for t in tests:
    print("\n=== TEST INPUT ===")
    print(t)
    resp = handle_text(t)
    print("--- Response ---")
    print(resp)

print("\nALL TESTS PASSED")
