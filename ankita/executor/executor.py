import importlib
import json
import time

with open("registry/tools.json") as f:
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
    
    results = []
    
    for step in plan["steps"]:
        tool_name = step["tool"]
        args = step.get("args", {})
        retries = step.get("retry", 1)
        timeout = step.get("timeout", None)

        tool_path = TOOL_REGISTRY[tool_name]
        module = importlib.import_module(tool_path)

        attempt = 0
        result = None
        while attempt < retries:
            start = time.time()
            try:
                result = module.run(**args)

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
