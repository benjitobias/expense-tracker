# Expenses

A single-user expense tracker: FastAPI + SQLite backend, mobile-first frontend
with three tabs — Home (log & browse expenses), Insights (spending trends,
day-of-week patterns), Budgets (per-category limits with over/near alerts).

## Run it

```
docker build -t expenses .
docker run -d \
  --name expenses \
  -p 8000:8000 \
  -e APP_PASSWORD=changeme \
  -v expenses-data:/data \
  --restart unless-stopped \
  expenses
```

Open `http://<server-ip>:8000` and log in with `APP_PASSWORD`.

- `APP_PASSWORD` is required — the container refuses to start without it.
- `-v expenses-data:/data` persists the SQLite database (`/data/expenses.db`)
  across container restarts/rebuilds. Without it, deleting the container
  deletes your data.
- If you put this behind an HTTPS reverse proxy (recommended if reachable
  from outside your home network), also set `-e SECURE_COOKIES=true` so the
  session cookie is marked `Secure`.

## Local development

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
APP_PASSWORD=dev DB_PATH=./data/expenses.db uvicorn app.main:app --reload
```

## Notes / known trade-offs

- Auth is a single shared password (no per-user accounts) with a signed
  session cookie, 30-day expiry, and a basic per-IP lockout after 5 failed
  attempts/minute. Sessions live in memory, so a container restart logs
  everyone out — fine for a personal tool, mention if that becomes annoying.
- Categories are a fixed list (Food, Transport, Shopping, Entertainment,
  Health, Housing, Utilities, Other) rather than user-defined, to keep the
  add-expense form and charts simple.
