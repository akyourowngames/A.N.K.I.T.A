"""Calendar web API: interactive connect for the Next.js frontend (Issue #5).

One global token (same file as CLI/Telegram). Secrets are write-only:
status never echoes raw tokens, only redacted previews from tools/calendar.
"""
from __future__ import annotations

import re

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("/status")
def status():
    from tools import calendar as _cal
    connected = bool(_cal.enabled() and _cal.is_connected())
    return {"enabled": _cal.enabled(), "connected": connected, "status": _cal.status_text()}


class AuthStart(BaseModel):
    client_id: str = ""
    redirect_uri: str = ""


@router.post("/auth/start")
def auth_start(body: AuthStart):
    from tools import calendar as _cal
    if body.client_id.strip():
        _cal.save_token({"client_id": body.client_id.strip()})
    msg = _cal.auth_start(body.client_id.strip(), body.redirect_uri.strip())
    m = re.search(r"https://accounts\.google\.com/\S+", msg)
    url = m.group(0).rstrip(").,") if m else ""
    return {"ok": not msg.startswith("ERROR"), "message": msg, "auth_url": url}


class AuthFinish(BaseModel):
    code: str = Field(min_length=1, max_length=2000)
    redirect_uri: str = ""
    client_id: str = ""
    client_secret: str = ""


@router.post("/auth/finish")
def auth_finish(body: AuthFinish):
    from tools import calendar as _cal
    msg = _cal.auth_finish(body.code.strip(), body.redirect_uri.strip(),
                           body.client_id.strip(), body.client_secret.strip())
    return {"ok": not msg.startswith("ERROR"), "message": msg}


class TokenSave(BaseModel):
    access_token: str = Field(min_length=1, max_length=5000)
    refresh_token: str = ""


@router.post("/token")
def save_token(body: TokenSave):
    from tools import calendar as _cal
    msg = _cal.set_token(body.access_token.strip(), body.refresh_token.strip())
    return {"ok": not msg.startswith("ERROR"), "message": msg}


@router.delete("")
def forget():
    from tools import calendar as _cal
    ok = _cal.clear_token()
    return {"forgot": ok, "message": "Calendar token forgotten." if ok else "Nothing was saved."}
