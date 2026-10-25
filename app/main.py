from __future__ import annotations

import csv
import asyncio
import hashlib
import io
import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel
from redis import Redis

from app.database import (
    add_processing_log,
    add_transcription_credits,
    adv_entity_data,
    all_comments,
    all_contents,
    api_usage_summary,
    background_job,
    background_jobs,
    background_job,
    cancel_background_job,
    comment_analysis_summary,
    connect,
    comments_with_channel,
    content_entity_mentions,
    create_entity,
    create_niche,
    create_project,
    get_content_ad_signal,
    list_ad_signals,
    ad_report_summary,
    run_ad_detection_for_project,
    upsert_content_ad_signal,
    delete_entity,
    delete_niche,
    delete_project,
    delete_project_contents,
    delete_project_source,
    delete_user_sessions_except,
    enqueue_background_job,
    entity_mentions_summary,
    get_entity,
    get_niche,
    get_transcription_credits,
    initialize,
    insert_comments,
    list_entities,
    list_channel_profiles,
    list_niche_channels,
    list_niche_entities,
    list_niches,
    list_projects,
    list_transcripts,
    list_user_sessions,
    mark_source_enqueued,
    merge_entities,
    monitoring_runs as list_monitoring_runs,
    processing_logs as list_processing_logs,
    project_snapshots,
    project_source,
    project_sources as list_project_sources,
    reap_stalled_jobs,
    save_comment_analysis,
    search_comments,
    unprocessed_comments,
    update_entity,
    update_niche,
    create_creator_link,
    update_project_source,
    upsert_contents,
    upsert_contents_for_niche,
    upsert_project_source,
    user_can_access_project,
    sync_niche_channels,
)
from app.auth import (
    authenticate,
    change_password,
    login,
    logout,
    register,
    token_hash,
)
from app.ratelimit import FixedWindowRateLimiter, RateLimitExceeded, auth_rate_limiter
from app.adv_intelligence import (
    build_adv_report,
    build_adv_report_from_entities,
    build_suspicion_report,
    search_sponsor,
)
from app.connectors import YouTubeConnector
from app.content_intelligence import build_content_report
from app.db import ping_database
from app.niche_discovery import expand_niche, expand_niche_channels
from app.panorama import build_panorama
from app.channel_intelligence import build_channel_overlap
from app.intelligence import build_intelligence_report
from app.monitoring import perform_metrics_refresh
from app.transcription_intelligence import find_campaign_clusters
from app.sponsor_niches import build_sponsor_basin_profile, compare_sponsor_basins
from app.settings import settings
from app.worker import background_job_loop, monitoring_loop
from app.youtube import YouTubeAPIError, fetch_video_comments


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("signaldesk")

APP_VERSION = "0.2.0"
public_preview_rate_limiter = FixedWindowRateLimiter(
    settings.public_preview_daily_limit, 24 * 60 * 60,
)


def check_production_hardening() -> list[str]:
    """Verifica le impostazioni critiche quando APP_ENV=production (G3)."""
    warnings: list[str] = []
    if settings.app_env != "production":
        return warnings
    if not settings.cookie_secure:
        warnings.append("COOKIE_SECURE=false: i cookie di sessione viaggiano senza Secure")
    if settings.allow_registration:
        warnings.append("ALLOW_REGISTRATION=true: chiunque può creare un account")
    if not settings.public_origin:
        warnings.append("PUBLIC_ORIGIN non impostata: controllo origine CSRF disattivo")
    if settings.allowed_hosts == ("*",):
        warnings.append("ALLOWED_HOSTS=*: nessuna restrizione sugli host")
    if not os.getenv("PSEUDONYM_SALT"):
        warnings.append("PSEUDONYM_SALT non impostato: pseudonimi con salt di sviluppo")
    return warnings


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    for warning in check_production_hardening():
        logger.warning("Hardening produzione: %s", warning)
    reaped = await asyncio.to_thread(reap_stalled_jobs, settings.job_timeout_hours)
    if reaped:
        logger.warning("Marcati come falliti %s job rimasti attivi oltre il timeout", reaped)
    tasks = []
    if settings.run_inline_worker:
        tasks.append(asyncio.create_task(background_job_loop()))
        if settings.auto_refresh_hours and os.getenv("YOUTUBE_API_KEY"):
            tasks.append(asyncio.create_task(monitoring_loop()))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="SignalDesk", version=APP_VERSION, lifespan=lifespan)
if settings.allowed_hosts != ("*",):
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def is_quota_error(exc: YouTubeAPIError) -> bool:
    """True se l'errore YouTube indica quota giornaliera esaurita (C3)."""
    message = str(exc).lower()
    return "quota" in message


def is_integrity_error(exc: Exception) -> bool:
    """True per violazioni di vincoli su entrambi i backend (SQLite/Postgres)."""
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    return isinstance(exc, psycopg.errors.IntegrityError)


