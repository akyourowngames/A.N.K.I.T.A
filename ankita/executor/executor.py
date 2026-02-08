"""
Executor - Executes plans and tracks all actions in memory.

Deep Memory Integration:
- All tool executions are automatically logged to memory
- Context is shared between tools via memory
- Tools can access previous tool results
- Suggestions flow based on tool usage patterns
"""

import importlib
import json
import time
import inspect
import os
from datetime import datetime

# Always resolve tools.json relative to this file's directory
_dir = os.path.dirname(os.path.abspath(__file__))
tools_path = os.path.join(_dir, "..", "registry", "tools.json")
with open(tools_path, encoding="utf-8") as f:
    TOOL_REGISTRY = json.load(f)


# ============== MEMORY INTEGRATION ==============

_memory = None

def _get_memory():
    """Get the shared memory instance (lazy load)."""
    global _memory
    if _memory is None:
        try:
            from memory.conversation_memory import get_conversation_memory
            _memory = get_conversation_memory()
        except ImportError:
            pass
    return _memory


def _extract_tool_category(tool_name: str) -> str:
    """Extract category from tool name (e.g., 'system.volume.up' -> 'system')."""
    parts = tool_name.split(".")
    return parts[0] if parts else "unknown"


def _generate_summary(tool_name: str, args: dict, result: dict) -> str:
    """Generate human-readable summary of tool execution."""
    category = _extract_tool_category(tool_name)
    action = tool_name.split(".")[-1] if "." in tool_name else tool_name
    
    # Build summary based on category
    if category == "youtube":
        if "query" in args:
            return f"YouTube: Played '{args['query']}'"
        return f"YouTube: {action.replace('_', ' ').title()}"
    
    elif category == "instagram":
        if "username" in args:
            return f"Instagram: {action} @{args['username']}"
        return f"Instagram: {action.replace('_', ' ').title()}"
    
    elif category == "whatsapp":
        contact = args.get("contact") or args.get("recipient", "contact")
        if action == "send":
            return f"WhatsApp: Sent message to {contact}"
        return f"WhatsApp: {action.replace('_', ' ').title()}"
        
    elif category == "gmail":
        to = args.get("to", "recipient")
        if action == "send":
            return f"Gmail: Sent email to {to}"
        return f"Gmail: {action.replace('_', ' ').title()}"

    elif category == "system":
        sub_category = tool_name.split(".")[1] if len(tool_name.split(".")) > 1 else ""
        if sub_category == "volume":
            return f"System: Volume {action}"
        elif sub_category == "brightness":
            return f"System: Brightness {action}"
        elif sub_category == "app":
            app = args.get("app", "application")
            return f"System: {action.title()} {app}"
        elif sub_category == "bluetooth":
            return f"System: Bluetooth {action}"
        elif sub_category == "hotspot":
            return f"System: Hotspot {action}"
        else:
            return f"System: {sub_category} {action}"
    
    elif category == "notepad":
        if action == "write" and "content" in args:
            content = args["content"][:30] + "..." if len(args.get("content", "")) > 30 else args.get("content", "")
            return f"Notepad: Wrote '{content}'"
        return f"Notepad: {action.replace('_', ' ').title()}"
    
    elif category == "scheduler":
        return f"Scheduler: Added job"
    
    elif category == "openclaw":
        return f"Openclaw: {action.replace('_', ' ').title()}"
    
    elif category == "web":
        if "query" in args:
            return f"Web: Searched '{args['query']}'"
        return f"Web: {action}"
    
    # Default summary
    return f"{category.title()}: {action.replace('_', ' ').title()}"


def _detect_topic(tool_name: str, args: dict) -> str:
    """Detect topic/category for the action."""
    category = _extract_tool_category(tool_name)
    
    topic_map = {
        "youtube": "video",
        "instagram": "social",
        "whatsapp": "social",
        "gmail": "communication",
        "notepad": "work",
        "system": "system",
        "scheduler": "schedule",
        "web": "search",
        "window_control": "system",
    }
    
    return topic_map.get(category, "general")


