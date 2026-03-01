# NicksWatchService

A production-quality web app that daily searches multiple marketplaces for used watch listings, syncs the watch list from a Google Sheet, persists results in a local database, and displays them in a clean web UI — accessible remotely via Cloudflare Tunnel.

## Tech Stack

- **Backend**: FastAPI + Python 3.12
- **Database**: SQLite (via aiosqlite) — swap to Postgres with one env var
- **ORM/Migrations**: SQLAlchemy 2.0 async + Alembic
- **Scheduler**: APScheduler (in-process daily job)
- **Frontend**: Jinja2 + HTMX + TailwindCSS CDN
- **Sources**: eBay Browse API, Chrono24, Mercari JP, Yahoo JP (Playwright), Serper web search
- **LLM verification**: Claude claude-sonnet-4-6 (ambiguous listing confidence scoring)
- **Remote access**: Cloudflare Tunnel

---

## Quick Start (local, no Docker)

### 1. Install dependencies

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys and tokens
```

Generate a random `RUN_TOKEN`:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Create the database

```bash
mkdir -p data
alembic upgrade head
```

### 4. Run the app

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open [http://localhost:8000](http://localhost:8000)

---

## Docker

```bash
cp .env.example .env
# Edit .env

docker compose up --build
```

The SQLite database is stored in `./data/watchservice.db` (volume-mounted).

---

## Google Sheets Setup

1. Create a Google Sheet with columns:
   `brand | model | references_csv | query_terms | required_keywords | forbidden_keywords | enabled`

2. Run the GCP setup script (requires `gcloud` CLI):
   ```bash
   GCP_PROJECT_ID=your-project-id bash scripts/setup_gcp.sh
   ```

3. Share your Sheet with the service account email shown at the end of the script (Viewer role).

4. Set in `.env`:
   ```
   GOOGLE_SHEET_ID=<your-sheet-id>
   GOOGLE_SERVICE_ACCOUNT_JSON=/app/secrets/service_account.json
   ```

---

## Cloudflare Tunnel (remote access)

```bash
CF_HOSTNAME=watches.yourdomain.com bash scripts/setup_tunnel.sh
cloudflared tunnel run nicks-watch-service
```

---

## API Reference

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/runs/trigger` | `X-Run-Token` header | Trigger a search run |
| `GET` | `/api/runs/latest` | — | Get latest run (JSON) |
| `DELETE` | `/api/listings/{id}` | — | Remove a listing |
| `GET` | `/health` | — | Health check |

---

## Adding a New Source

See [docs/add_adapter.md](docs/add_adapter.md).

---

## Environment Variables

See [.env.example](.env.example) for all options.

---

## Google Sheet Format

| Column | Required | Example | Notes |
|---|---|---|---|
| `brand` | ✅ | `Rolex` | |
| `model` | ✅ | `Submariner` | |
| `references_csv` | | `16610, 16610LN` | Comma-separated ref numbers |
| `query_terms` | | `stainless steel` | Extra search terms |
| `required_keywords` | | `["stainless"]` | JSON array — all must appear in title |
| `forbidden_keywords` | | `["parts only"]` | JSON array — any match rejects listing |
| `enabled` | | `1` | `0` or `false` to disable |
