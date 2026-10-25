# Architecture

SignalDesk is a modular monolith with a separate worker process. The same application image runs API, migration, and worker commands.

## Runtime Components

```text
Internet
   ↓
Caddy (TLS, compression, security headers)
   ↓
FastAPI
   ├── public pages and preview
   ├── authenticated JSON API
   └── static dashboard
        ↓                 ↓
PostgreSQL             Redis
        ↑                 ↑
        └──── Worker ──────┘
                 ↓
         YouTube Data API
```

## Application Modules

| Module | Responsibility |
|---|---|
| `app/main.py` | HTTP routes, middleware, response contracts |
| `app/database.py` | storage adapter and data access functions |
| `app/models.py` | SQLAlchemy schema definition |
| `app/youtube.py` | YouTube mapping, quota accounting, pagination |
| `app/connectors.py` | social connector interface |
| `app/jobs.py` | background job handlers |
| `app/worker.py` | job and monitoring loops |
| `app/niche_discovery.py` | seed expansion and channel aggregation |
| `app/channel_profiling.py` | TF-IDF profiles, scores, circles |
| `app/content_intelligence.py` | content landscape reports |
| `app/adv_intelligence.py` | sponsor and commercial-signal aggregation |
| `app/ad_detector.py` | six-level advertising evidence engine |
| `app/intelligence.py` | temporal activity and repeated-text indicators |

## Data Flow

```text
query / channel / video seeds
        ↓
connector resolution and collection
        ↓
content normalization and deduplication
        ↓
project and niche membership
        ↓
channel aggregation and semantic profiles
        ↓
reports, exports, and snapshots
```

## Persistence

- SQLite is used for local development and tests.
- PostgreSQL is the production backend.
- Alembic owns production schema changes.
- Redis coordinates scheduled work; persistent job state remains in the database.
- Public anonymous previews are non-persistent.

## Security Model

- Session tokens are random and stored only as hashes.
- Passwords use salted PBKDF2-SHA256.
- Projects belong to organizations and endpoints enforce project access.
- Production cookies are `HttpOnly`, `SameSite=Lax`, and `Secure`.
- Mutating API calls validate the configured public Origin.
- PostgreSQL and Redis are not exposed by the production Compose stack.

## Scaling Path

The initial deployment targets one VPS. The application and worker are already separate services, allowing later migration of PostgreSQL, Redis, or workers without changing the public API.
