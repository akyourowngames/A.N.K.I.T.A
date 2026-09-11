"""Diagnose structured output without ingesting or printing personal sources."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memory import llm

client = llm.chat_completion
def trace_completion(*args, **kwargs):
    result = client(*args, **kwargs)
    raw = result.raw or {}
    choices = raw.get("choices") or [{}]
    print("Completion metadata:", {"chars": len(result.content), "completion_tokens": result.usage.completion_tokens,
          "finish_reason": choices[0].get("finish_reason"), "status": raw.get("status")}, flush=True)
    return result
llm.chat_completion = trace_completion

print("Configured memory model:", llm._memory_model(), flush=True)
print(llm.chat_json("Return exactly this JSON object: " + json.dumps({"entities": [0, 1], "relations": [0]}), max_tokens=1200), flush=True)
if "--profile" in sys.argv:
    from knowledge import extraction, storage, reasoning
    if "--auto" in sys.argv:
        import os
        os.environ["ZUMBA_KNOWLEDGE_MODEL"] = "stepfun/step-3.7-flash:free"
    original = llm.chat_json
    def traced(*args, **kwargs):
        result = original(*args, **kwargs)
        print("Response shape:", {k: type(v).__name__ for k, v in result.items()} if isinstance(result, dict) else type(result).__name__, flush=True)
        return result
    llm.chat_json = traced
    with storage.connect() as con:
        source = con.execute("SELECT content FROM documents WHERE kind='profile' ORDER BY created_at DESC LIMIT 1").fetchone()
    entities, edges, rejected = extraction.extract_graph(bytes(source[0]).decode(), "profile")
    print("Verified profile counts:", len(entities), len(edges), rejected, flush=True)