def _share_tool_context(tool_name: str, args: dict, result: dict):
    """Share relevant context from tool execution for other tools to use."""
    memory = _get_memory()
    if not memory:
        return
    
    category = _extract_tool_category(tool_name)
    
    # Share usernames
    if "username" in args:
        memory.share_content("username", args["username"], category)
    
    # Share queries/searches
    if "query" in args:
        memory.share_content("query", args["query"], category)
        memory.set_tool_context(category, "last_search", args["query"])
    
    # Share URLs
    if "url" in args:
        memory.share_content("url", args["url"], category)
    
    # Share app names
    if "app" in args:
        memory.share_content("app", args["app"], category)
        memory.set_tool_context("system", "last_app", args["app"])
    
    # Share file paths
    if "file_path" in args or "path" in args:
        path = args.get("file_path") or args.get("path")
        memory.share_content("file", path, category)
    
    # Share content/text
    if "content" in args:
        memory.set_tool_context(category, "last_content", args["content"][:200])
    
    # Track page/destination
    if "destination" in args:
        memory.set_tool_context(category, "current_page", args["destination"])
    
    # Track action for pattern learning
    if "action" in args:
        memory.set_tool_context(category, "last_action", args["action"])
    
    # Track tool-specific context
    if category == "youtube":
        if "youtube.play" in tool_name:
            memory.set_tool_context("youtube", "is_playing", True)
            if "query" in args:
                memory.set_tool_context("youtube", "now_playing", args["query"])
    
    elif category == "system":
        if "volume" in tool_name:
            if "value" in args:
                memory.set_tool_context("system", "current_volume", args["value"])
        elif "brightness" in tool_name:
            if "value" in args:
                memory.set_tool_context("system", "current_brightness", args["value"])


def _track_execution(tool_name: str, args: dict, result: dict, duration_ms: float):
    """Track tool execution in memory."""
    memory = _get_memory()
    if not memory:
        return
    
    try:
        # Generate summary
        summary = _generate_summary(tool_name, args, result)
        topic = _detect_topic(tool_name, args)
        
        # Add to context
        memory.add_context(
            summary=summary,
            action=tool_name,
            entities=args,
            result={
                "status": result.get("status"),
                "message": result.get("message", ""),
                "duration_ms": duration_ms
            },
            topic=topic
        )
        
        # Learn preferences from successful actions
        if result.get("status") == "success":
            memory.learn_preference_from_action(tool_name, args)
            _share_tool_context(tool_name, args, result)
        
        print(f"[Memory] Tracked: {summary}")
        
    except Exception as e:
        print(f"[Memory] Error tracking: {e}")


def _inject_memory_context(tool_name: str, args: dict) -> dict:
    """Inject memory context into tool args for cross-tool awareness."""
    memory = _get_memory()
    if not memory:
        return args
    
    # Clone args to avoid mutation
    enhanced_args = dict(args)
    
    category = _extract_tool_category(tool_name)
    
    # Inject last shared username if tool needs it but doesn't have one
    if "username" not in enhanced_args:
        shared_usernames = memory.get_shared_content("username", limit=1)
        if shared_usernames:
            enhanced_args["_last_username"] = shared_usernames[0].get("content")
    
    # Inject last query if relevant
    if "query" not in enhanced_args:
        last_query = memory.get_global_context("last_search")
        if last_query:
            enhanced_args["_last_query"] = last_query
    
    # Inject last app for system tools
    if category == "system":
        last_app = memory.get_tool_context("system", "last_app")
        if last_app:
            enhanced_args["_last_app"] = last_app
    
    # Inject YouTube context
    if category == "youtube":
        yt_context = memory.get_youtube_context()
        enhanced_args["_youtube_context"] = yt_context
    
    # Inject Instagram context
    if category == "instagram":
        ig_context = memory.get_instagram_context()
        enhanced_args["_instagram_context"] = ig_context
    
    # Inject WhatsApp context
    if category == "whatsapp":
        wa_context = memory.get_tool_context("whatsapp")
        enhanced_args["_whatsapp_context"] = wa_context
        
    # Inject Gmail context
    if category == "gmail":
        gm_context = memory.get_tool_context("gmail")
        enhanced_args["_gmail_context"] = gm_context
    
    # Inject recent actions for context
    recent = memory.get_recent_context(limit=3)
    if recent:
        enhanced_args["_recent_actions"] = [
            {"action": r.get("action"), "summary": r.get("summary")}
            for r in recent
        ]
    
    return enhanced_args


