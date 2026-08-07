import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, Request

APP_PASSWORD = os.environ.get("APP_PASSWORD")
USERS_ENV = os.environ.get("USERS", "")
SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "false").lower() == "true"

COOKIE_NAME = "session"
SESSION_TTL = 60 * 60 * 24 * 30  # 30 days

MAX_ATTEMPTS = 5
LOCKOUT_WINDOW = 60  # seconds

PBKDF2_ITERATIONS = 260_000

_sessions: dict[str, tuple["SessionUser", float]] = {}
_failed_attempts: dict[str, list[float]] = {}


@dataclass
class SessionUser:
    id: int
    username: str


def check_startup() -> None:
    if not APP_PASSWORD and not USERS_ENV:
        raise RuntimeError(
            "USERS environment variable must be set (e.g. USERS=alice:pass1,bob:pass2) "
            "before starting the app"
        )


# ------------------------------------------------------------ passwords ----

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, iterations, salt, hex_digest = password_hash.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), hex_digest)
    except (ValueError, AttributeError):
        return False


# Used to keep login timing similar for unknown usernames, so the app doesn't
# leak which usernames exist via response latency.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def verify_unknown_user() -> None:
    verify_password(secrets.token_urlsafe(8), _DUMMY_HASH)


# ---------------------------------------------------------- user seeding ----

def ensure_users_seeded(conn: sqlite3.Connection) -> None:
    """Create accounts listed in USERS that don't exist yet. Existing users
    (including ones migrated from a legacy single-password install) are left
    untouched, so re-running with the same USERS value never resets a
    password someone has since changed."""
    existing = {r["username"] for r in conn.execute("SELECT username FROM users")}

    for pair in USERS_ENV.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise RuntimeError(f"Invalid USERS entry {pair!r}, expected username:password")
        username, password = (part.strip() for part in pair.split(":", 1))
        if not username or not password:
            raise RuntimeError(f"Invalid USERS entry {pair!r}, expected username:password")
        if username in existing:
            continue
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, hash_password(password), datetime.now(timezone.utc).isoformat()),
        )
        existing.add(username)

    if not existing and APP_PASSWORD:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            ("admin", hash_password(APP_PASSWORD), datetime.now(timezone.utc).isoformat()),
        )
        existing.add("admin")

    conn.commit()

    if not existing:
        raise RuntimeError("No users configured — set USERS=username:password[,username:password...]")


# ------------------------------------------------------------- lockout ----

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


# -------------------------------------------------------------- sessions ----

def create_session(user: SessionUser) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = (user, time.time() + SESSION_TTL)
    return token


def destroy_session(token: str) -> None:
    _sessions.pop(token, None)


def get_session_user(token: str | None) -> SessionUser | None:
    if not token:
        return None
    entry = _sessions.get(token)
    if entry is None:
        return None
    user, expiry = entry
    if expiry < time.time():
        _sessions.pop(token, None)
        return None
    return user


def require_auth(request: Request) -> SessionUser:
    token = request.cookies.get(COOKIE_NAME)
    user = get_session_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
