import importlib
import json
import time
import inspect


# Always resolve tools.json relative to this file's directory
import os
_dir = os.path.dirname(os.path.abspath(__file__))
tools_path = os.path.join(_dir, "..", "registry", "tools.json")
with open(tools_path, encoding="utf-8") as f:
    TOOL_REGISTRY = json.load(f)

def execute(plan):
    """
    Execute a plan and return the result.
    
    Returns:
        dict with 'status' and optional 'message'
    """
    # Handle message-only plans (no steps) - return silently, let LLM respond
    if "message" in plan:
        return {"status": "message", "message": plan["message"]}
    
    print(f"DEBUG: executor received plan -> {plan}")
    results = []
    
    for step in plan["steps"]:
        tool_name = step["tool"]
        args = step.get("args", {})
        retries = step.get("retry", 1)
        timeout = step.get("timeout", None)

        tool_path = TOOL_REGISTRY[tool_name]
        print(f"DEBUG: executing tool {tool_name} -> module {tool_path} with args {args}")
        module = importlib.import_module(tool_path)

        attempt = 0
        result = None
        while attempt < retries:
            start = time.time()
            try:
                run_fn = getattr(module, "run")
                sig = inspect.signature(run_fn)
                params = list(sig.parameters.values())

                # Support tools that define `run(args: dict)` (single positional arg)
                if (
                    len(params) == 1
                    and params[0].kind
                    in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                    and params[0].name == "args"
                ):
                    result = run_fn(args)
                else:
                    result = run_fn(**args)

                if timeout is not None and (time.time() - start) > timeout:
                    attempt += 1
                    time.sleep(0.3)
                    continue

                if result.get("status") == "success":
                    results.append(result)
                    break
            except Exception as e:
                result = {"status": "error", "error": str(e)}
                if timeout is not None and (time.time() - start) > timeout:
                    attempt += 1
                    time.sleep(0.3)
                    continue

            attempt += 1
            time.sleep(0.3)
        else:
            return {"status": "fail", "tool": tool_name, "last_result": result}
    
    return {"status": "success", "results": results}
