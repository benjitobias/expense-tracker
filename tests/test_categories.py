def test_list_categories_starts_with_builtins_only(client, alice):
    resp = client.get("/api/categories", headers=alice)
    assert resp.status_code == 200
    body = resp.json()
    assert body["builtin"] == [
        "Food", "Transport", "Shopping", "Entertainment",
        "Health", "Housing", "Utilities", "Other",
    ]
    assert body["custom"] == []


def test_create_custom_category(client, alice):
    resp = client.post("/api/categories", headers=alice, json={"name": "Pets"})
    assert resp.status_code == 200
    assert resp.json() == {"name": "Pets"}

    listing = client.get("/api/categories", headers=alice).json()
    assert listing["custom"] == ["Pets"]


def test_create_category_trims_whitespace(client, alice):
    resp = client.post("/api/categories", headers=alice, json={"name": "  Pets  "})
    assert resp.json() == {"name": "Pets"}


def test_blank_category_name_rejected(client, alice):
    resp = client.post("/api/categories", headers=alice, json={"name": "   "})
    assert resp.status_code == 422


def test_duplicate_of_builtin_folds_into_builtin_name(client, alice):
    resp = client.post("/api/categories", headers=alice, json={"name": "food"})
    assert resp.json() == {"name": "Food"}

    listing = client.get("/api/categories", headers=alice).json()
    assert listing["custom"] == []


def test_duplicate_custom_category_is_idempotent(client, alice):
    client.post("/api/categories", headers=alice, json={"name": "Pets"})
    resp = client.post("/api/categories", headers=alice, json={"name": "pets"})
    assert resp.json() == {"name": "Pets"}

    listing = client.get("/api/categories", headers=alice).json()
    assert listing["custom"] == ["Pets"]


def test_custom_categories_are_private_per_user(client, alice, bob):
    client.post("/api/categories", headers=alice, json={"name": "Pets"})
    resp = client.get("/api/categories", headers=bob)
    assert resp.json()["custom"] == []


def test_budget_can_be_set_on_custom_category(client, alice):
    client.post("/api/categories", headers=alice, json={"name": "Pets"})
    resp = client.put("/api/budgets/Pets", headers=alice, json={"monthly_limit": 50})
    assert resp.status_code == 200
    assert client.get("/api/budgets", headers=alice).json() == {"Pets": 50}


def test_budget_rejects_unregistered_category(client, alice):
    resp = client.put("/api/budgets/Pets", headers=alice, json={"monthly_limit": 50})
    assert resp.status_code == 400


def test_budget_rejects_other_users_custom_category(client, alice, bob):
    client.post("/api/categories", headers=alice, json={"name": "Pets"})
    resp = client.put("/api/budgets/Pets", headers=bob, json={"monthly_limit": 50})
    assert resp.status_code == 400
