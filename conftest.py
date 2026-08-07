import pytest
from fastapi.testclient import TestClient

from app import auth, database
from app.main import app
from tests.helpers import login


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A fresh, isolated app instance: its own SQLite file and its own
    in-memory session/lockout state, seeded with two accounts (alice, bob)."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(auth, "USERS_ENV", "alice:alicepass1,bob:bobpass1")
    monkeypatch.setattr(auth, "APP_PASSWORD", None)
    auth._sessions.clear()
    auth._failed_attempts.clear()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def alice(client):
    return login(client, "alice", "alicepass1")


@pytest.fixture()
def bob(client):
    return login(client, "bob", "bobpass1")
