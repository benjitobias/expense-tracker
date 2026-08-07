import sqlite3
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app import auth, database
from app.main import app
from tests.helpers import login

LEGACY_SCHEMA = """
CREATE TABLE expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL CHECK(amount > 0),
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE budgets (
    category TEXT PRIMARY KEY,
    monthly_limit REAL NOT NULL CHECK(monthly_limit >= 0)
);
CREATE TABLE feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('bug','feature')),
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','done')),
    created_at TEXT NOT NULL
);
"""


def _create_legacy_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO expenses (amount, description, category, date, created_at) VALUES (?,?,?,?,?)",
        (42.5, "Legacy rent", "Housing", "2026-07-01", now),
    )
    conn.execute("INSERT INTO budgets (category, monthly_limit) VALUES ('Housing', 1000)")
    conn.execute(
        "INSERT INTO feedback (kind, text, status, created_at) VALUES ('feature', 'old feedback', 'open', ?)",
        (now,),
    )
    conn.commit()
    conn.close()


def _use_legacy_env(monkeypatch, db_path, app_password="oldpass123"):
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(auth, "USERS_ENV", "")
    monkeypatch.setattr(auth, "APP_PASSWORD", app_password)
    monkeypatch.setenv("APP_PASSWORD", app_password)
    auth._sessions.clear()
    auth._failed_attempts.clear()


def test_legacy_single_password_db_migrates_on_startup(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)
    _use_legacy_env(monkeypatch, db_path)

    with TestClient(app) as client:
        cookies = login(client, "admin", "oldpass123")

        expenses = client.get("/api/expenses?month=2026-07", headers=cookies).json()
        assert len(expenses) == 1
        assert expenses[0]["description"] == "Legacy rent"

        budgets = client.get("/api/budgets", headers=cookies).json()
        assert budgets == {"Housing": 1000.0}

        feedback = client.get("/api/feedback", headers=cookies).json()
        assert len(feedback) == 1
        assert feedback[0]["username"] == "admin"


def test_migrated_data_is_not_visible_to_other_accounts(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(auth, "USERS_ENV", "newperson:newpass123")
    monkeypatch.setattr(auth, "APP_PASSWORD", "oldpass123")
    monkeypatch.setenv("APP_PASSWORD", "oldpass123")
    auth._sessions.clear()
    auth._failed_attempts.clear()

    with TestClient(app) as client:
        cookies = login(client, "newperson", "newpass123")
        assert client.get("/api/expenses?month=2026-07", headers=cookies).json() == []
        assert client.get("/api/budgets", headers=cookies).json() == {}


def test_migration_is_idempotent_across_restarts(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)
    _use_legacy_env(monkeypatch, db_path)

    with TestClient(app):
        pass  # first boot: migrates legacy data and creates the admin account

    auth._sessions.clear()
    auth._failed_attempts.clear()
    with TestClient(app) as client:
        # second boot must not touch the already-migrated admin password
        resp = client.post("/api/login", json={"username": "admin", "password": "oldpass123"})
        assert resp.status_code == 200

        cookies = {"Cookie": f"session={resp.cookies['session']}"}
        expenses = client.get("/api/expenses?month=2026-07", headers=cookies).json()
        assert len(expenses) == 1
