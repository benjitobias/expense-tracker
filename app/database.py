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
    created_at TEXT NOT NULL,
    theme TEXT
);
"""

SESSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
    is_standard INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    closed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    amount REAL NOT NULL CHECK(amount > 0),
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    location TEXT,
    note TEXT,
    payment_method TEXT NOT NULL DEFAULT 'Card',
    date TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS expense_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expense_photos_expense ON expense_photos(expense_id);

CREATE TABLE IF NOT EXISTS budgets (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    monthly_limit REAL NOT NULL CHECK(monthly_limit >= 0),
    PRIMARY KEY (session_id, category)
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


def _migrate_add_expense_note(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "expenses") and "note" not in _columns(conn, "expenses"):
        conn.execute("ALTER TABLE expenses ADD COLUMN note TEXT")
        conn.commit()


def _migrate_add_user_theme(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "users") and "theme" not in _columns(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN theme TEXT")
        conn.commit()


def _migrate_add_expense_payment_method(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "expenses") and "payment_method" not in _columns(conn, "expenses"):
        conn.execute("ALTER TABLE expenses ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'Card'")
        conn.commit()


def _migrate_add_active_session_column(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "users") and "active_session_id" not in _columns(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN active_session_id INTEGER REFERENCES sessions(id)")
        conn.commit()


def _migrate_add_expense_session_column(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "expenses") and "session_id" not in _columns(conn, "expenses"):
        conn.execute("ALTER TABLE expenses ADD COLUMN session_id INTEGER REFERENCES sessions(id)")
        conn.commit()
    # Only safe to index once the column above is guaranteed to exist —
    # can't live in SCHEMA's executescript since that runs before this on
    # pre-sessions installs, where the table (sans session_id) already exists.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_expenses_session_date ON expenses(session_id, date)")
    conn.commit()


def _migrate_budgets_to_sessions(conn: sqlite3.Connection) -> None:
    """Pre-sessions installs have budgets keyed on (user_id, category), which
    can't hold two sessions' limits for the same category name. Recreate the
    table keyed on (session_id, category) instead, folding existing rows into
    each user's Standard session."""
    if not _table_exists(conn, "budgets") or "session_id" in _columns(conn, "budgets"):
        return
    conn.execute("ALTER TABLE budgets RENAME TO budgets_legacy")
    conn.execute(
        "CREATE TABLE budgets ("
        "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, "
        "category TEXT NOT NULL, "
        "monthly_limit REAL NOT NULL CHECK(monthly_limit >= 0), "
        "PRIMARY KEY (session_id, category))"
    )
    conn.execute(
        "INSERT INTO budgets (user_id, session_id, category, monthly_limit) "
        "SELECT user_id, "
        "(SELECT id FROM sessions WHERE sessions.user_id = budgets_legacy.user_id AND sessions.is_standard = 1), "
        "category, monthly_limit FROM budgets_legacy"
    )
    conn.execute("DROP TABLE budgets_legacy")
    conn.commit()


def ensure_sessions(conn: sqlite3.Connection) -> None:
    """Create the 'Standard' session for any user who doesn't have one yet
    (new accounts and pre-sessions installs alike), backfill orphaned
    expenses/budgets into it, and point active_session_id at it. Idempotent —
    safe to call on every boot."""
    now = datetime.now(timezone.utc).isoformat()
    default_currency = os.environ.get("DEFAULT_CURRENCY", "ILS")

    users_without_standard = conn.execute(
        "SELECT id FROM users WHERE id NOT IN (SELECT user_id FROM sessions WHERE is_standard = 1)"
    ).fetchall()
    for u in users_without_standard:
        conn.execute(
            "INSERT INTO sessions (user_id, name, currency, status, is_standard, created_at) "
            "VALUES (?, 'Standard', ?, 'open', 1, ?)",
            (u["id"], default_currency, now),
        )
    conn.commit()

    conn.execute(
        "UPDATE expenses SET session_id = "
        "(SELECT id FROM sessions WHERE sessions.user_id = expenses.user_id AND sessions.is_standard = 1) "
        "WHERE session_id IS NULL"
    )
    conn.commit()

    _migrate_budgets_to_sessions(conn)

    conn.execute(
        "UPDATE budgets SET session_id = "
        "(SELECT id FROM sessions WHERE sessions.user_id = budgets.user_id AND sessions.is_standard = 1) "
        "WHERE session_id IS NULL"
    )
    conn.execute(
        "UPDATE users SET active_session_id = "
        "(SELECT id FROM sessions WHERE sessions.user_id = users.id AND sessions.is_standard = 1) "
        "WHERE active_session_id IS NULL"
    )
    conn.commit()


def uploads_dir() -> str:
    return os.path.join(os.path.dirname(DB_PATH) or ".", "uploads")


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    os.makedirs(uploads_dir(), exist_ok=True)
    conn = get_connection()
    try:
        conn.executescript(USERS_SCHEMA)
        conn.commit()
        _migrate_single_user_data(conn)
        conn.executescript(SESSIONS_SCHEMA)
        conn.commit()
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate_add_expense_location(conn)
        _migrate_add_expense_note(conn)
        _migrate_add_user_theme(conn)
        _migrate_add_expense_payment_method(conn)
        _migrate_add_active_session_column(conn)
        _migrate_add_expense_session_column(conn)
    finally:
        conn.close()


def db_dependency():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
