import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles

from . import analytics, auth, database
from .models import (
    CATEGORIES,
    BudgetIn,
    ExpenseIn,
    ExpenseOut,
    FeedbackIn,
    FeedbackOut,
    FeedbackStatusIn,
    LoginIn,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth.check_startup()
    database.init_db()
    yield


app = FastAPI(title="Expenses", lifespan=lifespan)


# ---------------------------------------------------------------- auth ----

@app.post("/api/login")
def login(payload: LoginIn, request: Request, response: Response):
    if auth.is_locked_out(request):
        raise HTTPException(status_code=429, detail="Too many attempts, try again in a minute")
    if not auth.verify_password(payload.password):
        auth.record_failed_attempt(request)
        raise HTTPException(status_code=401, detail="Incorrect password")
    token = auth.create_session()
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=auth.SECURE_COOKIES,
        max_age=auth.SESSION_TTL,
    )
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE_NAME)
    if token:
        auth.destroy_session(token)
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
def me(_: None = Depends(auth.require_auth)):
    return {"ok": True}


# ------------------------------------------------------------ expenses ----

@app.get("/api/expenses", response_model=list[ExpenseOut])
def list_expenses(
    month: str,
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    rows = db.execute(
        "SELECT * FROM expenses WHERE date LIKE ? ORDER BY date DESC, id DESC",
        (f"{month}%",),
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(
    payload: ExpenseIn,
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    created_at = datetime.utcnow().isoformat()
    cur = db.execute(
        "INSERT INTO expenses (amount, description, category, date, created_at) VALUES (?,?,?,?,?)",
        (payload.amount, payload.description, payload.category, payload.date.isoformat(), created_at),
    )
    db.commit()
    row = db.execute("SELECT * FROM expenses WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.put("/api/expenses/{expense_id}", response_model=ExpenseOut)
def update_expense(
    expense_id: int,
    payload: ExpenseIn,
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    existing = db.execute("SELECT id FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Expense not found")
    db.execute(
        "UPDATE expenses SET amount=?, description=?, category=?, date=? WHERE id=?",
        (payload.amount, payload.description, payload.category, payload.date.isoformat(), expense_id),
    )
    db.commit()
    row = db.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    return dict(row)


@app.delete("/api/expenses/{expense_id}", status_code=204)
def delete_expense(
    expense_id: int,
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    result = db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Expense not found")
    return Response(status_code=204)


# ------------------------------------------------------------- budgets ----

@app.get("/api/budgets")
def list_budgets(
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    rows = db.execute("SELECT * FROM budgets").fetchall()
    return {r["category"]: r["monthly_limit"] for r in rows}


@app.put("/api/budgets/{category}")
def set_budget(
    category: str,
    payload: BudgetIn,
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Unknown category")
    db.execute(
        "INSERT INTO budgets (category, monthly_limit) VALUES (?, ?) "
        "ON CONFLICT(category) DO UPDATE SET monthly_limit = excluded.monthly_limit",
        (category, payload.monthly_limit),
    )
    db.commit()
    return {"category": category, "monthly_limit": payload.monthly_limit}


@app.delete("/api/budgets/{category}", status_code=204)
def delete_budget(
    category: str,
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    db.execute("DELETE FROM budgets WHERE category = ?", (category,))
    db.commit()
    return Response(status_code=204)


# ----------------------------------------------------------- analytics ----

@app.get("/api/analytics/trends")
def trends(
    months: int = 6,
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    return analytics.monthly_trends(db, months)


@app.get("/api/analytics/patterns")
def patterns(
    months: int = 3,
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    return analytics.day_of_week_patterns(db, months)


@app.get("/api/analytics/budget-status")
def budget_status_endpoint(
    month: str,
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    return analytics.budget_status(db, month)


# ------------------------------------------------------------ feedback ----

@app.get("/api/feedback", response_model=list[FeedbackOut])
def list_feedback(
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    rows = db.execute(
        "SELECT * FROM feedback ORDER BY (status = 'done') ASC, id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/feedback", response_model=FeedbackOut, status_code=201)
def create_feedback(
    payload: FeedbackIn,
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    created_at = datetime.utcnow().isoformat()
    cur = db.execute(
        "INSERT INTO feedback (kind, text, status, created_at) VALUES (?, ?, 'open', ?)",
        (payload.kind, payload.text, created_at),
    )
    db.commit()
    row = db.execute("SELECT * FROM feedback WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.patch("/api/feedback/{feedback_id}", response_model=FeedbackOut)
def update_feedback_status(
    feedback_id: int,
    payload: FeedbackStatusIn,
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    existing = db.execute("SELECT id FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    db.execute("UPDATE feedback SET status = ? WHERE id = ?", (payload.status, feedback_id))
    db.commit()
    row = db.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
    return dict(row)


@app.delete("/api/feedback/{feedback_id}", status_code=204)
def delete_feedback(
    feedback_id: int,
    _: None = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    result = db.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    return Response(status_code=204)


# -------------------------------------------------------- static files ----
# Mounted last so it doesn't shadow the /api routes above. The frontend is a
# single-page app that self-gates on /api/me, so the static files are public
# but useless without a valid session cookie.

app.mount("/", StaticFiles(directory="static", html=True), name="static")