@app.exception_handler(YouTubeAPIError)
async def youtube_error_handler(_: Request, exc: YouTubeAPIError) -> JSONResponse:
    if is_quota_error(exc):
        return JSONResponse(
            {
                "detail": "Quota giornaliera YouTube API esaurita: riprova domani "
                          "o riduci le operazioni di ricerca.",
                "error": "quota_exceeded",
            },
            status_code=503,
        )
    return JSONResponse(
        {"detail": f"Errore YouTube API: {exc}", "error": "youtube_api_error"},
        status_code=502,
    )


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Errore non gestito su %s %s", request.method, request.url.path)
    project_id = request.query_params.get("project_id")
    if project_id and project_id.isdigit():
        try:
            await asyncio.to_thread(
                add_processing_log,
                int(project_id), "error",
                {
                    "endpoint": f"{request.method} {request.url.path}",
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        except Exception:
            logger.exception("Impossibile registrare l'errore in processing_logs")
    return JSONResponse(
        {"detail": f"Errore interno: {type(exc).__name__}: {exc}"},
        status_code=500,
    )


@app.middleware("http")
async def disable_development_cache(request: Request, call_next) -> Response:
    if (
        settings.public_origin
        and request.url.path.startswith("/api/")
        and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.headers.get("origin") != settings.public_origin
    ):
        return JSONResponse({"detail": "Origine della richiesta non consentita"}, status_code=403)
    request.state.user = authenticate(request.cookies.get("signaldesk_session"))
    public_api = {
        "/api/auth/login", "/api/auth/register", "/api/auth/status",
        "/api/health", "/api/public/preview",
    }
    if request.url.path.startswith("/api/") and request.url.path not in public_api and not request.state.user:
        return JSONResponse({"detail": "Autenticazione richiesta"}, status_code=401)
    response = await call_next(request)
    if request.url.path in {"/app", "/login", "/api/public/preview"}:
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path in {"/", "/try", "/robots.txt", "/sitemap.xml"}:
        response.headers["Cache-Control"] = "public, max-age=3600"
    elif request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' "
        "https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
    if settings.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


class CSVImport(BaseModel):
    csv_text: str
    project_id: int = 1


class YouTubeImport(BaseModel):
    video: str
    niche: str
    topic: str = ""
    max_comments: int = 200
    project_id: int = 1
    include_replies: bool = False


class YouTubeDiscovery(BaseModel):
    query: str
    niche: str
    topic: str = ""
    days: int = 30
    max_results: int = 25
    project_id: int = 1


class YouTubeRefresh(BaseModel):
    niche: str | None = None
    limit: int = 200
    project_id: int | None = None


class YouTubeBulkComments(BaseModel):
    project_id: int = 1
    niche: str | None = None
    video_limit: int = 5
    comments_per_video: int = 50
    include_replies: bool = False


class CommentAnalyze(BaseModel):
    project_id: int = 1
    niche: str | None = None
    limit: int = 500


class AdvSearch(BaseModel):
    project_id: int = 1
    query: str


class AdvInvestigate(BaseModel):
    project_id: int = 1
    external_ids: list[str] = []
    auto_select: bool = True
    days: int = 90
    min_score: float = 0.3


class AdDetectMetadata(BaseModel):
    title: str = ""
    description: str = ""
    tags: list[str] | str = []
    channel_id: str = ""
    channel_title: str = ""
    published_at: str = ""
    duration_seconds: int = 0
    views: int = 0
    likes: int = 0
    comments: int = 0
    has_paid_product_placement: int = 0


class AdDetectRequest(BaseModel):
    project_id: int = 1
    content_id: int | None = None
    external_id: str | None = None
    platform: str = "YouTube"
    metadata: AdDetectMetadata = AdDetectMetadata()
    transcript: str = ""
    comments_sample: list[str] = []
    resolve_links: bool = False


class AdDetectBatchRequest(BaseModel):
    project_id: int = 1
    content_ids: list[int] | None = None


class PublicPreviewRequest(BaseModel):
    topic: str
    channels: list[str] = []
    videos: list[str] = []
    region_code: str = "IT"
    language: str = "it"
    days: int = 90
    max_channels: int = 50


class CreditsRefill(BaseModel):
    amount: int


class EntityCreate(BaseModel):
    project_id: int = 1
    name: str
    type: str = "brand"
    sector: str = ""
    aliases: list[str] = []
    metadata: dict = {}


class EntityUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    sector: str | None = None
    aliases: list[str] | None = None
    metadata: dict | None = None


class EntityMerge(BaseModel):
    project_id: int = 1
    target_id: int
    source_ids: list[int]


class EntityExtractionRequest(BaseModel):
    project_id: int = 1
    full_refresh: bool = False


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class NicheSeedChannel(BaseModel):
    channel_id: str
    channel_title: str = ""


class NicheSeedVideo(BaseModel):
    video_id: str
    title: str = ""


class NicheCreate(BaseModel):
    project_id: int = 1
    name: str
    description: str = ""
    status: str = "draft"
    kind: str = "topic"
    definition: dict = {}
    seed_channels: list[NicheSeedChannel] = []
    seed_videos: list[NicheSeedVideo] = []
    include_keywords: list[str] = []
    exclude_keywords: list[str] = []
    filters: dict = {}


class NicheUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    kind: str | None = None
    definition: dict | None = None
    seed_channels: list[NicheSeedChannel] | None = None
    seed_videos: list[NicheSeedVideo] | None = None
    include_keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    filters: dict | None = None


class NichePreviewRequest(BaseModel):
    filters: dict | None = None
    mode: str = "videos"  # "videos" (lista piatta) | "channels" (panorama N1–N4)


class NichePopulateRequest(BaseModel):
    content_ids: list[str]
    auto_fetch_comments: bool = True
    max_comment_videos: int = 5
    comments_per_video: int = 50
    include_replies: bool = False


class PanoramaMaterializeRequest(BaseModel):
    channel_ids: list[str] = []
    membership_mode: str = "curated"
    definition: dict = {}
    filters: dict | None = None


class CreatorLinkRequest(BaseModel):
    project_id: int = 1
    display_name: str
    channel_profile_ids: list[int]


class SponsorNicheCreate(BaseModel):
    project_id: int = 1
    entity_id: int
    name: str = ""
    days: int = 365
    platform: str | None = None


class AuthCredentials(BaseModel):
    email: str
    password: str
    organization_name: str = ""


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


def require_project_access(request: Request, project_id: int) -> None:
    if not user_can_access_project(request.state.user["id"], project_id):
        raise HTTPException(status_code=404, detail="Progetto non trovato")


@app.get("/")
def landing_page() -> Response:
    return FileResponse(ROOT / "static" / "landing.html")


@app.get("/try")
def public_try_page() -> Response:
    return FileResponse(ROOT / "static" / "try.html")


@app.get("/app")
def index(request: Request) -> Response:
    if not request.state.user:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/login")
def login_page(request: Request) -> Response:
    if request.state.user:
        return RedirectResponse("/app", status_code=303)
    return FileResponse(ROOT / "static" / "login.html")


@app.get("/robots.txt")
def robots_txt(request: Request) -> Response:
    origin = settings.public_origin or str(request.base_url).rstrip("/")
    content = "\n".join((
        "User-agent: *",
        "Allow: /$",
        "Disallow: /app",
        "Disallow: /login",
        "Disallow: /api/",
        f"Sitemap: {origin}/sitemap.xml",
        "",
    ))
    return Response(content=content, media_type="text/plain")


@app.get("/sitemap.xml")
def sitemap_xml(request: Request) -> Response:
    origin = settings.public_origin or str(request.base_url).rstrip("/")
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{origin}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>\n"
        f"  <url><loc>{origin}/try</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>\n"
        "</urlset>\n"
    )
    return Response(content=content, media_type="application/xml")


def _alembic_revision() -> str | None:
    """Revisione Alembic corrente del database, se versionato (G4)."""
    try:
        from app.database import connect

        with connect() as connection:
            row = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
            return str(row[0]) if row else None
    except Exception:
        return None


@app.get("/api/health")
def health() -> Response:
    database_ok = ping_database()
    try:
        redis_ok = bool(Redis.from_url(settings.redis_url, socket_connect_timeout=1).ping())
    except Exception:
        redis_ok = False
    healthy = database_ok and (redis_ok or settings.app_env == "development")
    return JSONResponse(
        {
            "status": "ok" if healthy else "degraded",
            "version": APP_VERSION,
            "schema_revision": _alembic_revision(),
            "database": "ok" if database_ok else "unavailable",
            "redis": "ok" if redis_ok else "unavailable",
            "environment": settings.app_env,
        },
        status_code=200 if healthy else 503,
    )


def _public_preview_limit(request: Request) -> None:
    host = request.client.host if request.client else "unknown"
    key = hashlib.sha256(host.encode("utf-8")).hexdigest()[:24]
    try:
        public_preview_rate_limiter.check_and_record(key)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="Hai esaurito le analisi gratuite disponibili oggi. Accedi per continuare.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc


def _validate_public_preview(payload: PublicPreviewRequest) -> tuple[str, list[str], list[str]]:
    topic = " ".join(payload.topic.split()).strip()
    channels = list(dict.fromkeys(item.strip() for item in payload.channels if item.strip()))
    videos = list(dict.fromkeys(item.strip() for item in payload.videos if item.strip()))
    if len(topic) < 3 or len(topic) > 100:
        raise HTTPException(status_code=400, detail="Inserisci un argomento tra 3 e 100 caratteri")
    if len(channels) > 2:
        raise HTTPException(status_code=400, detail="La preview gratuita accetta massimo 2 canali seed")
    if len(videos) > 3:
        raise HTTPException(status_code=400, detail="La preview gratuita accetta massimo 3 video seed")
    if payload.days not in {30, 90, 365}:
        raise HTTPException(status_code=400, detail="Periodo non valido")
    if payload.max_channels not in {25, 50, 100}:
        raise HTTPException(status_code=400, detail="Numero massimo di canali non valido")
    if payload.max_channels > settings.public_preview_max_channels:
        raise HTTPException(status_code=400, detail="Il limite richiesto supera quello disponibile")
    if payload.region_code and (len(payload.region_code) != 2 or not payload.region_code.isalpha()):
        raise HTTPException(status_code=400, detail="La regione deve essere un codice di due lettere")
    if payload.language and (len(payload.language) != 2 or not payload.language.isalpha()):
        raise HTTPException(status_code=400, detail="La lingua deve essere un codice di due lettere")
    return topic, channels, videos


@app.post("/api/public/preview")
def public_preview(payload: PublicPreviewRequest, request: Request) -> dict:
    """Preview anonima, non persistita, di un campione YouTube."""
    if not settings.public_preview_enabled:
        raise HTTPException(status_code=503, detail="La preview pubblica non è ancora attiva")
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="La fonte YouTube non è configurata")
    topic, channel_seeds, video_seeds = _validate_public_preview(payload)
    _public_preview_limit(request)

    niche = {
        "name": topic,
        "description": topic,
        "seed_channels": [
            {"channel_id": value, "channel_title": value} for value in channel_seeds
        ],
        "seed_videos": [
            {"video_id": value, "title": value} for value in video_seeds
        ],
        "include_keywords": [topic],
        "exclude_keywords": [],
        "filters": {
            "date_window_days": payload.days,
            "max_results": min(max(payload.max_channels * 3, 50), 300),
            "region_code": payload.region_code.upper(),
            "relevance_language": payload.language.lower(),
            "strict_geo": False,
            "harvest_popular": False,
            "include_top_channels": False,
            "second_wave_top_k": 0,
        },
    }
    estimated_units = estimate_niche_expansion_units(niche)
    ensure_quota_available(estimated_units)
    stats: dict[str, Any] = {}
    try:
        channels = expand_niche_channels(
            niche, connector=YouTubeConnector(api_key=api_key), stats=stats,
        )
    except YouTubeAPIError:
        raise
    except Exception as exc:
        logger.exception("Preview pubblica fallita")
        raise HTTPException(
            status_code=500,
            detail="Non è stato possibile completare l'analisi. Riprova più tardi.",
        ) from exc

    channels.sort(
        key=lambda item: (
            item.get("candidate_level") == "matched",
            item.get("video_count", 0),
            item.get("total_views", 0),
        ),
        reverse=True,
    )
    channels = channels[:payload.max_channels]
    contents = [
        {
            **video,
            "channel_id": channel["channel_id"],
            "channel_title": channel["channel_title"],
            "tags_json": json.dumps(video.get("tags", []), ensure_ascii=False),
        }
        for channel in channels
        for video in channel.get("videos", [])
    ]
    report = build_content_report(
        contents, datetime.now(timezone.utc), days=payload.days,
    )
    public_channels = [
        {
            "channel_id": channel["channel_id"],
            "title": channel["channel_title"],
            "custom_url": channel.get("custom_url", ""),
            "created_at": channel.get("channel_published_at", ""),
            "country": channel.get("country", ""),
            "language": channel.get("language", ""),
            "subscribers": channel.get("subscribers", 0),
            "declared_video_count": channel.get("declared_video_count", 0),
            "observed_videos": channel.get("video_count", 0),
            "total_views": channel.get("total_views", 0),
            "average_views": channel.get("avg_views", 0),
            "engagement_rate": round(float(channel.get("engagement_rate", 0)) * 100, 2),
            "last_published_at": channel.get("last_published_at", ""),
            "match": channel.get("candidate_level", "observed"),
            "evidence": [
                {
                    "external_id": video.get("external_id", ""),
                    "title": video.get("title", ""),
                    "published_at": video.get("published_at", ""),
                    "views": video.get("views", 0),
                    "duration_seconds": video.get("duration_seconds", 0),
                }
                for video in channel.get("videos", [])[:3]
            ],
        }
        for channel in channels
    ]
    return {
        "query": topic,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "notice": "Analisi descrittiva del campione osservato, non censimento completo della nicchia.",
        "coverage": {
            "channels": len(public_channels),
            "videos": len(contents),
            "requested_channels": payload.max_channels,
            "candidates": stats.get("candidates", len(contents)),
            "excluded_geo": stats.get("excluded_geo", 0),
            "unresolved_channels": len(stats.get("unresolved_channels", [])),
            "invalid_video_seeds": len(stats.get("invalid_video_seeds", [])),
            "estimated_quota_units": estimated_units,
            "truncated": len(channels) >= payload.max_channels,
        },
        "metrics": {
            "views": sum(channel["total_views"] for channel in public_channels),
            "median_subscribers": _median_int([channel["subscribers"] for channel in public_channels]),
            "median_average_views": _median_int([channel["average_views"] for channel in public_channels]),
            "commercial_contents": report.get("commercial_signals", {}).get("contents", 0),
        },
        "terms": report.get("terms", [])[:12],
        "durations": report.get("durations", []),
        "formats": report.get("taxonomy", {}).get("formats", []),
        "top_contents": report.get("top_contents", [])[:8],
        "channels": public_channels,
        "account_required_for": [
            "salvare il report", "esportare il corpus", "approfondire i commenti",
            "monitorare la nicchia", "creare nuove analisi",
        ],
    }


