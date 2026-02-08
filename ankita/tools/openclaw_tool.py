"""
OpenClaw Tool for ANKITA
Register this as a tool so ANKITA can use OpenClaw's cloud capabilities
"""

import requests
import json

# OpenClaw API endpoint (local gateway)
OPENCLAW_API = "http://127.0.0.1:5050"  # ANKITA's API bridge (reverse proxy to OpenClaw)

def run(args: dict) -> dict:
    """
    Execute OpenClaw tools from ANKITA
    """
    # Detect action from intent or tool name if not explicitly provided
    action = args.get("action", "")
    
    # Check if we are being called via a specific intent mapping
    if not action:
        # Check if the caller is the specific OpenClaw tool
        # Inferred from common argument patterns
        if "message" in args:
            action = "send_message"
        elif "query" in args:
            action = "web_search"
        elif "location" in args:
            action = "get_weather"
        else:
            # Last resort fallback for status
            action = "get_status"

    if action == "web_search":
        query = args.get("query", "")
        
        # Call OpenClaw via ANKITA's API bridge endpoint
        try:
            response = requests.post(
                f"{OPENCLAW_API}/openclaw/web_search",
                json={"query": query, "count": 5},
                timeout=15
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "status": "error",
                    "message": f"OpenClaw web search failed: {response.status_code}"
                }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to call OpenClaw: {str(e)}"
            }
    
    elif action == "send_message":
        message = args.get("message", "")
        target = args.get("target", "Krish")
        
        # Call OpenClaw to send Telegram message via ANKITA's API bridge
        try:
            response = requests.post(
                f"{OPENCLAW_API}/openclaw/send_message",
                json={
                    "message": f"ANKITA: {message}",
                    "channel": "telegram",
                    "target": target
                },
                timeout=10
            )
            if response.status_code == 200:
                return {
                    "status": "success",
                    "action": "send_message",
                    "message": message,
                    "sent": True
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to send: {response.status_code}"
                }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to send message: {str(e)}"
            }
    
    elif action == "get_weather":
        location = args.get("location", "current")
        
        # Use OpenClaw's web_fetch to get weather
        try:
            response = requests.post(
                f"{OPENCLAW_API}/openclaw/get_weather",
                json={"location": location},
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "status": "error",
                    "message": f"Weather lookup failed: {response.status_code}"
                }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get weather: {str(e)}"
            }
            
    elif action == "get_status":
        try:
            response = requests.get(f"{OPENCLAW_API}/health", timeout=5)
            if response.status_code == 200:
                return {
                    "status": "success",
                    "message": "Cloud bridge is active and healthy.",
                    "details": response.json()
                }
            else:
                return {"status": "error", "message": "Cloud bridge is unresponsive."}
        except Exception as e:
            return {"status": "error", "message": f"Bridge error: {str(e)}"}
    
    else:
        return {
            "status": "error",
            "message": f"Unknown OpenClaw action: {action}"
        }

# Tool metadata for ANKITA's registry
TOOL_META = {
    "name": "openclaw",
    "description": "Access OpenClaw cloud tools (web search, messaging, etc.)",
    "actions": ["web_search", "send_message", "get_weather"],
    "category": "cloud"
}
