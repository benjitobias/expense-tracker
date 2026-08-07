import calendar
import sqlite3
from datetime import date

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# date.weekday() returns Monday=0 .. Sunday=6. The work week here is
# Sunday-Thursday, so the weekend is just Friday (4) and Saturday (5).
WEEKEND_WEEKDAYS = {4, 5}


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _shift_month(d: date, delta: int) -> date:
    month_index = d.month - 1 + delta
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def monthly_trends(db: sqlite3.Connection, months: int, user_id: int) -> dict:
    today = date.today().replace(day=1)
    month_keys = [_month_key(_shift_month(today, -i)) for i in range(months - 1, -1, -1)]
    range_start = _shift_month(today, -(months - 1)).isoformat()

    rows = db.execute(
        "SELECT date, category, amount FROM expenses WHERE user_id = ? AND date >= ?",
        (user_id, range_start),
    ).fetchall()

    totals = {k: 0.0 for k in month_keys}
    by_category: dict[str, dict[str, float]] = {k: {} for k in month_keys}
    for r in rows:
        key = r["date"][:7]
        if key not in totals:
            continue
        totals[key] += r["amount"]
        by_category[key][r["category"]] = by_category[key].get(r["category"], 0.0) + r["amount"]

    return {
        "months": month_keys,
        "totals": [round(totals[k], 2) for k in month_keys],
        "by_category": {
            k: {cat: round(amt, 2) for cat, amt in cats.items()}
            for k, cats in by_category.items()
        },
    }


def day_of_week_patterns(db: sqlite3.Connection, months: int, user_id: int) -> dict:
    today = date.today().replace(day=1)
    range_start = _shift_month(today, -(months - 1)).isoformat()

    rows = db.execute(
        "SELECT date, amount FROM expenses WHERE user_id = ? AND date >= ?",
        (user_id, range_start),
    ).fetchall()

    totals = [0.0] * 7
    counts = [0] * 7
    weekday_total = 0.0
    weekend_total = 0.0

    for r in rows:
        y, m, d = (int(part) for part in r["date"].split("-"))
        weekday = date(y, m, d).weekday()
        totals[weekday] += r["amount"]
        counts[weekday] += 1
        if weekday in WEEKEND_WEEKDAYS:
            weekend_total += r["amount"]
        else:
            weekday_total += r["amount"]

    return {
        "by_day": [
            {
                "day": DAY_NAMES[i],
                "total": round(totals[i], 2),
                "average": round(totals[i] / counts[i], 2) if counts[i] else 0,
            }
            for i in range(7)
        ],
        "weekday_total": round(weekday_total, 2),
        "weekend_total": round(weekend_total, 2),
    }


def daily_totals(db: sqlite3.Connection, month: str, user_id: int) -> dict:
    year, mon = (int(part) for part in month.split("-"))
    days_in_month = calendar.monthrange(year, mon)[1]

    rows = db.execute(
        "SELECT date, amount FROM expenses WHERE user_id = ? AND date LIKE ?",
        (user_id, f"{month}%"),
    ).fetchall()

    totals = [0.0] * days_in_month
    for r in rows:
        day = int(r["date"][8:10])
        totals[day - 1] += r["amount"]

    return {
        "days": list(range(1, days_in_month + 1)),
        "totals": [round(t, 2) for t in totals],
    }


def budget_status(db: sqlite3.Connection, month: str, user_id: int) -> list[dict]:
    budgets = {
        r["category"]: r["monthly_limit"]
        for r in db.execute("SELECT * FROM budgets WHERE user_id = ?", (user_id,)).fetchall()
    }
    spent_rows = db.execute(
        "SELECT category, SUM(amount) as total FROM expenses WHERE user_id = ? AND date LIKE ? GROUP BY category",
        (user_id, f"{month}%"),
    ).fetchall()
    spent = {r["category"]: r["total"] for r in spent_rows}

    result = []
    for category, limit in budgets.items():
        amount_spent = spent.get(category, 0.0)
        pct = (amount_spent / limit * 100) if limit > 0 else 0.0
        status = "critical" if pct >= 100 else "warning" if pct >= 80 else "good"
        result.append(
            {
                "category": category,
                "limit": limit,
                "spent": round(amount_spent, 2),
                "pct": round(pct, 1),
                "status": status,
            }
        )
    result.sort(key=lambda r: r["pct"], reverse=True)
    return result
