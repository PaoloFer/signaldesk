from __future__ import annotations

import asyncio
import json
import os
import secrets
from datetime import datetime, timezone

from redis import Redis

from app.database import (
    due_project_sources,
    enqueue_background_job,
    initialize,
    mark_source_enqueued,
    reap_stalled_jobs,
)
from app.jobs import process_next_job
from app.monitoring import perform_metrics_refresh
from app.settings import settings


async def background_job_loop() -> None:
    iterations = 0
    while True:
        processed = await asyncio.to_thread(process_next_job)
        iterations += 1
        if iterations >= 750:
            # Ogni ~10 minuti: i job 'running' oltre il timeout (es. worker
            # terminato durante l'esecuzione) vengono marcati come falliti (F3).
            iterations = 0
            await asyncio.to_thread(reap_stalled_jobs, settings.job_timeout_hours)
        await asyncio.sleep(0.1 if processed else 0.8)


def enqueue_due_sources(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    enqueued = 0
    for source in due_project_sources(now.replace(microsecond=0).isoformat()):
        if source["source_type"] != "youtube_search":
            mark_source_enqueued(source["id"])
            continue
        try:
            config = json.loads(source["config_json"])
        except (TypeError, json.JSONDecodeError):
            mark_source_enqueued(source["id"])
            continue
        mark_source_enqueued(source["id"])
        enqueue_background_job(
            source["project_id"], "youtube_discovery", {
                "query": config.get("query", ""), "niche": config.get("niche", ""),
                "topic": config.get("topic", ""), "days": int(config.get("days", 30)),
                "max_results": int(config.get("max_results", 25)),
                "source_id": source["id"],
            }
        )
        enqueued += 1
    return enqueued


async def sources_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(enqueue_due_sources)
        except Exception:
            # The scheduler must survive transient database errors.
            pass
        await asyncio.sleep(60)


async def monitoring_loop() -> None:
    redis_client = Redis.from_url(settings.redis_url)
    worker_id = secrets.token_hex(12)
    while True:
        await asyncio.sleep(settings.auto_refresh_hours * 3600)
        try:
            lock_seconds = max(round(settings.auto_refresh_hours * 3600 * 0.9), 60)
            acquired = await asyncio.to_thread(
                redis_client.set,
                "signaldesk:scheduled-refresh-lock",
                worker_id,
                nx=True,
                ex=lock_seconds,
            )
            if acquired:
                await asyncio.to_thread(perform_metrics_refresh, "scheduled")
        except Exception:
            # perform_metrics_refresh persists the failure; the scheduler remains alive.
            continue


async def run_worker() -> None:
    initialize()
    tasks = [
        asyncio.create_task(background_job_loop()),
        asyncio.create_task(sources_loop()),
    ]
    if settings.auto_refresh_hours and os.getenv("YOUTUBE_API_KEY"):
        tasks.append(asyncio.create_task(monitoring_loop()))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
