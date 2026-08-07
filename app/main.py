import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles

from . import analytics, auth, database
from .models import (
    CATEGORIES,
    BudgetIn,
    ChangePasswordIn,
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
    conn = database.get_connection()
    try:
        auth.ensure_users_seeded(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="Expenses", lifespan=lifespan)


# ---------------------------------------------------------------- auth ----

@app.post("/api/login")
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    if auth.is_locked_out(request):
        raise HTTPException(status_code=429, detail="Too many attempts, try again in a minute")

    row = db.execute(
        "SELECT id, username, password_hash FROM users WHERE username = ?", (payload.username,)
    ).fetchone()
    if row is None:
        auth.verify_unknown_user()
        auth.record_failed_attempt(request)
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    if not auth.verify_password(payload.password, row["password_hash"]):
        auth.record_failed_attempt(request)
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    user = auth.SessionUser(id=row["id"], username=row["username"])
    token = auth.create_session(user)
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=auth.SECURE_COOKIES,
        max_age=auth.SESSION_TTL,
    )
    return {"ok": True, "username": user.username}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE_NAME)
    if token:
        auth.destroy_session(token)
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
def me(user: auth.SessionUser = Depends(auth.require_auth)):
    return {"ok": True, "username": user.username}


@app.post("/api/change-password")
def change_password(
    payload: ChangePasswordIn,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    row = db.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()
    if not row or not auth.verify_password(payload.current_password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (auth.hash_password(payload.new_password), user.id),
    )
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------ expenses ----

@app.get("/api/expenses", response_model=list[ExpenseOut])
def list_expenses(
    month: str,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    rows = db.execute(
        "SELECT * FROM expenses WHERE user_id = ? AND date LIKE ? ORDER BY date DESC, id DESC",
        (user.id, f"{month}%"),
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(
    payload: ExpenseIn,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    created_at = datetime.utcnow().isoformat()
    cur = db.execute(
        "INSERT INTO expenses (user_id, amount, description, category, date, created_at) VALUES (?,?,?,?,?,?)",
        (user.id, payload.amount, payload.description, payload.category, payload.date.isoformat(), created_at),
    )
    db.commit()
    row = db.execute("SELECT * FROM expenses WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.put("/api/expenses/{expense_id}", response_model=ExpenseOut)
def update_expense(
    expense_id: int,
    payload: ExpenseIn,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    existing = db.execute(
        "SELECT id FROM expenses WHERE id = ? AND user_id = ?", (expense_id, user.id)
    ).fetchone()
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
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    result = db.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, user.id))
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Expense not found")
    return Response(status_code=204)


# ------------------------------------------------------------- budgets ----

@app.get("/api/budgets")
def list_budgets(
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    rows = db.execute("SELECT * FROM budgets WHERE user_id = ?", (user.id,)).fetchall()
    return {r["category"]: r["monthly_limit"] for r in rows}


@app.put("/api/budgets/{category}")
def set_budget(
    category: str,
    payload: BudgetIn,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Unknown category")
    db.execute(
        "INSERT INTO budgets (user_id, category, monthly_limit) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, category) DO UPDATE SET monthly_limit = excluded.monthly_limit",
        (user.id, category, payload.monthly_limit),
    )
    db.commit()
    return {"category": category, "monthly_limit": payload.monthly_limit}


@app.delete("/api/budgets/{category}", status_code=204)
def delete_budget(
    category: str,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    db.execute("DELETE FROM budgets WHERE category = ? AND user_id = ?", (category, user.id))
    db.commit()
    return Response(status_code=204)


# ----------------------------------------------------------- analytics ----

@app.get("/api/analytics/trends")
def trends(
    months: int = 6,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    return analytics.monthly_trends(db, months, user.id)


@app.get("/api/analytics/patterns")
def patterns(
    months: int = 3,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    return analytics.day_of_week_patterns(db, months, user.id)


@app.get("/api/analytics/budget-status")
def budget_status_endpoint(
    month: str,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    return analytics.budget_status(db, month, user.id)


# ------------------------------------------------------------ feedback ----
# Feedback is a shared household bug/feature board rather than per-user data:
# every account sees and can act on every entry, but each entry keeps a
# pointer to who filed it.

FEEDBACK_SELECT = (
    "SELECT feedback.*, users.username AS username FROM feedback "
    "LEFT JOIN users ON users.id = feedback.user_id"
)


@app.get("/api/feedback", response_model=list[FeedbackOut])
def list_feedback(
    _: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    rows = db.execute(
        f"{FEEDBACK_SELECT} ORDER BY (feedback.status = 'done') ASC, feedback.id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/feedback", response_model=FeedbackOut, status_code=201)
def create_feedback(
    payload: FeedbackIn,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    created_at = datetime.utcnow().isoformat()
    cur = db.execute(
        "INSERT INTO feedback (user_id, kind, text, status, created_at) VALUES (?, ?, ?, 'open', ?)",
        (user.id, payload.kind, payload.text, created_at),
    )
    db.commit()
    row = db.execute(f"{FEEDBACK_SELECT} WHERE feedback.id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.patch("/api/feedback/{feedback_id}", response_model=FeedbackOut)
def update_feedback_status(
    feedback_id: int,
    payload: FeedbackStatusIn,
    _: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    existing = db.execute("SELECT id FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    db.execute("UPDATE feedback SET status = ? WHERE id = ?", (payload.status, feedback_id))
    db.commit()
    row = db.execute(f"{FEEDBACK_SELECT} WHERE feedback.id = ?", (feedback_id,)).fetchone()
    return dict(row)


@app.delete("/api/feedback/{feedback_id}", status_code=204)
def delete_feedback(
    feedback_id: int,
    _: auth.SessionUser = Depends(auth.require_auth),
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
