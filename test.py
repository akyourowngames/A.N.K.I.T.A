"""
JARVIS TEST SCRIPT - General and Realtime Chat Selector
========================================================

PURPOSE:
This is a command-line test interface for interacting with J.A.R.V.I.S.
It allows you to switch between general chat (pure LLM, no web search) and realtime chat
(with Tavily web search) modes. Both modes share the same session ID, allowing
seamless conversation switching.

WHY IT EXISTS:
- Provides an easy way to test the JARVIS API without building a frontend
- Demonstrates how to use both chat endpoints
- Shows session management in action
- Useful for development and debugging

USAGE:
    python test.py
    
    Make sure the server is running first: python run.py

COMMANDS:
    1 - Switch to General Chat mode (pure LLM, no web search)
    2 - Switch to Realtime Chat mode (with Tavily web search)
    /history - View chat history for current session
    /clear - Start a new session (clears current session)
    /quit or /exit - Exit the test interface

HOW IT WORKS:
1. User selects a mode (1 for general, 2 for realtime)
2. User types messages which are sent to the appropriate endpoint
3. Both modes use the same session_id, so conversation context is shared
4. User can switch modes at any time within the same conversation
5. Session persists until user clears it or starts a new one
"""

import requests
import json
from datetime import datetime
from uuid import uuid4

try:
    from config import ASSISTANT_NAME
except ImportError:
    ASSISTANT_NAME = "Jarvis"


# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------
# API base URL; change if your server runs on a different host or port.
BASE_URL = "http://localhost:8000"
# Single session for this test client; shared between general and realtime modes.
SESSION_ID = None
CURRENT_MODE = None  # "general" (pure LLM) or "realtime" (with Tavily search)


# -----------------------------------------------------------------------------
# UI HELPERS
# -----------------------------------------------------------------------------

def print_header():
    print("\n" + "="*60)
    print("🤖 J.A.R.V.I.S - General & Realtime Chat")
    print("="*60)
    print("\nModes:")
    print("  1 = General Chat (pure LLM, no web search)")
    print("  2 = Realtime Chat (with Tavily search)")
    print("\nCommands:")
    print("  /history - See chat history")
    print("  /clear - Start new session")
    print("  /quit - Exit")
    print("="*60 + "\n")


def get_user_input():
    """Get user's input - either mode selection or message."""
    try:
        choice = input("\nYou: ").strip()
        return choice
    except (KeyboardInterrupt, EOFError):
        return None


# -----------------------------------------------------------------------------
# API CALLS
# -----------------------------------------------------------------------------

def send_message(message, mode):
    """
    Send a message to the appropriate JARVIS endpoint.
    
    This function sends the user's message to either the general chat endpoint
    (/chat) or the realtime chat endpoint (/chat/realtime) based on the selected mode.
    It uses the same session_id for both modes, allowing conversation continuity.
    
    Args:
        message: The user's message/question
        mode: Either "general" or "realtime" to determine which endpoint to use
    
    Returns:
        str: JARVIS's response, or an error message if something went wrong
    
    Note:
        - Creates a new session_id if one doesn't exist
        - Uses longer timeout for realtime mode (60s) since it includes web search
        - General mode uses shorter timeout (30s) as it's faster
    """
    global SESSION_ID
    
    # Generate a new session ID if we don't have one yet
    # This session_id will be used for both general and realtime modes
    if not SESSION_ID:
        SESSION_ID = str(uuid4())
    
    # Choose endpoint based on mode
    # /chat/realtime uses Tavily search, /chat is general chat
    endpoint = "/chat/realtime" if mode == "realtime" else "/chat"
    
    try:
        # Send POST request to the appropriate endpoint
        # Include the message and session_id in the request body
        response = requests.post(
            f"{BASE_URL}{endpoint}",
            json={
                "message": message,
                "session_id": SESSION_ID
            },
            timeout=60 if mode == "realtime" else 30  # Realtime needs more time for web search
        )
        
        # If request succeeded, extract response and update session_id
        if response.status_code == 200:
            data = response.json()
            SESSION_ID = data.get("session_id", SESSION_ID)  # Update session_id if server returned one
            return data.get("response", "No response")
        else:
            # Request failed - show user-friendly message when available (e.g. 429 rate limit)
            try:
                err = response.json()
                if isinstance(err.get("detail"), str):
                    return f"❌ {err['detail']}"
            except Exception:
                pass
            return f"❌ Error: {response.status_code} - {response.text}"
    
    except requests.exceptions.ConnectionError:
        # Server is not running or not accessible
        return "❌ Cannot connect to backend. Start it with: python run.py"
    except requests.exceptions.Timeout:
        # Request took too long (especially for realtime mode)
        return "❌ Request timed out. Try a simpler query."
    except Exception as e:
        # Any other error
        return f"❌ Error: {str(e)}"