def _median_int(values: list[int]) -> int:
    ordered = sorted(int(value or 0) for value in values)
    if not ordered:
        return 0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return round((ordered[middle - 1] + ordered[middle]) / 2)


@app.get("/api/auth/status")
def auth_status(request: Request) -> dict:
    return {
        "authenticated": bool(request.state.user),
        "user": request.state.user,
        "registration_enabled": settings.allow_registration,
    }


def _auth_rate_limit_key(request: Request, email: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{email.lower().strip()}"


def _check_auth_rate_limit(request: Request, email: str) -> None:
    try:
        auth_rate_limiter.check(_auth_rate_limit_key(request, email))
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=f"Troppi tentativi falliti: riprova tra {exc.retry_after // 60 + 1} minuti",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc


@app.post("/api/auth/register", status_code=201)
def auth_register(payload: AuthCredentials, request: Request) -> Response:
    if not settings.allow_registration:
        raise HTTPException(status_code=403, detail="Registrazioni disabilitate")
    email = payload.email.lower().strip()
    if "@" not in email or len(email) > 254:
        raise HTTPException(status_code=400, detail="Email non valida")
    if len(payload.password) < 10:
        raise HTTPException(status_code=400, detail="La password deve contenere almeno 10 caratteri")
    _check_auth_rate_limit(request, email)
    try:
        user, token = register(email, payload.password, payload.organization_name)
    except Exception as exc:
        if is_integrity_error(exc):
            auth_rate_limiter.record_failure(_auth_rate_limit_key(request, email))
            raise HTTPException(status_code=409, detail="Email già registrata") from exc
        raise
    auth_rate_limiter.reset(_auth_rate_limit_key(request, email))
    response = JSONResponse({"user": user}, status_code=201)
    response.set_cookie("signaldesk_session", token, max_age=14 * 86400, httponly=True, samesite="lax", secure=settings.cookie_secure)
    return response


@app.post("/api/auth/login")
def auth_login(payload: AuthCredentials, request: Request) -> Response:
    key = _auth_rate_limit_key(request, payload.email)
    _check_auth_rate_limit(request, payload.email)
    result = login(payload.email, payload.password)
    if not result:
        auth_rate_limiter.record_failure(key)
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    auth_rate_limiter.reset(key)
    user, token = result
    response = JSONResponse({"user": user})
    response.set_cookie("signaldesk_session", token, max_age=14 * 86400, httponly=True, samesite="lax", secure=settings.cookie_secure)
    return response


@app.post("/api/auth/logout")
def auth_logout(request: Request) -> Response:
    logout(request.cookies.get("signaldesk_session"))
    response = JSONResponse({"logged_out": True})
    response.delete_cookie("signaldesk_session")
    return response


@app.post("/api/auth/password")
def auth_password_change(payload: PasswordChange, request: Request) -> dict:
    """Cambio password da autenticato: revoca tutte le altre sessioni (A1)."""
    if len(payload.new_password) < 10:
        raise HTTPException(status_code=400, detail="La password deve contenere almeno 10 caratteri")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="La nuova password deve essere diversa dall'attuale")
    changed = change_password(
        request.state.user["id"],
        payload.current_password,
        payload.new_password,
        keep_token=request.cookies.get("signaldesk_session"),
    )
    if not changed:
        raise HTTPException(status_code=400, detail="La password attuale non è corretta")
    return {"changed": True}


@app.get("/api/auth/sessions")
def auth_sessions(request: Request) -> dict:
    """Sessioni attive dell'utente corrente (A5)."""
    current = token_hash(request.cookies.get("signaldesk_session") or "")
    items = [
        {
            "id": session["token_hash"][:12],
            "created_at": session["created_at"],
            "expires_at": session["expires_at"],
            "current": session["token_hash"] == current,
        }
        for session in list_user_sessions(request.state.user["id"])
    ]
    return {"items": items}


@app.post("/api/auth/sessions/revoke-others")
def auth_sessions_revoke_others(request: Request) -> dict:
    """Revoca tutte le sessioni tranne quella corrente (A5)."""
    revoked = delete_user_sessions_except(
        request.state.user["id"],
        token_hash(request.cookies.get("signaldesk_session") or ""),
    )
    return {"revoked": revoked}


