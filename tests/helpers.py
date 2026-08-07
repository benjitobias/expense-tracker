def login(client, username, password):
    """Log in and return request headers carrying that user's session cookie.

    Passed as `headers=` on subsequent requests (rather than relying on the
    TestClient's shared cookie jar via `cookies=`, which is deprecated and
    also wouldn't let two logged-in users be exercised concurrently on one
    client instance).
    """
    resp = client.post("/api/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Cookie": f"session={resp.cookies['session']}"}