# ============== MAIN EXECUTOR ==============

def execute(plan):
    """
    Execute a plan and return the result.
    
    Features:
    - Tracks all executions in memory
    - Injects cross-tool context into args
    - Shares context between tools
    - Learns patterns from usage
    
    Returns:
        dict with 'status' and optional 'message'
    """
    # Handle message-only plans (no steps) - return silently, let LLM respond
    if "message" in plan:
        return {"status": "message", "message": plan["message"]}
    
    print(f"DEBUG: executor received plan -> {plan}")
    results = []
    
    # Cleanup expired context periodically
    memory = _get_memory()
    if memory:
        try:
            removed = memory.cleanup_expired_context()
            if removed > 0:
                print(f"[Memory] Cleaned up {removed} expired context entries")
        except:
            pass
    
    for step in plan["steps"]:
        tool_name = step["tool"]
        args = step.get("args", {})
        retries = step.get("retry", 1)
        timeout = step.get("timeout", None)

        # Inject memory context into args
        enhanced_args = _inject_memory_context(tool_name, args)
        
        try:
            tool_path = TOOL_REGISTRY[tool_name]
        except KeyError:
            return {"status": "fail", "tool": tool_name, "reason": f"Tool '{tool_name}' not found in registry"}
        
        print(f"DEBUG: executing tool {tool_name} -> module {tool_path} with args {args}")
        
        try:
            module = importlib.import_module(tool_path)
        except ImportError as e:
            return {"status": "fail", "tool": tool_name, "reason": f"Failed to import tool: {e}"}

        attempt = 0
        result = None
        exec_start = time.time()
        
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
                    result = run_fn(args)  # Use original args for single-arg tools
                else:
                    # Use original args (not enhanced) for actual execution
                    # Enhanced args are for internal reference
                    result = run_fn(**args)

                if timeout is not None and (time.time() - start) > timeout:
                    attempt += 1
                    time.sleep(0.3)
                    continue

                if result.get("status") == "success":
                    results.append(result)
                    break
                elif result.get("status") in ("skip", "partial"):
                    # Also consider skip/partial as acceptable results
                    results.append(result)
                    break
                    
            except Exception as e:
                result = {"status": "error", "error": str(e)}
                print(f"[Executor] Error in {tool_name}: {e}")
                if timeout is not None and (time.time() - start) > timeout:
                    attempt += 1
                    time.sleep(0.3)
                    continue

            attempt += 1
            time.sleep(0.3)
        else:
            # Track failed execution too
            duration_ms = (time.time() - exec_start) * 1000
            _track_execution(tool_name, args, result or {"status": "fail"}, duration_ms)
            return {"status": "fail", "tool": tool_name, "last_result": result}
        
        # Track successful execution in memory
        duration_ms = (time.time() - exec_start) * 1000
        _track_execution(tool_name, args, result, duration_ms)
    
    return {"status": "success", "results": results}


def get_execution_context() -> dict:
    """Get current execution context for tools to use."""
    memory = _get_memory()
    if not memory:
        return {}
    
    return {
        "recent_actions": memory.get_recent_context(limit=5),
        "shared_content": memory.get_shared_content(limit=5),
        "youtube_context": memory.get_youtube_context(),
        "instagram_context": memory.get_instagram_context(),
        "suggestions": memory.get_suggestions(limit=3),
    }


def get_last_result_for_tool(tool_category: str) -> dict:
    """Get the last result from a specific tool category."""
    memory = _get_memory()
    if not memory:
        return {}
    
    last_action = memory.get_last_tool_action(tool_category)
    return last_action or {}
