from tests.helpers import login


def test_login_success_sets_session_cookie(client):
    resp = client.post("/api/login", json={"username": "alice", "password": "alicepass1"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "username": "alice", "theme": "system"}
    assert "session" in resp.cookies


def test_login_wrong_password_rejected(client):
    resp = client.post("/api/login", json={"username": "alice", "password": "nope"})
    assert resp.status_code == 401


def test_login_unknown_username_rejected(client):
    resp = client.post("/api/login", json={"username": "ghost", "password": "whatever"})
    assert resp.status_code == 401


def test_me_requires_authentication(client):
    resp = client.get("/api/me")
    assert resp.status_code == 401


def test_me_returns_current_username(client):
    cookies = login(client, "alice", "alicepass1")
    resp = client.get("/api/me", headers=cookies)
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


def test_logout_invalidates_session(client):
    cookies = login(client, "alice", "alicepass1")
    assert client.get("/api/me", headers=cookies).status_code == 200
    client.post("/api/logout", headers=cookies)
    assert client.get("/api/me", headers=cookies).status_code == 401


def test_repeated_failed_logins_are_locked_out(client):
    for _ in range(5):
        resp = client.post("/api/login", json={"username": "alice", "password": "wrong"})
        assert resp.status_code == 401
    # Even the correct password is rejected once the per-IP lockout trips.
    resp = client.post("/api/login", json={"username": "alice", "password": "alicepass1"})
    assert resp.status_code == 429


def test_change_password_requires_correct_current_password(client):
    cookies = login(client, "alice", "alicepass1")
    resp = client.post(
        "/api/change-password",
        headers=cookies,
        json={"current_password": "wrong", "new_password": "brandnewpass"},
    )
    assert resp.status_code == 401


def test_change_password_updates_credentials(client):
    cookies = login(client, "alice", "alicepass1")
    resp = client.post(
        "/api/change-password",
        headers=cookies,
        json={"current_password": "alicepass1", "new_password": "brandnewpass"},
    )
    assert resp.status_code == 200

    old = client.post("/api/login", json={"username": "alice", "password": "alicepass1"})
    assert old.status_code == 401

    new = client.post("/api/login", json={"username": "alice", "password": "brandnewpass"})
    assert new.status_code == 200
