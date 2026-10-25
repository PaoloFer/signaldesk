from __future__ import annotations

import os
from datetime import datetime, timezone

from app.database import (
    finish_monitoring_run,
    refreshable_content_ids,
    start_monitoring_run,
    update_content_metrics,
)
from app.youtube import fetch_video_metrics


def perform_metrics_refresh(
    trigger: str, niche: str | None = None, limit: int = 200,
    project_id: int | None = None,
) -> dict:
    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    run_id = start_monitoring_run(trigger, started_at, project_id)
    video_ids = refreshable_content_ids(niche, limit, project_id)
    if not video_ids:
        finish_monitoring_run(run_id, started_at, "completed")
        return {"run_id": run_id, "requested": 0, "received": 0, "updated": 0, "captured_at": None}
    try:
        metrics = fetch_video_metrics(os.environ["YOUTUBE_API_KEY"], video_ids)
        captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        updated = update_content_metrics(metrics, captured_at)
        finish_monitoring_run(
            run_id, captured_at, "completed", len(video_ids), len(metrics), updated
        )
        return {
            "run_id": run_id, "requested": len(video_ids), "received": len(metrics),
            "updated": updated, "captured_at": captured_at,
        }
    except Exception as exc:
        finished_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        finish_monitoring_run(
            run_id, finished_at, "failed", len(video_ids), error=str(exc)
        )
        raise
