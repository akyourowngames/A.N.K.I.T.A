"""
Contacts book for A.N.K.I.T.A.

Stores name → E.164 phone mappings in data/contacts.json.
Supports fuzzy name matching so "Krish", "krish", "KRISH" all work.

Tools exposed:
    lookup_contact(name)           → phone number or error
    add_contact(name, phone)       → ok / error
    remove_contact(name)           → ok / error
    list_contacts()                → list of {name, phone}
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, Any, List

# ---------------------------------------------------------------------------
# Path to contacts file — relative to this file's location
# ---------------------------------------------------------------------------
_CONTACTS_FILE = Path(__file__).parent.parent / "data" / "contacts.json"


def _load() -> Dict[str, str]:
    """Load contacts dict (lowercase name → phone). Ignores _comment key."""
    if not _CONTACTS_FILE.exists():
        return {}
    try:
        data = json.loads(_CONTACTS_FILE.read_text(encoding="utf-8"))
        return {k.lower(): v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        return {}


def _save(contacts: Dict[str, str]) -> None:
    """Save contacts dict to file, preserving the _comment key."""
    _CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if _CONTACTS_FILE.exists():
        try:
            existing = json.loads(_CONTACTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Preserve _comment, update the rest
    out = {"_comment": existing.get("_comment", "Contacts for A.N.K.I.T.A")}
    out.update(contacts)
    _CONTACTS_FILE.write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _normalize_phone(phone: str) -> str:
    """Ensure phone is E.164 — strip spaces/dashes, add + if missing."""
    phone = re.sub(r"[\s\-\(\)]", "", phone.strip())
    if not phone.startswith("+"):
        phone = "+" + phone
    return phone


def _fuzzy_match(name: str, contacts: Dict[str, str]) -> str | None:
    """Return the best matching key for `name`, or None."""
    key = name.lower().strip()
    # Exact match
    if key in contacts:
        return key
    # Starts-with match
    matches = [k for k in contacts if k.startswith(key) or key.startswith(k)]
    if len(matches) == 1:
        return matches[0]
    # Contains match
    matches = [k for k in contacts if key in k or k in key]
    if len(matches) == 1:
        return matches[0]
    return None


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

def lookup_contact(name: str) -> Dict[str, Any]:
    """
    Look up a contact's phone number by name.

    Args:
        name: Contact name (case-insensitive, fuzzy matched).

    Returns:
        {"ok": True,  "name": name, "phone": "+91..."}
        {"ok": False, "error": "Contact 'X' not found. Known: [...]"}
    """
    contacts = _load()
    key = _fuzzy_match(name, contacts)
    if key:
        return {"ok": True, "name": key, "phone": contacts[key]}

    known = sorted(contacts.keys())
    return {
        "ok": False,
        "error": f"Contact '{name}' not found. Known contacts: {known}",
    }


def add_contact(name: str, phone: str) -> Dict[str, Any]:
    """
    Add or update a contact.

    Args:
        name:  Contact name.
        phone: Phone in E.164 format, e.g. '+919876543210'.

    Returns:
        {"ok": True,  "name": name, "phone": phone}
        {"ok": False, "error": "..."}
    """
    if not name or not name.strip():
        return {"ok": False, "error": "Name cannot be empty."}
    if not phone or not phone.strip():
        return {"ok": False, "error": "Phone cannot be empty."}

    phone = _normalize_phone(phone)
    if not re.match(r"^\+\d{7,15}$", phone):
        return {
            "ok": False,
            "error": f"Invalid phone '{phone}'. Must be E.164 format like +919876543210.",
        }

    contacts = _load()
    key = name.lower().strip()
    contacts[key] = phone
    _save(contacts)
    return {"ok": True, "name": key, "phone": phone}


def remove_contact(name: str) -> Dict[str, Any]:
    """
    Remove a contact by name.

    Args:
        name: Contact name to remove.

    Returns:
        {"ok": True,  "name": name}
        {"ok": False, "error": "Contact 'X' not found."}
    """
    contacts = _load()
    key = _fuzzy_match(name, contacts)
    if not key:
        return {"ok": False, "error": f"Contact '{name}' not found."}

    del contacts[key]
    _save(contacts)
    return {"ok": True, "name": key}


def list_contacts() -> Dict[str, Any]:
    """
    List all saved contacts.

    Returns:
        {"ok": True, "contacts": [{"name": "krish", "phone": "+91..."}, ...]}
    """
    contacts = _load()
    result = [{"name": k, "phone": v} for k, v in sorted(contacts.items())]
    return {"ok": True, "contacts": result, "count": len(result)}
