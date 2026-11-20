"""Dashboard auth (docs/04 §7.4): one shared password -> HTTP-only SameSite=Strict signed session cookie."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request, WebSocket, status

from app.settings import Settings

COOKIE = "pdm_session"


def _secret(s: Settings) -> bytes:
    return (s.session_secret or s.dashboard_password or "dev").encode()


def make_token(s: Settings, now: float | None = None) -> str:
    exp = int((now or time.time()) + s.session_max_age_s)
    sig = hmac.new(_secret(s), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid_token(s: Settings, token: str | None, now: float | None = None) -> bool:
    if not s.dashboard_password:
        return True  # auth disabled (dev); startup logs a warning
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    good = hmac.new(_secret(s), exp.encode(), hashlib.sha256).hexdigest()
    return exp.isdigit() and hmac.compare_digest(sig, good) and int(exp) > (now or time.time())


def check_password(s: Settings, password: str) -> bool:
    return bool(s.dashboard_password) and secrets.compare_digest(password.encode(), s.dashboard_password.encode())


def check_api_key(s: Settings, key: str | None) -> bool:
    return bool(s.ingest_api_key) and key is not None and secrets.compare_digest(key.encode(), s.ingest_api_key.encode())


def require_user(request: Request) -> None:
    s: Settings = request.app.state.settings
    if not valid_token(s, request.cookies.get(COOKIE)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")


def ws_allowed(ws: WebSocket) -> bool:
    s: Settings = ws.app.state.settings
    return valid_token(s, ws.cookies.get(COOKIE))