def _since_from_days(days: int) -> str:
    """Soglia temporale ISO per il push-down SQL dei report (B1)."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()


def _snapshots_for_contents(contents: list[dict]) -> list[dict]:
    """Snapshot limitati agli external_id dei contenuti in esame (B1)."""
    external_ids = sorted({str(content.get("external_id", "")) for content in contents if content.get("external_id")})
    return project_snapshots(external_ids=external_ids)


@app.get("/api/report")
def report(
    request: Request,
    days: int = Query(14, ge=1, le=90),
    niche: str | None = None,
    left: str | None = None,
    right: str | None = None,
    project_id: int = Query(1, ge=1),
) -> dict:
    require_project_access(request, project_id)
    comparison = (left, right) if left and right and left != right else None
    return build_intelligence_report(
        all_comments(project_id, since=_since_from_days(days)),
        days=days, niche=niche, comparison_names=comparison,
    )


@app.get("/api/content/report")
def content_report(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    niche: str | None = None,
    left: str | None = None,
    right: str | None = None,
    project_id: int = Query(1, ge=1),
) -> dict:
    require_project_access(request, project_id)
    comparison = (left, right) if left and right and left != right else None
    contents = all_contents(project_id, since=_since_from_days(days))
    return build_content_report(
        contents, days=days, niche=niche, comparison_names=comparison,
        raw_snapshots=_snapshots_for_contents(contents),
    )


@app.get("/api/adv/report")
def adv_report(
    request: Request,
    days: int = Query(90, ge=1, le=365),
    niche: str | None = None,
    project_id: int = Query(1, ge=1),
) -> dict:
    require_project_access(request, project_id)
    entity_data = adv_entity_data(project_id, days=days, niche=niche)
    if entity_data:
        return build_adv_report_from_entities(
            entity_data, raw_snapshots=_snapshots_for_contents(entity_data)
        )
    contents = all_contents(project_id, since=_since_from_days(days))
    return build_adv_report(
        contents, raw_snapshots=_snapshots_for_contents(contents), days=days, niche=niche
    )


@app.post("/api/adv/search")
def adv_search(payload: AdvSearch, request: Request) -> dict:
    require_project_access(request, payload.project_id)
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="La query di ricerca è obbligatoria")
    contents = all_contents(payload.project_id)
    return search_sponsor(
        contents, raw_snapshots=_snapshots_for_contents(contents), query=payload.query.strip()
    )


@app.get("/api/adv/suspicious")
def adv_suspicious(
    request: Request,
    days: int = Query(90, ge=1, le=365),
    niche: str | None = None,
    min_score: float = Query(0.3, ge=0.0, le=1.0),
    include_declared: bool = False,
    project_id: int = Query(1, ge=1),
) -> dict:
    require_project_access(request, project_id)
    contents = all_contents(project_id, since=_since_from_days(days))
    return build_suspicion_report(
        contents,
        raw_snapshots=_snapshots_for_contents(contents),
        days=days,
        niche=niche,
        min_score=min_score,
        include_declared=include_declared,
    )


@app.post("/api/adv/investigate", status_code=202)
def adv_investigate(payload: AdvInvestigate, request: Request) -> dict:
    """Avvia l'indagine premium sulle trascrizioni (1 credito per video)."""
    require_project_access(request, payload.project_id)
    video_ids = [video_id.strip() for video_id in payload.external_ids if video_id.strip()]
    if not video_ids and payload.auto_select:
        contents = all_contents(payload.project_id, since=_since_from_days(payload.days))
        suspicion = build_suspicion_report(
            contents,
            raw_snapshots=_snapshots_for_contents(contents),
            days=payload.days,
            min_score=payload.min_score,
        )
        video_ids = [entry["external_id"] for entry in suspicion["items"] if not entry["declared"]]
    if not video_ids:
        raise HTTPException(
            status_code=400,
            detail="Nessun video da investigare: fornisci external_ids o attiva auto_select",
        )
    credits = get_transcription_credits(payload.project_id)
    if credits <= 0:
        raise HTTPException(
            status_code=402,
            detail="Crediti trascrizione esauriti: ricarica per avviare una nuova indagine",
        )
    video_ids = video_ids[:credits]
    job = enqueue_background_job(
        payload.project_id, "transcript_investigation", {"external_ids": video_ids}
    )
    return {"job": _public_job(job), "videos": len(video_ids), "credits_remaining": credits}


@app.post("/api/ad/detect")
def ad_detect(payload: AdDetectRequest, request: Request) -> dict:
    """Analizza un contenuto e restituisce la valutazione AD."""
    require_project_access(request, payload.project_id)

    from app.ad_detector import detect_ad_for_content

    content: dict[str, Any] | None = None
    if payload.content_id:
        with connect() as connection:
            row = connection.execute(
                """SELECT c.* FROM social_contents c
                   JOIN project_contents pc ON pc.content_id = c.id
                   WHERE pc.project_id = ? AND c.id = ?""",
                (payload.project_id, payload.content_id),
            ).fetchone()
            if row:
                content = dict(row)
    elif payload.external_id:
        with connect() as connection:
            row = connection.execute(
                """SELECT c.* FROM social_contents c
                   JOIN project_contents pc ON pc.content_id = c.id
                   WHERE pc.project_id = ? AND c.external_id = ? AND c.platform = ?""",
                (payload.project_id, payload.external_id, payload.platform),
            ).fetchone()
            if row:
                content = dict(row)

    if content is None:
        # Analisi su dati forniti senza contenuto persistito.
        content = {
            "id": 0,
            "external_id": payload.external_id or "unknown",
            "platform": payload.platform,
            "title": payload.metadata.title,
            "description": payload.metadata.description,
            "tags_json": json.dumps(payload.metadata.tags) if isinstance(payload.metadata.tags, list) else payload.metadata.tags,
            "channel_id": payload.metadata.channel_id,
            "channel_title": payload.metadata.channel_title,
            "published_at": payload.metadata.published_at,
            "duration_seconds": payload.metadata.duration_seconds,
            "views": payload.metadata.views,
            "likes": payload.metadata.likes,
            "comments": payload.metadata.comments,
            "has_paid_product_placement": payload.metadata.has_paid_product_placement,
            "transcript": payload.transcript,
            "comments_sample": payload.comments_sample,
        }
        assessment = detect_ad_for_content(content, payload.project_id)
        return {
            "content_id": content["id"],
            "external_id": content["external_id"],
            "platform": content["platform"],
            **assessment,
            "persisted": False,
        }

    # Aggiunge transcript e commenti al content se disponibili.
    with connect() as connection:
        transcript_row = connection.execute(
            "SELECT text FROM content_transcripts WHERE project_id = ? AND external_id = ? AND platform = ?",
            (payload.project_id, content["external_id"], content["platform"]),
        ).fetchone()
        if transcript_row:
            content["transcript"] = transcript_row["text"]

    content["transcript"] = payload.transcript or content.get("transcript", "")
    content["comments_sample"] = payload.comments_sample or []

    assessment = detect_ad_for_content(content, payload.project_id)

    # Persiste solo se richiesto implicitamente da content_id valido.
    if payload.content_id:
        upsert_content_ad_signal(
            project_id=payload.project_id,
            content_id=content["id"],
            platform=content["platform"],
            external_id=content["external_id"],
            assessment=assessment,
        )

    return {
        "content_id": content["id"],
        "external_id": content["external_id"],
        "platform": content["platform"],
        **assessment,
        "persisted": bool(payload.content_id),
    }


@app.post("/api/ad/detect/batch")
def ad_detect_batch(payload: AdDetectBatchRequest, request: Request) -> dict:
    """Esegue AD detection su più contenuti di un progetto."""
    require_project_access(request, payload.project_id)
    result = run_ad_detection_for_project(payload.project_id, payload.content_ids)
    return {"status": "ok", **result}


@app.get("/api/ad/report")
def ad_report(
    request: Request,
    project_id: int = Query(1, ge=1),
    days: int = Query(90, ge=1, le=365),
    niche: str | None = None,
) -> dict:
    """Report aggregato dei segnali AD nel progetto."""
    require_project_access(request, project_id)
    return ad_report_summary(project_id, days=days, niche=niche)


@app.get("/api/adv/transcripts")
def adv_transcripts(
    request: Request,
    only_ad_reads: bool = False,
    min_similarity: float = Query(0.45, ge=0.1, le=1.0),
    project_id: int = Query(1, ge=1),
) -> dict:
    """Risultati delle indagini trascrizione + cluster di campagne coordinate."""
    require_project_access(request, project_id)
    items = list_transcripts(project_id, only_ad_reads=only_ad_reads)
    campaign_entries = [
        {
            "external_id": item["external_id"],
            "channel": item["channel"],
            "text": " ".join(
                segment["text_preview"] for segment in item["analysis"].get("suspicious_segments", [])
            ),
        }
        for item in items
        if item["status"] == "ok" and item["analysis"].get("suspicious_segments")
    ]
    return {
        "items": items,
        "campaigns": find_campaign_clusters(campaign_entries, min_similarity=min_similarity),
        "credits": get_transcription_credits(project_id),
    }


