def add(client, cookies, amount, category, date):
    resp = client.post(
        "/api/expenses",
        headers=cookies,
        json={"amount": amount, "description": "x", "category": category, "date": date},
    )
    assert resp.status_code == 201, resp.text
    return resp


def test_trends_aggregates_by_month_and_category(client, alice):
    add(client, alice, 100, "Food", "2026-08-01")
    add(client, alice, 50, "Transport", "2026-08-15")

    resp = client.get("/api/analytics/trends?months=1", headers=alice)
    assert resp.status_code == 200
    body = resp.json()
    assert body["months"] == ["2026-08"]
    assert body["totals"] == [150.0]
    assert body["by_category"]["2026-08"] == {"Food": 100.0, "Transport": 50.0}


def test_trends_scoped_per_user(client, alice, bob):
    add(client, alice, 100, "Food", "2026-08-01")
    add(client, bob, 999, "Food", "2026-08-01")

    resp = client.get("/api/analytics/trends?months=1", headers=alice)
    assert resp.json()["totals"] == [100.0]


def test_day_of_week_patterns_split_weekday_weekend(client, alice):
    add(client, alice, 40, "Food", "2026-08-03")      # Monday
    add(client, alice, 60, "Shopping", "2026-08-08")  # Saturday

    resp = client.get("/api/analytics/patterns?months=1", headers=alice)
    assert resp.status_code == 200
    body = resp.json()
    assert body["weekday_total"] == 40.0
    assert body["weekend_total"] == 60.0

    mon = next(d for d in body["by_day"] if d["day"] == "Mon")
    assert mon["total"] == 40.0


def test_budget_status_thresholds(client, alice):
    client.put("/api/budgets/Food", headers=alice, json={"monthly_limit": 100})
    add(client, alice, 90, "Food", "2026-08-01")

    resp = client.get("/api/analytics/budget-status?month=2026-08", headers=alice)
    assert resp.status_code == 200
    [status] = resp.json()
    assert status["category"] == "Food"
    assert status["spent"] == 90.0
    assert status["pct"] == 90.0
    assert status["status"] == "warning"


def test_budget_status_critical_when_over_limit(client, alice):
    client.put("/api/budgets/Food", headers=alice, json={"monthly_limit": 100})
    add(client, alice, 150, "Food", "2026-08-01")

    resp = client.get("/api/analytics/budget-status?month=2026-08", headers=alice)
    [status] = resp.json()
    assert status["status"] == "critical"


def test_budget_status_scoped_per_user(client, alice, bob):
    client.put("/api/budgets/Food", headers=alice, json={"monthly_limit": 100})
    add(client, bob, 500, "Food", "2026-08-01")

    resp = client.get("/api/analytics/budget-status?month=2026-08", headers=alice)
    [status] = resp.json()
    assert status["spent"] == 0.0
