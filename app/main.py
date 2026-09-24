import io
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from . import analytics, auth, database
from .models import (
    CATEGORIES,
    BudgetIn,
    CategoryIn,
    ChangePasswordIn,
    ExpenseIn,
    ExpenseOut,
    FeedbackIn,
    FeedbackOut,
    FeedbackStatusIn,
    LoginIn,
    PhotoOut,
    SessionIn,
    SessionOut,
    ThemeIn,
)

MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_PHOTOS_PER_EXPENSE = 5
PHOTO_EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
}


def _user_categories(db: sqlite3.Connection, user_id: int) -> set[str]:
    custom = {
        r["name"] for r in db.execute(
            "SELECT name FROM custom_categories WHERE user_id = ?", (user_id,)
        ).fetchall()
    }
    return set(CATEGORIES) | custom


def _user_theme(db: sqlite3.Connection, user_id: int) -> str:
    row = db.execute("SELECT theme FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or row["theme"] is None:
        return "system"
    return row["theme"]


def _active_session(db: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = db.execute(
        "SELECT sessions.* FROM sessions JOIN users ON users.active_session_id = sessions.id "
        "WHERE users.id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="No active session")
    return row


def _session_out(row: sqlite3.Row, active_id: int) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "currency": row["currency"],
        "status": row["status"],
        "is_standard": bool(row["is_standard"]),
        "is_active": row["id"] == active_id,
        "created_at": row["created_at"],
        "closed_at": row["closed_at"],
    }


def _photos_for_expenses(db: sqlite3.Connection, expense_ids: list[int]) -> dict[int, list[dict]]:
    if not expense_ids:
        return {}
    placeholders = ",".join("?" * len(expense_ids))
    rows = db.execute(
        f"SELECT id, expense_id, content_type FROM expense_photos "
        f"WHERE expense_id IN ({placeholders}) ORDER BY id",
        expense_ids,
    ).fetchall()
    by_expense: dict[int, list[dict]] = {}
    for r in rows:
        by_expense.setdefault(r["expense_id"], []).append({"id": r["id"], "content_type": r["content_type"]})
    return by_expense


def _expense_with_photos(db: sqlite3.Connection, row: sqlite3.Row) -> dict:
    data = dict(row)
    data["photos"] = _photos_for_expenses(db, [row["id"]]).get(row["id"], [])
    return data


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth.check_startup()
    database.init_db()
    conn = database.get_connection()
    try:
        auth.ensure_users_seeded(conn)
        database.ensure_sessions(conn)
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
        "SELECT id, username, password_hash, theme FROM users WHERE username = ?", (payload.username,)
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
    return {"ok": True, "username": user.username, "theme": row["theme"] or "system"}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE_NAME)
    if token:
        auth.destroy_session(token)
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
def me(
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    return {"ok": True, "username": user.username, "theme": _user_theme(db, user.id)}


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


@app.put("/api/theme")
def set_theme(
    payload: ThemeIn,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    stored = None if payload.theme == "system" else payload.theme
    db.execute("UPDATE users SET theme = ? WHERE id = ?", (stored, user.id))
    db.commit()
    return {"theme": payload.theme}


# ------------------------------------------------------------- sessions ----
# A "session" scopes expenses/budgets/analytics/export to one currency and
# one pool of spending — the household's ongoing "Standard" session (always
# present, can't be closed) plus any number of trip sessions you switch into.
# Whichever session is active is what every other endpoint below reads from
# and writes to; there's no per-request session override.

@app.get("/api/sessions", response_model=list[SessionOut])
def list_sessions(
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    active = _active_session(db, user.id)
    rows = db.execute(
        "SELECT * FROM sessions WHERE user_id = ? ORDER BY is_standard DESC, created_at DESC",
        (user.id,),
    ).fetchall()
    return [_session_out(r, active["id"]) for r in rows]


@app.post("/api/sessions", response_model=SessionOut, status_code=201)
def create_session(
    payload: SessionIn,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    created_at = datetime.utcnow().isoformat()
    cur = db.execute(
        "INSERT INTO sessions (user_id, name, currency, status, is_standard, created_at) "
        "VALUES (?, ?, ?, 'open', 0, ?)",
        (user.id, payload.name, payload.currency, created_at),
    )
    db.execute("UPDATE users SET active_session_id = ? WHERE id = ?", (cur.lastrowid, user.id))
    db.commit()
    row = db.execute("SELECT * FROM sessions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _session_out(row, cur.lastrowid)


@app.post("/api/sessions/{session_id}/activate", response_model=SessionOut)
def activate_session(
    session_id: int,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    row = db.execute(
        "SELECT * FROM sessions WHERE id = ? AND user_id = ?", (session_id, user.id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    db.execute("UPDATE users SET active_session_id = ? WHERE id = ?", (session_id, user.id))
    db.commit()
    return _session_out(row, session_id)


@app.post("/api/sessions/{session_id}/close", response_model=SessionOut)
def close_session(
    session_id: int,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    row = db.execute(
        "SELECT * FROM sessions WHERE id = ? AND user_id = ?", (session_id, user.id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    if row["is_standard"]:
        raise HTTPException(status_code=400, detail="The Standard session can't be closed")
    db.execute(
        "UPDATE sessions SET status = 'closed', closed_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), session_id),
    )
    db.commit()
    active = _active_session(db, user.id)
    row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_out(row, active["id"])


@app.post("/api/sessions/{session_id}/reopen", response_model=SessionOut)
def reopen_session(
    session_id: int,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    row = db.execute(
        "SELECT * FROM sessions WHERE id = ? AND user_id = ?", (session_id, user.id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    db.execute("UPDATE sessions SET status = 'open', closed_at = NULL WHERE id = ?", (session_id,))
    db.commit()
    active = _active_session(db, user.id)
    row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_out(row, active["id"])


# ------------------------------------------------------------ expenses ----

@app.get("/api/expenses", response_model=list[ExpenseOut])
def list_expenses(
    month: str,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    session = _active_session(db, user.id)
    rows = db.execute(
        "SELECT * FROM expenses WHERE user_id = ? AND session_id = ? AND date LIKE ? "
        "ORDER BY date DESC, id DESC",
        (user.id, session["id"], f"{month}%"),
    ).fetchall()
    photos_by_expense = _photos_for_expenses(db, [r["id"] for r in rows])
    return [{**dict(r), "photos": photos_by_expense.get(r["id"], [])} for r in rows]


SEARCH_RESULT_LIMIT = 100


@app.get("/api/expenses/search", response_model=list[ExpenseOut])
def search_expenses(
    q: str,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    term = q.strip()
    if not term:
        return []
    session = _active_session(db, user.id)
    like = f"%{term}%"
    rows = db.execute(
        "SELECT * FROM expenses WHERE user_id = ? AND session_id = ? AND ("
        "description LIKE ? OR note LIKE ? OR location LIKE ? OR category LIKE ? OR payment_method LIKE ?"
        ") ORDER BY date DESC, id DESC LIMIT ?",
        (user.id, session["id"], like, like, like, like, like, SEARCH_RESULT_LIMIT),
    ).fetchall()
    photos_by_expense = _photos_for_expenses(db, [r["id"] for r in rows])
    return [{**dict(r), "photos": photos_by_expense.get(r["id"], [])} for r in rows]


@app.post("/api/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(
    payload: ExpenseIn,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    if payload.category not in _user_categories(db, user.id):
        raise HTTPException(status_code=400, detail="Unknown category")
    session = _active_session(db, user.id)
    if session["status"] != "open":
        raise HTTPException(status_code=400, detail="This session is closed — reopen it to add expenses")
    created_at = datetime.utcnow().isoformat()
    cur = db.execute(
        "INSERT INTO expenses "
        "(user_id, session_id, amount, description, category, location, note, payment_method, date, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            user.id, session["id"], payload.amount, payload.description, payload.category,
            payload.location, payload.note, payload.payment_method, payload.date.isoformat(), created_at,
        ),
    )
    db.commit()
    row = db.execute("SELECT * FROM expenses WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _expense_with_photos(db, row)


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
    if payload.category not in _user_categories(db, user.id):
        raise HTTPException(status_code=400, detail="Unknown category")
    db.execute(
        "UPDATE expenses SET amount=?, description=?, category=?, location=?, note=?, "
        "payment_method=?, date=? WHERE id=?",
        (
            payload.amount, payload.description, payload.category,
            payload.location, payload.note, payload.payment_method, payload.date.isoformat(), expense_id,
        ),
    )
    db.commit()
    row = db.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    return _expense_with_photos(db, row)


@app.delete("/api/expenses/{expense_id}", status_code=204)
def delete_expense(
    expense_id: int,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    photos = db.execute(
        "SELECT filename FROM expense_photos WHERE expense_id = ? AND user_id = ?",
        (expense_id, user.id),
    ).fetchall()
    result = db.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, user.id))
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Expense not found")
    for p in photos:
        path = os.path.join(database.uploads_dir(), p["filename"])
        if os.path.isfile(path):
            os.remove(path)
    return Response(status_code=204)


# -------------------------------------------------------- expense photos ----

@app.post("/api/expenses/{expense_id}/photos", response_model=list[PhotoOut], status_code=201)
async def upload_expense_photos(
    expense_id: int,
    files: list[UploadFile] = File(...),
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    existing = db.execute(
        "SELECT id FROM expenses WHERE id = ? AND user_id = ?", (expense_id, user.id)
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Expense not found")

    current_count = db.execute(
        "SELECT COUNT(*) AS n FROM expense_photos WHERE expense_id = ?", (expense_id,)
    ).fetchone()["n"]
    if current_count + len(files) > MAX_PHOTOS_PER_EXPENSE:
        raise HTTPException(
            status_code=400, detail=f"An expense can have at most {MAX_PHOTOS_PER_EXPENSE} attachments"
        )

    # Validate and read everything up front so a bad file in the batch
    # doesn't leave earlier ones written to disk without a DB row.
    to_save: list[tuple[str, bytes]] = []
    for file in files:
        if file.content_type not in PHOTO_EXTENSION_BY_CONTENT_TYPE:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file.content_type}. Use a photo (JPEG/PNG/WebP/GIF) or a PDF.",
            )
        data = await file.read()
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(status_code=400, detail="Each file must be 5MB or smaller")
        to_save.append((file.content_type, data))

    created = []
    created_at = datetime.utcnow().isoformat()
    for content_type, data in to_save:
        filename = f"{uuid4().hex}{PHOTO_EXTENSION_BY_CONTENT_TYPE[content_type]}"
        with open(os.path.join(database.uploads_dir(), filename), "wb") as f:
            f.write(data)
        cur = db.execute(
            "INSERT INTO expense_photos (expense_id, user_id, filename, content_type, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (expense_id, user.id, filename, content_type, created_at),
        )
        created.append({"id": cur.lastrowid, "content_type": content_type})
    db.commit()
    return created


@app.get("/api/expenses/{expense_id}/photos/{photo_id}")
def get_expense_photo(
    expense_id: int,
    photo_id: int,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    row = db.execute(
        "SELECT filename, content_type FROM expense_photos "
        "WHERE id = ? AND expense_id = ? AND user_id = ?",
        (photo_id, expense_id, user.id),
    ).fetchone()
    path = os.path.join(database.uploads_dir(), row["filename"]) if row else None
    if not row or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(path, media_type=row["content_type"])


@app.delete("/api/expenses/{expense_id}/photos/{photo_id}", status_code=204)
def delete_expense_photo(
    expense_id: int,
    photo_id: int,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    row = db.execute(
        "SELECT filename FROM expense_photos WHERE id = ? AND expense_id = ? AND user_id = ?",
        (photo_id, expense_id, user.id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Photo not found")
    db.execute("DELETE FROM expense_photos WHERE id = ?", (photo_id,))
    db.commit()
    path = os.path.join(database.uploads_dir(), row["filename"])
    if os.path.isfile(path):
        os.remove(path)
    return Response(status_code=204)


# ------------------------------------------------------------- budgets ----

@app.get("/api/budgets")
def list_budgets(
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    session = _active_session(db, user.id)
    rows = db.execute(
        "SELECT * FROM budgets WHERE user_id = ? AND session_id = ?", (user.id, session["id"])
    ).fetchall()
    return {r["category"]: r["monthly_limit"] for r in rows}


@app.put("/api/budgets/{category}")
def set_budget(
    category: str,
    payload: BudgetIn,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    if category not in _user_categories(db, user.id):
        raise HTTPException(status_code=400, detail="Unknown category")
    session = _active_session(db, user.id)
    existing = db.execute(
        "SELECT 1 FROM budgets WHERE session_id = ? AND category = ?", (session["id"], category)
    ).fetchone()
    if existing:
        db.execute(
            "UPDATE budgets SET monthly_limit = ? WHERE session_id = ? AND category = ?",
            (payload.monthly_limit, session["id"], category),
        )
    else:
        db.execute(
            "INSERT INTO budgets (user_id, session_id, category, monthly_limit) VALUES (?, ?, ?, ?)",
            (user.id, session["id"], category, payload.monthly_limit),
        )
    db.commit()
    return {"category": category, "monthly_limit": payload.monthly_limit}


@app.delete("/api/budgets/{category}", status_code=204)
def delete_budget(
    category: str,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    session = _active_session(db, user.id)
    db.execute(
        "DELETE FROM budgets WHERE category = ? AND session_id = ?", (category, session["id"])
    )
    db.commit()
    return Response(status_code=204)


# ----------------------------------------------------------- categories ----

@app.get("/api/categories")
def list_categories(
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    custom = [
        r["name"] for r in db.execute(
            "SELECT name FROM custom_categories WHERE user_id = ? ORDER BY name", (user.id,)
        ).fetchall()
    ]
    return {"builtin": CATEGORIES, "custom": custom}


@app.post("/api/categories")
def create_category(
    payload: CategoryIn,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Category name is required")

    # Case-insensitively fold into an existing builtin or custom category
    # rather than creating a near-duplicate, so "food" reuses "Food".
    for builtin in CATEGORIES:
        if builtin.lower() == name.lower():
            return {"name": builtin}
    existing = db.execute(
        "SELECT name FROM custom_categories WHERE user_id = ? AND lower(name) = lower(?)",
        (user.id, name),
    ).fetchone()
    if existing:
        return {"name": existing["name"]}

    db.execute(
        "INSERT INTO custom_categories (user_id, name, created_at) VALUES (?, ?, ?)",
        (user.id, name, datetime.utcnow().isoformat()),
    )
    db.commit()
    return {"name": name}


# ----------------------------------------------------------- analytics ----

@app.get("/api/analytics/trends")
def trends(
    months: int = 6,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    session = _active_session(db, user.id)
    return analytics.monthly_trends(db, months, session["id"])


@app.get("/api/analytics/patterns")
def patterns(
    months: int = 3,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    session = _active_session(db, user.id)
    return analytics.day_of_week_patterns(db, months, session["id"])


@app.get("/api/analytics/daily")
def daily(
    month: str,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    session = _active_session(db, user.id)
    return analytics.daily_totals(db, month, session["id"])


@app.get("/api/analytics/budget-status")
def budget_status_endpoint(
    month: str,
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    session = _active_session(db, user.id)
    return analytics.budget_status(db, month, session["id"])


# --------------------------------------------------------------- export ----

@app.get("/api/export/expenses.xlsx")
def export_expenses(
    user: auth.SessionUser = Depends(auth.require_auth),
    db: sqlite3.Connection = Depends(database.db_dependency),
):
    session = _active_session(db, user.id)
    rows = db.execute(
        "SELECT date, category, description, location, amount FROM expenses "
        "WHERE user_id = ? AND session_id = ? ORDER BY date, id",
        (user.id, session["id"]),
    ).fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = "Expenses"

    headers = ["Date", "Category", "Description", "Location", f"Amount ({session['currency']})"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for r in rows:
        ws.append([r["date"], r["category"], r["description"], r["location"] or "", r["amount"]])

    for cell in ws["E"][1:]:
        cell.number_format = "#,##0.00"

    if rows:
        total_row = len(rows) + 2
        ws.cell(row=total_row, column=1, value="Total").font = Font(bold=True)
        total_cell = ws.cell(row=total_row, column=5, value=f"=SUM(E2:E{total_row - 1})")
        total_cell.font = Font(bold=True)
        total_cell.number_format = "#,##0.00"

    for i, width in enumerate([12, 16, 32, 20, 14], start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=expenses.xlsx"},
    )


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
