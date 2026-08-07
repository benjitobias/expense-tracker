import os
import secrets
import sqlite3
from datetime import datetime, timezone

from . import auth

DB_PATH = os.environ.get("DB_PATH", "/data/expenses.db")

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount REAL NOT NULL CHECK(amount > 0),
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    location TEXT,
    date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses(user_id, date);

CREATE TABLE IF NOT EXISTS budgets (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    monthly_limit REAL NOT NULL CHECK(monthly_limit >= 0),
    PRIMARY KEY (user_id, category)
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind TEXT NOT NULL CHECK(kind IN ('bug','feature')),
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','done')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS custom_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, name)
);
"""


def get_connection() -> sqlite3.Connection:
    # FastAPI's yield-dependencies can run a generator's setup and teardown
    # halves on different threadpool workers, so sqlite3's default same-thread
    # check trips even though each connection is only ever used by one
    # request at a time, never concurrently across threads.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_single_user_data(conn: sqlite3.Connection) -> None:
    """Pre-multi-user databases have expenses/budgets/feedback with no owner.
    Fold all of it under one legacy account (named after LEGACY_USERNAME, or
    'admin') so existing data isn't orphaned when this upgrade runs."""
    if not _table_exists(conn, "expenses") or "user_id" in _columns(conn, "expenses"):
        return

    legacy_username = os.environ.get("LEGACY_USERNAME", "admin")
    legacy_password = os.environ.get("APP_PASSWORD") or secrets.token_urlsafe(16)
    cur = conn.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (legacy_username, auth.hash_password(legacy_password), datetime.now(timezone.utc).isoformat()),
    )
    legacy_user_id = cur.lastrowid or conn.execute(
        "SELECT id FROM users WHERE username = ?", (legacy_username,)
    ).fetchone()["id"]

    conn.execute("ALTER TABLE expenses ADD COLUMN user_id INTEGER")
    conn.execute("UPDATE expenses SET user_id = ?", (legacy_user_id,))

    if _table_exists(conn, "budgets") and "user_id" not in _columns(conn, "budgets"):
        conn.execute("ALTER TABLE budgets RENAME TO budgets_legacy")
        conn.execute(
            "CREATE TABLE budgets ("
            "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "category TEXT NOT NULL, "
            "monthly_limit REAL NOT NULL CHECK(monthly_limit >= 0), "
            "PRIMARY KEY (user_id, category))"
        )
        conn.execute(
            "INSERT INTO budgets (user_id, category, monthly_limit) "
            "SELECT ?, category, monthly_limit FROM budgets_legacy",
            (legacy_user_id,),
        )
        conn.execute("DROP TABLE budgets_legacy")

    if _table_exists(conn, "feedback") and "user_id" not in _columns(conn, "feedback"):
        conn.execute("ALTER TABLE feedback ADD COLUMN user_id INTEGER REFERENCES users(id)")
        conn.execute("UPDATE feedback SET user_id = ?", (legacy_user_id,))

    conn.commit()


def _migrate_add_expense_location(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "expenses") and "location" not in _columns(conn, "expenses"):
        conn.execute("ALTER TABLE expenses ADD COLUMN location TEXT")
        conn.commit()


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = get_connection()
    try:
        conn.executescript(USERS_SCHEMA)
        conn.commit()
        _migrate_single_user_data(conn)
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate_add_expense_location(conn)
    finally:
        conn.close()


def db_dependency():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
