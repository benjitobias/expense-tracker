import hmac
import os
import secrets
import time

from fastapi import HTTPException, Request

APP_PASSWORD = os.environ.get("APP_PASSWORD")
SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "false").lower() == "true"

COOKIE_NAME = "session"
SESSION_TTL = 60 * 60 * 24 * 30  # 30 days

MAX_ATTEMPTS = 5
LOCKOUT_WINDOW = 60  # seconds

_sessions: dict[str, float] = {}
_failed_attempts: dict[str, list[float]] = {}


def check_startup() -> None:
    if not APP_PASSWORD:
        raise RuntimeError(
            "APP_PASSWORD environment variable must be set before starting the app"
        )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def is_locked_out(request: Request) -> bool:
    ip = _client_ip(request)
    now = time.time()
    attempts = [t for t in _failed_attempts.get(ip, []) if now - t < LOCKOUT_WINDOW]
    _failed_attempts[ip] = attempts
    return len(attempts) >= MAX_ATTEMPTS


def record_failed_attempt(request: Request) -> None:
    ip = _client_ip(request)
    _failed_attempts.setdefault(ip, []).append(time.time())


def verify_password(password: str) -> bool:
    return hmac.compare_digest(password, APP_PASSWORD or "")


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_TTL
    return token


def destroy_session(token: str) -> None:
    _sessions.pop(token, None)


def is_valid_session(token: str | None) -> bool:
    if not token:
        return False
    expiry = _sessions.get(token)
    if expiry is None:
        return False
    if expiry < time.time():
        _sessions.pop(token, None)
        return False
    return True


def require_auth(request: Request) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if not is_valid_session(token):
        raise HTTPException(status_code=401, detail="Not authenticated")
