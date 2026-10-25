# SignalDesk

[![CI](https://github.com/PaoloFer/signaldesk/actions/workflows/ci.yml/badge.svg)](https://github.com/PaoloFer/signaldesk/actions/workflows/ci.yml)

SignalDesk is a self-hosted social intelligence MVP for building and analyzing research samples from public YouTube data.

Given a topic, channel seeds, or video seeds, it collects a bounded corpus and exposes channel metrics, content formats, recurring language, observed commenter overlap, growth snapshots, and commercial signals. The interface separates observed data, calculated metrics, and heuristic indicators instead of presenting them as equivalent facts.

> **Status:** public beta / portfolio project. Results describe the collected sample, not the entire platform or market.

## What It Does

- Builds research samples from queries, channel handles, channel IDs, and video URLs.
- Filters candidates by date, region, language, subscriber range, and public metrics.
- Aggregates videos into reusable channel profiles with evidence records.
- Extracts explainable TF-IDF themes and channel-to-niche similarity.
- Compares niches, channels, formats, vocabulary, and observed commenters.
- Tracks metric snapshots and content growth over time.
- Screens for sponsorship, affiliate, product-placement, and disclosure signals.
- Runs long operations through persistent background jobs.
- Supports isolated organizations, projects, sessions, and exports.
- Exposes an account-free, rate-limited public preview at `/try`.

## Public Beta Flow

```text
Topic + optional seeds
        ↓
YouTube discovery
        ↓
Bounded sample of videos and channels
        ↓
Descriptive metrics and evidence
        ↓
Account required only to save or deepen the analysis
```

The anonymous preview is deliberately limited: no comments, transcripts, persistence, or definitive semantic claims.

## Architecture

```text
Browser
   ↓
Caddy / HTTPS
   ↓
FastAPI API + static frontend
   ├── Public preview
   ├── Authenticated workspace
   └── Report endpoints
          ↓
PostgreSQL / SQLite
   ├── projects, niches, contents, comments
   ├── snapshots, entities, ad signals
   └── jobs, sources, sessions
          ↑
Worker + Redis coordination
          ↓
YouTube Data API v3
```

More detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Explainable Analytics

The default semantic pipeline uses TF-IDF rather than requiring an external model:

- channel descriptions, titles, tags, and video descriptions become evidence documents;
- cosine similarity produces a niche-fit component;
- shared terms remain visible in the score breakdown;
- size, popularity, engagement, geography, and optional velocity remain separate components;
- emerging circles are multi-label and derived from the observed pool.

Optional multilingual embeddings can be enabled, with deterministic TF-IDF fallback.

Method definitions and limitations: [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## API Quota Optimization

Known channels are enriched through their YouTube upload playlists rather than a separate `search.list` request per channel:

```text
channels.list → uploads playlist → playlistItems.list → batched videos.list
```

This preserves expensive search calls for actual discovery. Quota usage is tracked by operation and checked before costly jobs are accepted.

## Technology

| Area | Stack |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic |
| Persistence | PostgreSQL 16, SQLite, SQLAlchemy 2, Alembic |
| Jobs | asyncio worker, Redis coordination |
| Frontend | HTML, CSS, vanilla JavaScript |
| Analytics | TF-IDF, cosine similarity, Jaccard, median/MAD, rule-based NLP |
| Deployment | Docker, Docker Compose, Caddy |
| Testing | pytest/unittest, schema and static frontend contracts |

## Local Setup

### 1. Create the environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set a YouTube Data API v3 key and a stable local pseudonym salt in `.env`:

```dotenv
YOUTUBE_API_KEY=your-server-key
PSEUDONYM_SALT=use-a-long-random-local-secret
COOKIE_SECURE=false
```

### 2. Start the application

```powershell
uvicorn app.main:app --reload --port 8090
```

Open:

- landing: `http://127.0.0.1:8090/`
- public preview: `http://127.0.0.1:8090/try`
- authenticated workspace: `http://127.0.0.1:8090/app`
- health check: `http://127.0.0.1:8090/api/health`

The default local setup uses SQLite. Production uses PostgreSQL and Redis.

## Docker Development

```powershell
docker compose up --build
```

The local override publishes the app on port `8090`. Production adds Caddy, HTTPS, a dedicated worker, and migration ordering.

Deployment guide: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

Current baseline: **245 passing tests** covering authentication, project isolation, migrations, jobs, quota accounting, YouTube mapping, niche discovery, semantic profiling, ADV analysis, public preview, and frontend contracts.

## Analysis Scripts

Generate an Italian creator sample with a curated seed registry and sector queries:

```powershell
python scripts/analyze_italian_creators.py \
  --days 365 \
  --max-results 300 \
  --max-channels 100 \
  --min-subscribers 10000
```

Generated reports are written under `reports/` and intentionally excluded from Git.

The curated seed registry is stored in `data/italian_creator_seeds.json`; it is an explicit starting set, not a claim of complete market coverage.

## Project Structure

```text
app/                 FastAPI application, analytics, jobs, connectors
alembic/             versioned database migrations
data/                synthetic demo data and curated public seed IDs
deploy/              Caddy configuration
docs/                architecture, methodology, deployment, roadmap
scripts/             backups, migrations, deployment, analysis utilities
static/              landing, public preview, authenticated dashboard
tests/               unit, integration, migration, and frontend contracts
```

## Boundaries

- YouTube is the only complete live connector; other platforms can be imported by CSV.
- Public views do not equal campaign impressions or creator analytics.
- Commenter overlap does not equal total audience overlap.
- Sentiment, toxicity, anomaly, and ADV outputs are screening indicators.
- Channel country and language are optional creator-provided metadata.
- Reports are only as complete as the search queries, seeds, period, and API coverage.
- Recommendation and depth-graph features are roadmap items, not current claims.

## Development Approach

This project was developed iteratively with AI-assisted tooling. Product scope, architecture decisions, data-quality checks, test design, and output validation were treated as first-class work; generated code was not considered complete until it was inspected and covered by repeatable tests.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- [`docs/ROADMAP.md`](docs/ROADMAP.md)
- [`SECURITY.md`](SECURITY.md)
