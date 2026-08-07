def test_set_and_get_budget(client, alice):
    resp = client.put("/api/budgets/Food", headers=alice, json={"monthly_limit": 300})
    assert resp.status_code == 200
    assert client.get("/api/budgets", headers=alice).json() == {"Food": 300}


def test_set_budget_overwrites_existing_limit(client, alice):
    client.put("/api/budgets/Food", headers=alice, json={"monthly_limit": 300})
    client.put("/api/budgets/Food", headers=alice, json={"monthly_limit": 500})
    assert client.get("/api/budgets", headers=alice).json() == {"Food": 500}


def test_unknown_category_rejected(client, alice):
    resp = client.put("/api/budgets/Vacation", headers=alice, json={"monthly_limit": 100})
    assert resp.status_code == 400


def test_negative_limit_rejected(client, alice):
    resp = client.put("/api/budgets/Food", headers=alice, json={"monthly_limit": -1})
    assert resp.status_code == 422


def test_delete_budget(client, alice):
    client.put("/api/budgets/Food", headers=alice, json={"monthly_limit": 300})
    resp = client.delete("/api/budgets/Food", headers=alice)
    assert resp.status_code == 204
    assert client.get("/api/budgets", headers=alice).json() == {}


def test_budgets_are_private_per_user(client, alice, bob):
    client.put("/api/budgets/Food", headers=alice, json={"monthly_limit": 300})
    assert client.get("/api/budgets", headers=bob).json() == {}

    # bob setting his own Food budget doesn't touch alice's
    client.put("/api/budgets/Food", headers=bob, json={"monthly_limit": 50})
    assert client.get("/api/budgets", headers=alice).json() == {"Food": 300}
    assert client.get("/api/budgets", headers=bob).json() == {"Food": 50}
