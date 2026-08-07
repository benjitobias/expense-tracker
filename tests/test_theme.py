def test_theme_defaults_to_system(client, alice):
    resp = client.get("/api/me", headers=alice)
    assert resp.status_code == 200
    assert resp.json()["theme"] == "system"


def test_set_theme_persists(client, alice):
    resp = client.put("/api/theme", headers=alice, json={"theme": "dark"})
    assert resp.status_code == 200
    assert resp.json() == {"theme": "dark"}

    assert client.get("/api/me", headers=alice).json()["theme"] == "dark"


def test_set_theme_back_to_system(client, alice):
    client.put("/api/theme", headers=alice, json={"theme": "dark"})
    client.put("/api/theme", headers=alice, json={"theme": "system"})
    assert client.get("/api/me", headers=alice).json()["theme"] == "system"


def test_invalid_theme_rejected(client, alice):
    resp = client.put("/api/theme", headers=alice, json={"theme": "purple"})
    assert resp.status_code == 422


def test_theme_is_private_per_user(client, alice, bob):
    client.put("/api/theme", headers=alice, json={"theme": "dark"})
    assert client.get("/api/me", headers=bob).json()["theme"] == "system"


def test_login_response_includes_theme(client):
    resp = client.post("/api/login", json={"username": "alice", "password": "alicepass1"})
    assert resp.json()["theme"] == "system"