@app.get("/api/adv/niches/brands")
def adv_niche_brands(
    request: Request,
    niche: str,
    project_id: int = Query(1, ge=1),
    days: int = Query(365, ge=1, le=3650),
    platform: str | None = None,
) -> dict:
    require_project_access(request, project_id)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(
        microsecond=0
    ).isoformat()
    items = brands_by_niche(
        project_id, niche, since=since, platform=platform,
    )
    total = sum(int(item["sponsored_contents"]) for item in items) or 1
    for item in items:
        item["content_share"] = round(item["sponsored_contents"] / total, 4)
    return {"niche": niche, "items": items, "total": len(items)}


@app.get("/api/adv/compare")
def adv_compare_brands(
    request: Request,
    left_entity_id: int,
    right_entity_id: int,
    project_id: int = Query(1, ge=1),
    days: int = Query(365, ge=1, le=3650),
    platform: str | None = None,
) -> dict:
    require_project_access(request, project_id)
    if left_entity_id == right_entity_id:
        raise HTTPException(status_code=400, detail="Seleziona due brand diversi")
    try:
        left = build_sponsor_basin_profile(
            project_id, left_entity_id, days=days, platform=platform,
        )
        right = build_sponsor_basin_profile(
            project_id, right_entity_id, days=days, platform=platform,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return compare_sponsor_basins(left, right)


@app.post("/api/projects/{project_id}/transcription-credits")
def refill_transcription_credits(project_id: int, payload: CreditsRefill, request: Request) -> dict:
    """Ricarica i crediti trascrizione del progetto (es. dopo un pagamento)."""
    require_project_access(request, project_id)
    if payload.amount <= 0 or payload.amount > 10000:
        raise HTTPException(status_code=400, detail="La ricarica deve essere tra 1 e 10000 crediti")
    balance = add_transcription_credits(project_id, payload.amount)
    add_processing_log(project_id, "transcription_credits_refill", {"amount": payload.amount, "balance": balance})
    return {"project_id": project_id, "credits": balance}


@app.get("/api/entities")
def entities_list(
    request: Request,
    project_id: int = Query(1, ge=1),
    type: str | None = None,
    search: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    require_project_access(request, project_id)
    return {
        "items": list_entities(project_id, type=type, search=search, limit=limit, offset=offset),
        "summary": entity_mentions_summary(project_id),
    }


@app.post("/api/entities", status_code=201)
def entity_create(payload: EntityCreate, request: Request) -> dict:
    require_project_access(request, payload.project_id)
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Il nome dell'entità è obbligatorio")
    if payload.type not in {"brand", "product", "person", "organization", "platform"}:
        raise HTTPException(status_code=400, detail="Tipo entità non valido")
    try:
        return create_entity(
            project_id=payload.project_id,
            name=payload.name,
            type=payload.type,
            sector=payload.sector,
            aliases=payload.aliases,
            metadata=payload.metadata,
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Esiste già un'entità con questo nome nel progetto") from exc


@app.get("/api/entities/{entity_id}")
def entity_detail(entity_id: int, request: Request) -> dict:
    entity = get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entità non trovata")
    require_project_access(request, entity["project_id"])
    return entity


@app.patch("/api/entities/{entity_id}")
def entity_update(entity_id: int, payload: EntityUpdate, request: Request) -> dict:
    entity = get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entità non trovata")
    require_project_access(request, entity["project_id"])
    if payload.type is not None and payload.type not in {"brand", "product", "person", "organization", "platform"}:
        raise HTTPException(status_code=400, detail="Tipo entità non valido")
    updated = update_entity(
        entity_id=entity_id,
        name=payload.name,
        type=payload.type,
        sector=payload.sector,
        aliases=payload.aliases,
        metadata=payload.metadata,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Entità non trovata")
    return updated


@app.delete("/api/entities/{entity_id}")
def entity_delete(entity_id: int, request: Request) -> dict:
    entity = get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entità non trovata")
    require_project_access(request, entity["project_id"])
    return {"deleted": delete_entity(entity_id)}


@app.post("/api/entities/merge")
def entity_merge(payload: EntityMerge, request: Request) -> dict:
    require_project_access(request, payload.project_id)
    if not payload.source_ids:
        raise HTTPException(status_code=400, detail="Seleziona almeno un'entità da unire")
    try:
        return merge_entities(payload.project_id, payload.target_id, payload.source_ids)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/entities/extract", status_code=202)
def entity_extract(payload: EntityExtractionRequest, request: Request) -> dict:
    require_project_access(request, payload.project_id)
    job = enqueue_background_job(
        payload.project_id, "entity_extraction",
        {"full_refresh": payload.full_refresh},
    )
    add_processing_log(
        payload.project_id, "entity_extraction_requested",
        {"full_refresh": payload.full_refresh, "job_id": job["id"]},
    )
    return {"job": _public_job(job)}


@app.get("/api/entities/{entity_id}/mentions")
def entity_mentions(
    entity_id: int,
    request: Request,
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    entity = get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entità non trovata")
    require_project_access(request, entity["project_id"])
    return {"items": content_entity_mentions(entity["project_id"], entity_id=entity_id, limit=limit)}


@app.get("/api/entities/{entity_id}/sponsor-basin")
def entity_sponsor_basin(
    entity_id: int,
    request: Request,
    days: int = Query(365, ge=1, le=3650),
    niche: str | None = None,
    platform: str | None = None,
) -> dict:
    entity = get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entità non trovata")
    require_project_access(request, entity["project_id"])
    try:
        profile = build_sponsor_basin_profile(
            entity["project_id"], entity_id, days=days, niche=niche, platform=platform,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    profile.pop("contents", None)
    return profile


@app.post("/api/niches/from-sponsor", status_code=201)
def niche_from_sponsor(payload: SponsorNicheCreate, request: Request) -> dict:
    require_project_access(request, payload.project_id)
    try:
        basin = build_sponsor_basin_profile(
            payload.project_id, payload.entity_id,
            days=payload.days, platform=payload.platform,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    name = payload.name.strip() or f"Canali sponsorizzati da {basin['entity']['name']}"
    definition = {
        "source": "sponsor", "entity_id": payload.entity_id,
        "days": payload.days, "platform": payload.platform,
        "membership_mode": "rule_based",
    }
    try:
        niche = create_niche(
            project_id=payload.project_id, name=name,
            description=f"Canali sponsorizzati da {basin['entity']['name']}",
            status="active", kind="panorama", definition=definition,
        )
    except Exception as exc:
        if is_integrity_error(exc):
            raise HTTPException(status_code=409, detail="Esiste già una nicchia con questo nome") from exc
        raise
    memberships = sync_niche_channels(
        payload.project_id, niche["id"], basin["channels"], replace=True,
    )
    contents = []
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for content in basin["contents"]:
        contents.append({
            **content, "niche": name,
            "source_query": "sponsor_basin",
            "acquired_at": content.get("acquired_at") or now,
            "matched_seed": "sponsor",
            "matched_value": basin["entity"]["name"],
        })
    if contents:
        upsert_contents_for_niche(payload.project_id, niche["id"], name, contents)
    return {**niche, "channels": len(memberships), "contents": len(contents)}


@app.get("/api/niches")
def niches(request: Request, project_id: int = Query(1, ge=1)) -> list[dict]:
    require_project_access(request, project_id)
    return list_niche_entities(project_id)


@app.get("/api/niches/summary")
def niches_summary(request: Request, project_id: int = Query(1, ge=1)) -> list[dict]:
    require_project_access(request, project_id)
    return list_niches(project_id)


@app.post("/api/niches", status_code=201)
def niche_create(payload: NicheCreate, request: Request) -> dict:
    require_project_access(request, payload.project_id)
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Il nome della nicchia è obbligatorio")
    if payload.status not in {"draft", "active", "archived"}:
        raise HTTPException(status_code=400, detail="Stato non valido")
    if payload.kind not in {"topic", "panorama"}:
        raise HTTPException(status_code=400, detail="Tipo nicchia non valido")
    try:
        return create_niche(
            project_id=payload.project_id,
            name=payload.name,
            description=payload.description,
            status=payload.status,
            kind=payload.kind,
            definition=payload.definition,
            seed_channels=[c.model_dump() for c in payload.seed_channels],
            seed_videos=[v.model_dump() for v in payload.seed_videos],
            include_keywords=payload.include_keywords,
            exclude_keywords=payload.exclude_keywords,
            filters=payload.filters,
        )
    except Exception as exc:
        if is_integrity_error(exc):
            raise HTTPException(
                status_code=409, detail="Esiste già una nicchia con questo nome nel progetto"
            ) from exc
        raise


@app.get("/api/niches/{niche_id}")
def niche_detail(niche_id: int, request: Request) -> dict:
    niche = get_niche(niche_id)
    if not niche:
        raise HTTPException(status_code=404, detail="Nicchia non trovata")
    require_project_access(request, niche["project_id"])
    return niche


@app.patch("/api/niches/{niche_id}")
def niche_update(niche_id: int, payload: NicheUpdate, request: Request) -> dict:
    niche = get_niche(niche_id)
    if not niche:
        raise HTTPException(status_code=404, detail="Nicchia non trovata")
    require_project_access(request, niche["project_id"])
    if payload.status is not None and payload.status not in {"draft", "active", "archived"}:
        raise HTTPException(status_code=400, detail="Stato non valido")
    if payload.kind is not None and payload.kind not in {"topic", "panorama"}:
        raise HTTPException(status_code=400, detail="Tipo nicchia non valido")
    try:
        updated = update_niche(
            niche_id=niche_id,
            name=payload.name,
            description=payload.description,
            status=payload.status,
            kind=payload.kind,
            definition=payload.definition,
            seed_channels=[c.model_dump() for c in payload.seed_channels]
            if payload.seed_channels is not None
            else None,
            seed_videos=[v.model_dump() for v in payload.seed_videos]
            if payload.seed_videos is not None
            else None,
            include_keywords=payload.include_keywords,
            exclude_keywords=payload.exclude_keywords,
            filters=payload.filters,
        )
    except Exception as exc:
        if is_integrity_error(exc):
            raise HTTPException(
                status_code=409, detail="Esiste già una nicchia con questo nome nel progetto"
            ) from exc
        raise
    if updated is None:
        raise HTTPException(status_code=404, detail="Nicchia non trovata")
    return updated


@app.delete("/api/niches/{niche_id}")
def niche_delete(niche_id: int, request: Request) -> dict:
    niche = get_niche(niche_id)
    if not niche:
        raise HTTPException(status_code=404, detail="Nicchia non trovata")
    require_project_access(request, niche["project_id"])
    return {"deleted": delete_niche(niche_id)}


def estimate_niche_expansion_units(niche: dict) -> int:
    """Stima conservativa del costo quota di un'espansione di nicchia (C2).

    Fino a 10 ricerche (canali seed + keyword) da 100 unità, più le
    chiamate aggregate da 1 unità (dettagli video, canali, popolari).
    """
    searches = min(
        len(niche.get("seed_channels", [])) + len(niche.get("include_keywords", [])),
        10,
    )
    units = searches * 100 + 5
    if (niche.get("filters") or {}).get("harvest_popular"):
        units += 1
    units += int((niche.get("filters") or {}).get("second_wave_top_k", 0) or 0) * 100
    return units


@app.post("/api/niches/{niche_id}/discover", status_code=202)
def discover_niche(niche_id: int, request: Request) -> dict:
    niche = get_niche(niche_id)
    if not niche:
        raise HTTPException(status_code=404, detail="Nicchia non trovata")
    require_project_access(request, niche["project_id"])
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Configura YOUTUBE_API_KEY sul server")
    ensure_quota_available(estimate_niche_expansion_units(niche))
    job = enqueue_background_job(
        niche["project_id"], "niche_discovery", {"niche_id": niche_id}
    )
    return {"job": _public_job(job), "niche": niche["name"]}


@app.post("/api/niches/{niche_id}/preview")
def preview_niche(niche_id: int, payload: NichePreviewRequest, request: Request) -> dict:
    niche = get_niche(niche_id)
    if not niche:
        raise HTTPException(status_code=404, detail="Nicchia non trovata")
    require_project_access(request, niche["project_id"])
    if payload.mode not in {"videos", "channels"}:
        raise HTTPException(status_code=400, detail="Modalità preview non valida")
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Configura YOUTUBE_API_KEY sul server")
    connector = YouTubeConnector(api_key=api_key)
    preview_niche = dict(niche)
    if payload.filters:
        preview_niche["filters"] = {**(niche.get("filters") or {}), **payload.filters}
    stats: dict = {}
    ensure_quota_available(estimate_niche_expansion_units(preview_niche))
    try:
        if payload.mode == "channels":
            # Vista panorama (N1–N4): pool di canali con temi estratti,
            # score composito e cerchi emergenti.
            panorama = build_panorama(preview_niche, connector=connector, stats=stats)
            return {
                "niche": niche["name"],
                "mode": "channels",
                "channels": panorama["channels"],
                "circles": panorama["circles"],
                "pool_themes": panorama["pool_themes"],
                "total": len(panorama["channels"]),
                "stats": stats,
            }
        contents = expand_niche(preview_niche, connector=connector, stats=stats)
    except YouTubeAPIError as exc:
        if is_quota_error(exc):
            raise HTTPException(
                status_code=503,
                detail="Quota giornaliera YouTube API esaurita: riprova domani "
                       "o riduci le operazioni di ricerca.",
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        # Errori imprevisti: il dettaglio resta leggibile per il debug
        # invece di un generico 500 senza contesto.
        raise HTTPException(
            status_code=500, detail=f"Errore interno: {type(exc).__name__}: {exc}"
        ) from exc
    return {
        "niche": niche["name"],
        "mode": "videos",
        "items": contents,
        "total": len(contents),
        "stats": stats,
    }


@app.get("/api/niches/{niche_id}/channels")
def niche_channel_members(niche_id: int, request: Request) -> dict:
    niche = get_niche(niche_id)
    if not niche:
        raise HTTPException(status_code=404, detail="Nicchia non trovata")
    require_project_access(request, niche["project_id"])
    channels = list_niche_channels(niche_id)
    return {"niche": niche, "channels": channels, "total": len(channels)}


@app.post("/api/niches/{niche_id}/materialize", status_code=202)
def materialize_panorama(
    niche_id: int, payload: PanoramaMaterializeRequest, request: Request,
) -> dict:
    niche = get_niche(niche_id)
    if not niche:
        raise HTTPException(status_code=404, detail="Nicchia non trovata")
    require_project_access(request, niche["project_id"])
    if payload.membership_mode not in {"curated", "rule_based"}:
        raise HTTPException(status_code=400, detail="Modalità membership non valida")
    if payload.membership_mode == "curated" and not payload.channel_ids:
        raise HTTPException(status_code=400, detail="Seleziona almeno un canale")
    if not os.getenv("YOUTUBE_API_KEY"):
        raise HTTPException(status_code=503, detail="Configura YOUTUBE_API_KEY sul server")
    filters = {**(niche.get("filters") or {}), **(payload.filters or {})}
    evaluation = {**niche, "filters": filters}
    ensure_quota_available(estimate_niche_expansion_units(evaluation))
    definition = {
        **(niche.get("definition") or {}), **payload.definition,
        "membership_mode": payload.membership_mode,
    }
    update_niche(niche_id, kind="panorama", definition=definition, filters=filters)
    job = enqueue_background_job(
        niche["project_id"], "panorama_materialize", {
            "niche_id": niche_id,
            "channel_ids": payload.channel_ids,
            "membership_mode": payload.membership_mode,
        },
    )
    return {"job": _public_job(job), "niche": niche["name"]}


@app.post("/api/niches/{niche_id}/reevaluate", status_code=202)
def reevaluate_panorama(niche_id: int, request: Request) -> dict:
    niche = get_niche(niche_id)
    if not niche:
        raise HTTPException(status_code=404, detail="Nicchia non trovata")
    require_project_access(request, niche["project_id"])
    if niche.get("kind") != "panorama":
        raise HTTPException(status_code=400, detail="La nicchia non è di tipo panorama")
    ensure_quota_available(estimate_niche_expansion_units(niche))
    job = enqueue_background_job(
        niche["project_id"], "panorama_materialize", {
            "niche_id": niche_id, "channel_ids": [],
            "membership_mode": (niche.get("definition") or {}).get(
                "membership_mode", "rule_based"
            ),
        },
    )
    return {"job": _public_job(job), "niche": niche["name"]}


@app.get("/api/channel-profiles")
def channel_profiles(request: Request, project_id: int = Query(1, ge=1), platform: str | None = None) -> dict:
    require_project_access(request, project_id)
    items = list_channel_profiles(project_id, platform=platform)
    return {"items": items, "total": len(items)}


@app.post("/api/creator-links", status_code=201)
def creator_link_create(payload: CreatorLinkRequest, request: Request) -> dict:
    require_project_access(request, payload.project_id)
    if not payload.display_name.strip() or not payload.channel_profile_ids:
        raise HTTPException(status_code=400, detail="Nome e profili canale sono obbligatori")
    try:
        return create_creator_link(
            payload.project_id, payload.display_name, payload.channel_profile_ids
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/niches/{niche_id}/populate", status_code=202)
def populate_niche(niche_id: int, payload: NichePopulateRequest, request: Request) -> dict:
    niche = get_niche(niche_id)
    if not niche:
        raise HTTPException(status_code=404, detail="Nicchia non trovata")
    require_project_access(request, niche["project_id"])
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Configura YOUTUBE_API_KEY sul server")
    if not payload.content_ids:
        raise HTTPException(status_code=400, detail="Seleziona almeno un contenuto")
    job = enqueue_background_job(
        niche["project_id"], "niche_populate", {
            "niche_id": niche_id,
            "content_ids": payload.content_ids,
            "auto_fetch_comments": payload.auto_fetch_comments,
            "max_comment_videos": payload.max_comment_videos,
            "comments_per_video": payload.comments_per_video,
            "include_replies": payload.include_replies,
        }
    )
    return {"job": _public_job(job), "niche": niche["name"]}


@app.get("/api/projects")
def projects(request: Request) -> list[dict]:
    return list_projects(request.state.user["id"])


@app.post("/api/projects", status_code=201)
def project_create(payload: ProjectCreate, request: Request) -> dict:
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Il nome del progetto è obbligatorio")
    try:
        return create_project(payload.name, payload.description, request.state.user["id"])
    except Exception as exc:
        if is_integrity_error(exc):
            raise HTTPException(status_code=409, detail="Esiste già un progetto con questo nome") from exc
        raise


@app.delete("/api/projects/{project_id}")
def project_delete(project_id: int, request: Request) -> dict:
    if project_id == 1:
        raise HTTPException(status_code=400, detail="Il progetto principale non può essere eliminato")
    require_project_access(request, project_id)
    if not delete_project(project_id, request.state.user["id"]):
        raise HTTPException(status_code=404, detail="Progetto non trovato")
    return {"deleted": project_id}


@app.delete("/api/projects/{project_id}/contents")
def project_contents_delete(
    project_id: int,
    request: Request,
    niche: str | None = None,
) -> dict:
    """Scollega i contenuti del progetto (opzionalmente solo una nicchia) (B2).

    Rimuove le associazioni progetto-contenuto e i contenuti rimasti orfani;
    i contenuti condivisi con altri progetti restano intatti.
    """
    require_project_access(request, project_id)
    result = delete_project_contents(project_id, niche=niche)
    add_processing_log(
        project_id, "contents_deleted",
        {"niche": niche or "*", **result},
    )
    return {"project_id": project_id, "niche": niche, **result}


@app.get("/api/connectors/status")
def connectors_status() -> dict:
    return {
        "youtube": {
            "configured": bool(os.getenv("YOUTUBE_API_KEY")),
            "pseudonym_salt_configured": bool(os.getenv("PSEUDONYM_SALT")),
            "mode": "API ufficiale · commenti pubblici top-level",
            "auto_refresh_hours": settings.auto_refresh_hours,
            "auto_refresh_active": bool(settings.auto_refresh_hours and os.getenv("YOUTUBE_API_KEY")),
        }
    }


@app.get("/api/quota")
def quota_status() -> dict:
    """Consumo stimato della quota YouTube API (C1).

    Il conteggio è una stima basata sul costo documentato delle chiamate
    (search.list = 100 unità, altre = 1), non il valore ufficiale Google.
    """
    summary = api_usage_summary(days=7)
    return {
        **summary,
        "daily_budget": settings.youtube_daily_quota,
        "estimated": True,
    }


def ensure_quota_available(estimated_units: int) -> None:
    """Blocca l'operazione se la quota residua stimata non basta (C2)."""
    used = api_usage_summary(days=1)["used_today"]
    if used + estimated_units > settings.youtube_daily_quota:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Quota stimata insufficiente: l'operazione richiede ~{estimated_units} "
                f"unità ma oggi ne restano ~{max(settings.youtube_daily_quota - used, 0)} "
                f"su {settings.youtube_daily_quota}. Riprova domani."
            ),
        )


@app.post("/api/sources/youtube/import")
def import_youtube(payload: YouTubeImport, request: Request) -> dict:
    require_project_access(request, payload.project_id)
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Configura YOUTUBE_API_KEY sul server prima di acquisire dati reali",
        )
    if not payload.niche.strip():
        raise HTTPException(status_code=400, detail="La nicchia è obbligatoria")
    if not 1 <= payload.max_comments <= 500:
        raise HTTPException(status_code=400, detail="max_comments deve essere tra 1 e 500")
    ensure_quota_available(2 + -(-payload.max_comments // 100))
    metadata, comments = fetch_video_comments(
        api_key=api_key,
        video=payload.video,
        niche=payload.niche,
        topic=payload.topic,
        max_comments=payload.max_comments,
        salt=os.getenv("PSEUDONYM_SALT", "signaldesk-development-only"),
        include_replies=payload.include_replies,
    )
    return {
        "video": metadata,
        "received": len(comments),
        "imported": insert_comments(comments, payload.project_id),
    }


@app.post("/api/sources/youtube/discover", status_code=202)
def discover_youtube(payload: YouTubeDiscovery, request: Request) -> dict:
    require_project_access(request, payload.project_id)
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Configura YOUTUBE_API_KEY sul server")
    if not payload.query.strip() or not payload.niche.strip():
        raise HTTPException(status_code=400, detail="Query e nicchia sono obbligatorie")
    if not 1 <= payload.days <= 365 or not 1 <= payload.max_results <= 50:
        raise HTTPException(status_code=400, detail="Periodo o numero di risultati non valido")
    ensure_quota_available(101)
    source = upsert_project_source(
        payload.project_id, "youtube_search",
        f"Query: {payload.query.strip()}",
        {
            "query": payload.query.strip(), "niche": payload.niche.strip(),
            "topic": payload.topic.strip(), "days": payload.days,
            "max_results": payload.max_results,
        },
    )
    mark_source_enqueued(source["id"])
    job = enqueue_background_job(
        payload.project_id, "youtube_discovery", {
            "query": payload.query, "niche": payload.niche, "topic": payload.topic,
            "days": payload.days, "max_results": payload.max_results,
            "source_id": source["id"],
        }
    )
    return {"job": _public_job(job), "source": _public_source(source)}


@app.post("/api/sources/youtube/comments/bulk", status_code=202)
def import_youtube_comments_bulk(payload: YouTubeBulkComments, request: Request) -> dict:
    require_project_access(request, payload.project_id)
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Configura YOUTUBE_API_KEY sul server")
    if not 1 <= payload.video_limit <= 10 or not 1 <= payload.comments_per_video <= 100:
        raise HTTPException(status_code=400, detail="Limiti non validi")
    ensure_quota_available(payload.video_limit * 3)
    job = enqueue_background_job(
        payload.project_id, "youtube_bulk_comments", {
            "niche": payload.niche, "video_limit": payload.video_limit,
            "comments_per_video": payload.comments_per_video,
            "include_replies": payload.include_replies,
        }
    )
    return {"job": _public_job(job)}


def _public_source(source: dict) -> dict:
    public = {key: source.get(key) for key in (
        "id", "project_id", "source_type", "name", "status", "refresh_hours",
        "created_at", "last_run_at", "next_run_at", "last_error",
    )}
    try:
        public["config"] = json.loads(source.get("config_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        public["config"] = {}
    return public


def _require_source_access(request: Request, source_id: int) -> dict:
    source = project_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Fonte non trovata")
    require_project_access(request, source["project_id"])
    return source


@app.get("/api/sources")
def sources_list(request: Request, project_id: int = Query(1, ge=1)) -> dict:
    require_project_access(request, project_id)
    return {"items": [_public_source(item) for item in list_project_sources(project_id)]}


class SourceUpdate(BaseModel):
    status: str | None = None
    refresh_hours: int | None = None
    name: str | None = None


@app.patch("/api/sources/{source_id}")
def source_update(source_id: int, payload: SourceUpdate, request: Request) -> dict:
    _require_source_access(request, source_id)
    if payload.status is not None and payload.status not in {"active", "paused"}:
        raise HTTPException(status_code=400, detail="Lo stato deve essere active o paused")
    if payload.refresh_hours is not None and not 1 <= payload.refresh_hours <= 720:
        raise HTTPException(status_code=400, detail="La frequenza deve essere tra 1 e 720 ore")
    if payload.name is not None and not payload.name.strip():
        raise HTTPException(status_code=400, detail="Il nome non può essere vuoto")
    updated = update_project_source(
        source_id, payload.status, payload.refresh_hours, name=payload.name
    )
    return _public_source(updated)


@app.delete("/api/sources/{source_id}")
def source_delete(source_id: int, request: Request) -> dict:
    _require_source_access(request, source_id)
    if not delete_project_source(source_id):
        raise HTTPException(status_code=404, detail="Fonte non trovata")
    return {"deleted": source_id}


@app.post("/api/sources/{source_id}/run", status_code=202)
def source_run_now(source_id: int, request: Request) -> dict:
    source = _require_source_access(request, source_id)
    if not os.getenv("YOUTUBE_API_KEY"):
        raise HTTPException(status_code=503, detail="Configura YOUTUBE_API_KEY sul server")
    if source["source_type"] != "youtube_search":
        raise HTTPException(status_code=400, detail="Tipo di fonte non eseguibile")
    try:
        config = json.loads(source["config_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Configurazione fonte illeggibile") from exc
    ensure_quota_available(101)
    mark_source_enqueued(source_id)
    job = enqueue_background_job(
        source["project_id"], "youtube_discovery", {
            "query": config.get("query", ""), "niche": config.get("niche", ""),
            "topic": config.get("topic", ""), "days": int(config.get("days", 30)),
            "max_results": int(config.get("max_results", 25)),
            "source_id": source_id,
        }
    )
    return {"job": _public_job(job)}


def _public_job(job: dict) -> dict:
    public = {key: job.get(key) for key in (
        "id", "project_id", "job_type", "status", "progress", "error",
        "created_at", "started_at", "finished_at",
    )}
    try:
        public["result"] = json.loads(job.get("result_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        public["result"] = {}
    return public


@app.get("/api/jobs")
def jobs_list(
    request: Request, project_id: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    require_project_access(request, project_id)
    return {"items": [_public_job(job) for job in background_jobs(project_id, limit)]}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: int, request: Request) -> dict:
    job = background_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    require_project_access(request, job["project_id"])
    return _public_job(job)


@app.delete("/api/jobs/{job_id}")
def job_cancel(job_id: int, request: Request) -> dict:
    job = background_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    require_project_access(request, job["project_id"])
    return {"cancelled": cancel_background_job(job_id)}


@app.post("/api/sources/youtube/refresh")
def refresh_youtube(payload: YouTubeRefresh, request: Request) -> dict:
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Configura YOUTUBE_API_KEY sul server")
    if not 1 <= payload.limit <= 500:
        raise HTTPException(status_code=400, detail="Il limite deve essere tra 1 e 500")
    if payload.project_id is not None:
        require_project_access(request, payload.project_id)
    ensure_quota_available(-(-payload.limit // 50))
    return perform_metrics_refresh(
        "manual", payload.niche, payload.limit, payload.project_id
    )


@app.get("/api/monitoring/runs")
def monitoring_history(
    request: Request, project_id: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    require_project_access(request, project_id)
    return {
        "auto_refresh_hours": settings.auto_refresh_hours,
        "active": bool(settings.auto_refresh_hours and os.getenv("YOUTUBE_API_KEY")),
        "items": list_monitoring_runs(limit, project_id),
    }


@app.get("/api/comments/search")
def comments_search(
    request: Request,
    q: str = Query(min_length=2, max_length=100),
    niche: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    project_id: int = Query(1, ge=1),
) -> dict:
    require_project_access(request, project_id)
    results = search_comments(q.strip(), project_id=project_id, niche=niche, limit=limit)
    return {"query": q, "count": len(results), "items": results}


@app.post("/api/comments/analyze", status_code=202)
def comments_analyze(payload: CommentAnalyze, request: Request) -> dict:
    require_project_access(request, payload.project_id)
    if not 1 <= payload.limit <= 5000:
        raise HTTPException(status_code=400, detail="Il limite deve essere tra 1 e 5000")
    job = enqueue_background_job(
        payload.project_id, "comment_analysis",
        {"niche": payload.niche, "limit": payload.limit},
    )
    add_processing_log(
        payload.project_id, "comment_analysis_requested",
        {"niche": payload.niche, "limit": payload.limit, "job_id": job["id"]},
    )
    return {"job": _public_job(job)}


@app.get("/api/comments/analysis")
def comments_analysis(
    request: Request,
    niche: str | None = None,
    project_id: int = Query(1, ge=1),
) -> dict:
    require_project_access(request, project_id)
    return comment_analysis_summary(project_id, niche)


@app.get("/api/processing/logs")
def processing_logs(
    request: Request,
    project_id: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    require_project_access(request, project_id)
    return {"items": list_processing_logs(project_id, limit)}


@app.get("/api/channels/overlap")
def channel_overlap(
    request: Request,
    project_id: int = Query(1, ge=1),
    niche: str | None = None,
) -> dict:
    require_project_access(request, project_id)
    comments = comments_with_channel(project_id, niche)
    return build_channel_overlap(comments)


def _csv_response(rows: list[dict], fields: list[str], filename: str) -> Response:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/contents.csv")
def export_contents(
    request: Request,
    project_id: int = Query(1, ge=1), niche: str | None = None,
) -> Response:
    require_project_access(request, project_id)
    rows = all_contents(project_id)
    if niche:
        rows = [row for row in rows if row.get("niche") == niche]
    fields = [
        "external_id", "platform", "title", "channel_title", "tags_json", "published_at",
        "duration_seconds", "views", "likes", "comments", "niche", "topic",
        "source_query", "acquired_at",
    ]
    return _csv_response(rows, fields, f"signaldesk-project-{project_id}-contents.csv")


@app.get("/api/export/comments.csv")
def export_comments(
    request: Request,
    project_id: int = Query(1, ge=1), niche: str | None = None,
) -> Response:
    require_project_access(request, project_id)
    rows = all_comments(project_id)
    if niche:
        rows = [row for row in rows if row.get("niche") == niche]
    fields = [
        "external_id", "content_id", "content_title", "author_hash", "text",
        "published_at", "platform", "niche", "topic",
    ]
    return _csv_response(rows, fields, f"signaldesk-project-{project_id}-comments.csv")


@app.post("/api/import")
def import_csv(payload: CSVImport, request: Request) -> dict[str, int]:
    require_project_access(request, payload.project_id)
    try:
        rows = list(csv.DictReader(io.StringIO(payload.csv_text)))
        required = {"external_id", "content_id", "author_hash", "text", "published_at"}
        if not rows or not required.issubset(rows[0]):
            raise ValueError(f"Colonne obbligatorie: {', '.join(sorted(required))}")
        return {"imported": insert_comments(rows, payload.project_id)}
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/import/contents")
def import_contents_csv(payload: CSVImport, request: Request) -> dict[str, int]:
    require_project_access(request, payload.project_id)
    try:
        rows = list(csv.DictReader(io.StringIO(payload.csv_text)))
        required = {"external_id", "platform", "title", "published_at"}
        if not rows or not required.issubset(rows[0]):
            raise ValueError(f"Colonne obbligatorie: {', '.join(sorted(required))}")
        acquired_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        numeric_fields = ("duration_seconds", "views", "likes", "comments")
        for row in rows:
            for field in numeric_fields:
                row[field] = int(row.get(field) or 0)
            row["tags"] = [tag.strip() for tag in row.get("tags", "").split("|") if tag.strip()]
            row["acquired_at"] = acquired_at
            row["source_query"] = row.get("source_query") or "Importazione CSV"
        return {"imported": upsert_contents(rows, payload.project_id)}
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