def get_chat_history():
    """
    Retrieve and format chat history for the current session.
    
    This function fetches all messages from the current session and formats them
    in a readable way. The history includes both general and realtime messages
    since they share the same session_id.
    
    Returns:
        str: Formatted chat history, or an error message if retrieval failed
    
    Note:
        - Returns "No active session" if no session_id exists
        - Shows all messages from both general and realtime modes
        - Messages are numbered and clearly labeled as "You" or "Jarvis"
    """
    if not SESSION_ID:
        return "No active session"
    
    try:
        # Request chat history from the API
        response = requests.get(
            f"{BASE_URL}/chat/history/{SESSION_ID}",
            timeout=10
        )
        
        if response.status_code == 200:
            history = response.json()
            messages = history.get("messages", [])
            
            if not messages:
                return "No messages in this session"
            
            # Format the history for display
            output = f"\n📜 Chat History ({len(messages)} messages):\n"
            output += "-" * 60 + "\n"
            
            # Display each message with its role (user or assistant)
            for i, msg in enumerate(messages, 1):
                role = "You" if msg.get("role") == "user" else ASSISTANT_NAME
                content = msg.get("content", "")
                output += f"{i}. {role}: {content}\n"
            
            output += "-" * 60 + "\n"
            return output
        else:
            return "Could not retrieve history"
    
    except Exception as e:
        return f"Error retrieving history: {str(e)}"


# -----------------------------------------------------------------------------
# MAIN LOOP
# -----------------------------------------------------------------------------

def main():
    """
    Main chat loop: prompt for mode (1=general, 2=realtime), then accept messages
    until /quit or /exit. Handles /history, /clear, and mode switching.
    """
    print_header()
    
    global SESSION_ID, CURRENT_MODE
    
    print("💡 Tip: Select a mode (1 or 2) then type your messages.")
    print("    Both modes share the same session until you clear it.\n")
    print("Select mode first (1=General, 2=Realtime):\n")
    
    while True:
        try:
            user_input = get_user_input()
            if user_input is None:
                print("\n👋 Goodbye!")
                break
            # Mode selection (1 = general chat, 2 = realtime with search)
            if user_input == "1":
                CURRENT_MODE = "general"
                print("✅ Switched to GENERAL chat (pure LLM, no web search)\n")
                continue
            
            elif user_input == "2":
                CURRENT_MODE = "realtime"
                print("✅ Switched to REALTIME chat (with Tavily web search)\n")
                continue
            
            # Slash commands: history, clear session, or quit
            elif user_input == "/history":
                print(get_chat_history())
                continue
            
            elif user_input == "/clear":
                SESSION_ID = None
                CURRENT_MODE = None
                print("\n🔄 Session cleared. Starting fresh!")
                print("Select mode again (1=General, 2=Realtime):\n")
                continue
            
            elif user_input in ["/quit", "/exit"]:
                print("\n👋 Goodbye!")
                break
            
            elif user_input.startswith("/"):
                print(f"❌ Unknown command: {user_input}")
                continue
            # Must have chosen a mode before sending a message
            if not CURRENT_MODE:
                print("❌ Please select a mode first (1=General or 2=Realtime)")
                continue
            
            message = user_input
            mode_label = "General" if CURRENT_MODE == "general" else "Realtime"
            print(f"🤖 {ASSISTANT_NAME} ({mode_label}): ", end="", flush=True)
            response = send_message(message, CURRENT_MODE)
            print(response)
        
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {str(e)}")


# Run the interactive loop when this file is executed (python test.py).
if __name__ == "__main__":
    main()
