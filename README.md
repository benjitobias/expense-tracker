# Expenses

A single-user expense tracker: FastAPI + SQLite backend, mobile-first frontend
with three tabs — Home (log & browse expenses), Insights (spending trends,
day-of-week patterns), Budgets (per-category limits with over/near alerts).

## Run it standalone

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

## Run it behind the shared reverse-proxy

Routing and TLS for this app are handled by the standalone `reverse-proxy`
project (see `../reverse-proxy/README.md`), not by anything in this repo or
in `working_bizint_ng`. This project only needs to join the network it
exposes:

1. **Set your password:**
   ```
   cp .env.example .env
   # edit .env — set a real APP_PASSWORD; SECURE_COOKIES=true is already set
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
