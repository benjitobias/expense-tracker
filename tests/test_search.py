def add(client, cookies, **overrides):
    payload = {
        "amount": 12.5,
        "description": "Coffee",
        "category": "Food",
        "date": "2026-08-07",
    }
    payload.update(overrides)
    resp = client.post("/api/expenses", headers=cookies, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def search(client, cookies, q):
    return client.get("/api/expenses/search", headers=cookies, params={"q": q})


def test_search_requires_authentication(client):
    resp = client.get("/api/expenses/search", params={"q": "coffee"})
    assert resp.status_code == 401


def test_search_matches_description(client, alice):
    add(client, alice, description="Trader Joe's groceries")
    add(client, alice, description="Bus ticket")

    resp = search(client, alice, "groceries")
    assert resp.status_code == 200
    [result] = resp.json()
    assert result["description"] == "Trader Joe's groceries"


def test_search_matches_note(client, alice):
    add(client, alice, description="Dinner", note="Split with Sarah")
    add(client, alice, description="Lunch")

    [result] = search(client, alice, "sarah").json()
    assert result["description"] == "Dinner"


def test_search_matches_location(client, alice):
    add(client, alice, description="Snacks", location="Costco")
    add(client, alice, description="Snacks", location="Corner store")

    [result] = search(client, alice, "costco").json()
    assert result["location"] == "Costco"


def test_search_matches_category(client, alice):
    add(client, alice, description="x", category="Transport")
    add(client, alice, description="y", category="Food")

    [result] = search(client, alice, "transport").json()
    assert result["category"] == "Transport"


def test_search_matches_payment_method(client, alice):
    add(client, alice, description="x", payment_method="Cash")
    add(client, alice, description="y", payment_method="Card")

    [result] = search(client, alice, "cash").json()
    assert result["payment_method"] == "Cash"


def test_search_is_case_insensitive(client, alice):
    add(client, alice, description="COFFEE run")
    [result] = search(client, alice, "coffee").json()
    assert result["description"] == "COFFEE run"


def test_search_spans_all_months(client, alice):
    add(client, alice, description="Old thing", date="2020-01-01")
    add(client, alice, description="New thing", date="2026-08-07")

    results = search(client, alice, "thing").json()
    assert len(results) == 2


def test_search_no_matches_returns_empty_list(client, alice):
    add(client, alice, description="Coffee")
    assert search(client, alice, "nonexistent").json() == []


def test_search_blank_query_returns_empty_list(client, alice):
    add(client, alice, description="Coffee")
    assert search(client, alice, "   ").json() == []


def test_search_results_ordered_newest_first(client, alice):
    add(client, alice, description="match one", date="2026-01-01")
    add(client, alice, description="match two", date="2026-06-01")

    results = search(client, alice, "match").json()
    assert [r["description"] for r in results] == ["match two", "match one"]


def test_search_includes_photos(client, alice):
    created = add(client, alice, description="Receipt test")
    client.post(
        f"/api/expenses/{created['id']}/photos",
        headers=alice,
        files=[("files", ("a.jpg", b"\xff\xd8\xff\xe0x", "image/jpeg"))],
    )
    [result] = search(client, alice, "receipt").json()
    assert len(result["photos"]) == 1


def test_search_is_scoped_per_user(client, alice, bob):
    add(client, alice, description="Alice's secret snack")
    add(client, bob, description="Bob's secret snack")

    results = search(client, alice, "secret").json()
    assert len(results) == 1
    assert results[0]["description"] == "Alice's secret snack"
