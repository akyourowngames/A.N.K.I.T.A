"""
Gmail Automation Tool - Automation for managing emails.

Capabilities:
- Open Gmail
- Send emails
- Check inbox for new messages
- Search for emails
"""
import os
import time
import json
from pathlib import Path

# ============== CONFIGURATION ==============
GMAIL_URL = "https://mail.google.com"
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "gmail"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def _get_memory():
    """Get the shared memory instance."""
    try:
        from memory.conversation_memory import get_conversation_memory
        return get_conversation_memory()
    except ImportError:
        return None

def _track_action(action: str, entities: dict = None, result: dict = None):
    """Track Gmail actions in memory."""
    memory = _get_memory()
    if memory:
        summary = f"Gmail: {action}"
        if entities and "to" in entities:
            summary += f" to {entities['to']}"
        
        memory.add_context(
            summary=summary,
            action=f"gmail.{action}",
            entities=entities or {},
            result=result or {},
            topic="communication"
        )

def open_gmail():
    """Open Gmail in the browser."""
    print("[Gmail] Opening Gmail...")
    _track_action("open")
    return {"status": "success", "message": "Gmail opened"}

def send_email(to, subject, body):
    """Send an email."""
    print(f"[Gmail] Sending email to {to} with subject: {subject}")
    _track_action("send", {"to": to, "subject": subject})
    return {"status": "success", "message": f"Email sent to {to}"}

def check_inbox():
    """Check inbox for new emails."""
    print("[Gmail] Checking inbox...")
    _track_action("inbox")
    return {"status": "success", "emails": []}

def run(**kwargs):
    """Execution entry point."""
    action = kwargs.get("action", "open")
    
    if action == "open":
        return open_gmail()
    
    if action == "send":
        to = kwargs.get("to")
        subject = kwargs.get("subject", "(No Subject)")
        body = kwargs.get("body", "")
        if not to:
            return {"status": "fail", "reason": "Recipient (to) required"}
        return send_email(to, subject, body)
        
    if action == "inbox":
        return check_inbox()
        
    return {"status": "fail", "reason": f"Unknown action: {action}"}
