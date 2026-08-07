# Expenses

A multi-user expense tracker: FastAPI + SQLite backend, mobile-first frontend
with three tabs — Home (log & browse expenses), Insights (spending trends,
day-of-week patterns), Budgets (per-category limits with over/near alerts).
Each person logs in with their own account; expenses and budgets are private
per user, while the Feedback tab is a shared bug/feature board.

## Run it standalone

```
docker build -t expenses .
docker run -d \
  --name expenses \
  -p 8000:8000 \
  -e USERS=alice:changeme,bob:changeme2 \
  -v expenses-data:/data \
  --restart unless-stopped \
  expenses
```

Open `http://<server-ip>:8000` and log in as `alice` / `changeme` (or any
other pair from `USERS`).

- `USERS` (or legacy `APP_PASSWORD`, see below) is required — the container
  refuses to start without at least one account configured.
- `USERS` is a comma-separated list of `username:password` pairs. It's only
  used to *create* accounts that don't exist yet — accounts already in the
  database are left alone, so redeploying with the same `USERS` value never
  resets someone's password. To add a family member later, add their pair
  and redeploy; to change a password, use the in-app Account section on the
  Feedback tab instead of editing `USERS`.
- `-v expenses-data:/data` persists the SQLite database (`/data/expenses.db`)
  across container restarts/rebuilds. Without it, deleting the container
  deletes your data.
- If you put this behind an HTTPS reverse proxy (recommended if reachable
  from outside your home network), also set `-e SECURE_COOKIES=true` so the
  session cookie is marked `Secure`.

### Upgrading from the single-password version

Older deployments used one shared `APP_PASSWORD` and had no per-user data.
On first boot after upgrading, the app automatically migrates in place:

1. All existing expenses/budgets/feedback are assigned to one account named
   `admin` (override the name with `LEGACY_USERNAME`), using your existing
   `APP_PASSWORD` as that account's password.
2. Any additional pairs in `USERS` are created as new, empty accounts.

Keep `APP_PASSWORD` set for that first boot so the migration has a password
to give the `admin` account; it's safe to remove afterward since it's not
read again once `admin` exists.

## Run it behind the shared reverse-proxy

Routing and TLS for this app are handled by the standalone `reverse-proxy`
project (see `../reverse-proxy/README.md`), not by anything in this repo or
in `working_bizint_ng`. This project only needs to join the network it
exposes:

1. **Set your accounts:**
   ```
   cp .env.example .env
   # edit .env — set real USERS pairs; SECURE_COOKIES=true is already set
   # since TLS terminates at the reverse proxy, not here
   ```
2. **Bring it up** (after `reverse-proxy` has been started at least once, so
   the `shared_proxy` network exists):
   ```
   docker compose up -d --build
   ```
   `docker-compose.yml` joins `expenses_web` to `shared_proxy` and publishes
   no host ports — it's only reachable through the reverse proxy.

Routing (`money.bizint.xyz` → `expenses_web:8000`) and the TLS cert are
already set up in `reverse-proxy/conf.d/money.conf` — see that project's
README for how to add another subdomain the same way in the future.

## Local development

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
USERS=dev:dev DB_PATH=./data/expenses.db uvicorn app.main:app --reload
```

## Tests

```
pip install -r requirements-dev.txt
pytest
```

Each test gets its own throwaway SQLite file and its own in-memory
session/lockout state (see `conftest.py`), so tests can run in any order
without touching `/data` or each other. Coverage: login/lockout/logout,
self-service password change, expense & budget CRUD plus per-user
isolation, the three analytics endpoints, the shared feedback board, and
the legacy single-password → multi-user migration path.

## Notes / known trade-offs

- Auth is per-user accounts (`USERS=username:password,...`) with hashed
  passwords (PBKDF2-SHA256), a signed session cookie, 30-day expiry, and a
  basic per-IP lockout after 5 failed attempts/minute. Sessions live in
  memory, so a container restart logs everyone out — fine for a personal
  tool, mention if that becomes annoying.
- Expenses and budgets are private per account. Feedback (bug/feature
  reports) is a shared board visible to every account, tagged with who
  filed each entry.
- There's no admin UI for managing accounts — new users are provisioned by
  adding them to `USERS` and redeploying; passwords are changed self-service
  from the in-app Account section (Management tab).
- Categories start from a fixed list (Food, Transport, Shopping,
  Entertainment, Health, Housing, Utilities, Other) but each account can add
  its own on the fly from the "+ Add new category" option in the add-expense
  form. Custom categories are private per account (like expenses/budgets),
  can be budgeted just like the built-ins, and there's no way to rename or
  remove one once added (add a fresh one and stop using the old one instead).
- Expenses can optionally record where the purchase was made, a free-text
  note, and up to 5 attachments (5MB each; JPEG/PNG/WebP/GIF or PDF) — all
  tucked behind a "+ Note, photo, or location" disclosure on the add-expense
  form since they're rarely needed. None of these are used in charts/
  filters, just shown on the expense itself. Attachments are saved to disk
  under `<dirname of DB_PATH>/uploads` (e.g. `/data/uploads`), so they're
  covered by the same `-v expenses-data:/data` volume as the database — no
  separate volume needed, but also no external backup unless that volume is
  backed up. Individual attachments can be removed without deleting the
  whole expense.
- Tapping an expense row opens it for editing (amount, description,
  category, date, location, note, attachments); tapping the delete button
  deletes it instead. Deleting an expense or an attachment always asks for
  confirmation first.
