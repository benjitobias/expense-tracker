def create_expense(client, cookies, **overrides):
    payload = {
        "amount": 12.5,
        "description": "Coffee",
        "category": "Food",
        "date": "2026-08-07",
    }
    payload.update(overrides)
    return client.post("/api/expenses", headers=cookies, json=payload)


def test_create_and_list_expense(client, alice):
    resp = create_expense(client, alice)
    assert resp.status_code == 201
    body = resp.json()
    assert body["amount"] == 12.5
    assert body["category"] == "Food"

    listing = client.get("/api/expenses?month=2026-08", headers=alice)
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_list_excludes_other_months(client, alice):
    create_expense(client, alice, date="2026-08-07")
    listing = client.get("/api/expenses?month=2026-07", headers=alice)
    assert listing.json() == []


def test_update_expense(client, alice):
    created = create_expense(client, alice).json()
    resp = client.put(
        f"/api/expenses/{created['id']}",
        headers=alice,
        json={"amount": 20, "description": "Lunch", "category": "Food", "date": "2026-08-07"},
    )
    assert resp.status_code == 200
    assert resp.json()["amount"] == 20
    assert resp.json()["description"] == "Lunch"


def test_update_missing_expense_404s(client, alice):
    resp = client.put(
        "/api/expenses/999",
        headers=alice,
        json={"amount": 1, "description": "x", "category": "Food", "date": "2026-08-07"},
    )
    assert resp.status_code == 404


def test_delete_expense(client, alice):
    created = create_expense(client, alice).json()
    resp = client.delete(f"/api/expenses/{created['id']}", headers=alice)
    assert resp.status_code == 204
    assert client.get("/api/expenses?month=2026-08", headers=alice).json() == []


def test_delete_missing_expense_404s(client, alice):
    resp = client.delete("/api/expenses/999", headers=alice)
    assert resp.status_code == 404


def test_negative_amount_rejected(client, alice):
    resp = create_expense(client, alice, amount=-5)
    assert resp.status_code == 422


def test_unregistered_category_rejected(client, alice):
    resp = create_expense(client, alice, category="Vacation")
    assert resp.status_code == 400


def test_location_is_optional(client, alice):
    resp = create_expense(client, alice)
    assert resp.status_code == 201
    assert resp.json()["location"] is None


def test_location_is_stored(client, alice):
    resp = create_expense(client, alice, location="Trader Joe's")
    assert resp.status_code == 201
    assert resp.json()["location"] == "Trader Joe's"

    listing = client.get("/api/expenses?month=2026-08", headers=alice).json()
    assert listing[0]["location"] == "Trader Joe's"


def test_note_is_optional(client, alice):
    resp = create_expense(client, alice)
    assert resp.status_code == 201
    assert resp.json()["note"] is None


def test_note_is_stored(client, alice):
    resp = create_expense(client, alice, note="Split with Sarah, she owes half")
    assert resp.status_code == 201
    assert resp.json()["note"] == "Split with Sarah, she owes half"

    listing = client.get("/api/expenses?month=2026-08", headers=alice).json()
    assert listing[0]["note"] == "Split with Sarah, she owes half"


def test_new_expense_has_no_photos(client, alice):
    resp = create_expense(client, alice)
    assert resp.json()["photos"] == []


def test_custom_category_usable_after_registration(client, alice):
    created = client.post("/api/categories", headers=alice, json={"name": "Pets"}).json()
    assert created["name"] == "Pets"

    resp = create_expense(client, alice, category="Pets")
    assert resp.status_code == 201
    assert resp.json()["category"] == "Pets"


def test_expenses_require_authentication(client):
    resp = client.get("/api/expenses?month=2026-08")
    assert resp.status_code == 401


def test_expenses_are_private_per_user(client, alice, bob):
    created = create_expense(client, alice, description="Alice only").json()

    bob_listing = client.get("/api/expenses?month=2026-08", headers=bob)
    assert bob_listing.json() == []

    hijack_update = client.put(
        f"/api/expenses/{created['id']}",
        headers=bob,
        json={"amount": 1, "description": "hijack", "category": "Food", "date": "2026-08-07"},
    )
    assert hijack_update.status_code == 404

    hijack_delete = client.delete(f"/api/expenses/{created['id']}", headers=bob)
    assert hijack_delete.status_code == 404

    alice_listing = client.get("/api/expenses?month=2026-08", headers=alice)
    assert len(alice_listing.json()) == 1
