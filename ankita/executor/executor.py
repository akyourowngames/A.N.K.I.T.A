import importlib
import json
import time

with open("registry/tools.json") as f:
    TOOL_REGISTRY = json.load(f)

def execute(plan):
    for step in plan["steps"]:
        tool_name = step["tool"]
        args = step.get("args", {})
        retries = step.get("retry", 1)
        timeout = step.get("timeout", None)

        tool_path = TOOL_REGISTRY[tool_name]
        module = importlib.import_module(tool_path)

        attempt = 0
        while attempt < retries:
            start = time.time()
            try:
                result = module.run(**args)

                if timeout is not None and (time.time() - start) > timeout:
                    attempt += 1
                    time.sleep(0.3)
                    continue

                if result.get("status") == "success":
                    break
            except Exception:
                if timeout is not None and (time.time() - start) > timeout:
                    attempt += 1
                    time.sleep(0.3)
                    continue

            attempt += 1
            time.sleep(0.3)
        else:
            raise RuntimeError(f"Tool failed: {tool_name}")
