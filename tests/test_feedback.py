def test_create_feedback_records_submitter(client, alice):
    resp = client.post("/api/feedback", headers=alice, json={"kind": "bug", "text": "found a bug"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "alice"
    assert body["status"] == "open"


def test_feedback_is_shared_across_users(client, alice, bob):
    client.post("/api/feedback", headers=alice, json={"kind": "feature", "text": "add dark mode"})

    resp = client.get("/api/feedback", headers=bob)
    assert resp.status_code == 200
    [item] = resp.json()
    assert item["username"] == "alice"
    assert item["text"] == "add dark mode"


def test_any_user_can_resolve_shared_feedback(client, alice, bob):
    created = client.post("/api/feedback", headers=alice, json={"kind": "bug", "text": "x"}).json()

    resp = client.patch(f"/api/feedback/{created['id']}", headers=bob, json={"status": "done"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


def test_any_user_can_delete_shared_feedback(client, alice, bob):
    created = client.post("/api/feedback", headers=alice, json={"kind": "bug", "text": "x"}).json()

    resp = client.delete(f"/api/feedback/{created['id']}", headers=bob)
    assert resp.status_code == 204
    assert client.get("/api/feedback", headers=alice).json() == []


def test_update_missing_feedback_404s(client, alice):
    resp = client.patch("/api/feedback/999", headers=alice, json={"status": "done"})
    assert resp.status_code == 404


def test_delete_missing_feedback_404s(client, alice):
    resp = client.delete("/api/feedback/999", headers=alice)
    assert resp.status_code == 404


def test_open_items_sort_before_done_items(client, alice):
    first = client.post("/api/feedback", headers=alice, json={"kind": "bug", "text": "first"}).json()
    second = client.post("/api/feedback", headers=alice, json={"kind": "bug", "text": "second"}).json()
    client.patch(f"/api/feedback/{first['id']}", headers=alice, json={"status": "done"})

    items = client.get("/api/feedback", headers=alice).json()
    assert [i["id"] for i in items] == [second["id"], first["id"]]
