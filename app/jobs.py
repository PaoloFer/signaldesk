from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from app.database import (
    add_processing_log,
    all_contents,
    background_job_cancel_requested,
    claim_background_job,
    decrement_transcription_credits,
    delete_all_entity_mentions,
    finish_background_job,
    finish_source_run,
    get_niche,
    insert_comments,
    list_entities,
    list_niche_channels,
    project_content_targets,
    save_comment_analysis,
    sync_niche_channels,
    transcribed_external_ids,
    unprocessed_comments,
    update_background_job,
    upsert_contents,
    upsert_contents_for_niche,
    upsert_entity_mentions,
    upsert_transcript,
)
from app.connectors import YouTubeConnector
from app.entity_extraction import extract_entities_from_contents
from app.niche_discovery import expand_niche
from app.panorama import build_panorama
from app.nlp import analyze_comment
from app.transcription_intelligence import (
    TranscriptionError,
    analyze_transcript,
    fetch_transcript,
)
from app.youtube import YouTubeAPIError, discover_videos, fetch_video_comments


def process_next_job() -> bool:
    job = claim_background_job()
    if not job:
        return False
    source_id = None
    try:
        payload = json.loads(job["payload_json"])
        source_id = payload.get("source_id")
        if job["job_type"] == "youtube_discovery":
            result = _run_discovery(job["id"], job["project_id"], payload)
        elif job["job_type"] == "niche_discovery":
            result = _run_niche_discovery(job["id"], job["project_id"], payload)
        elif job["job_type"] == "niche_populate":
            result = _run_niche_populate(job["id"], job["project_id"], payload)
        elif job["job_type"] == "panorama_materialize":
            result = _run_panorama_materialize(job["id"], job["project_id"], payload)
        elif job["job_type"] == "youtube_bulk_comments":
            result = _run_bulk_comments(job["id"], job["project_id"], payload)
        elif job["job_type"] == "comment_analysis":
            result = _run_comment_analysis(job["id"], job["project_id"], payload)
        elif job["job_type"] == "entity_extraction":
            result = _run_entity_extraction(job["id"], job["project_id"], payload)
        elif job["job_type"] == "transcript_investigation":
            result = _run_transcript_investigation(job["id"], job["project_id"], payload)
        else:
            raise ValueError(f"Tipo di job non supportato: {job['job_type']}")
        if background_job_cancel_requested(job["id"]):
            finish_background_job(job["id"], "cancelled", result)
        else:
            finish_background_job(job["id"], "completed", result)
        if source_id:
            finish_source_run(int(source_id))
    except Exception as exc:
        finish_background_job(job["id"], "failed", error=str(exc))
        if source_id:
            finish_source_run(int(source_id), error=str(exc))
        try:
            add_processing_log(
                job["project_id"], "error",
                {
                    "job_id": job["id"], "job_type": job["job_type"],
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        except Exception:
            # Il log degli errori non deve mai interrompere il worker.
            pass
    return True


def _run_discovery(job_id: int, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    update_background_job(job_id, 15)
    contents = discover_videos(
        api_key=_api_key(), query=payload["query"], niche=payload["niche"],
        topic=payload.get("topic", ""), days=int(payload.get("days", 30)),
        max_results=int(payload.get("max_results", 25)),
    )
    if background_job_cancel_requested(job_id):
        return {"received": len(contents), "stored": 0}
    update_background_job(job_id, 80)
    stored = upsert_contents(contents, project_id)
    return {"query": payload["query"], "received": len(contents), "stored": stored}


def _run_niche_discovery(job_id: int, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    niche = get_niche(int(payload["niche_id"]))
    if not niche:
        raise ValueError("Nicchia non trovata")
    update_background_job(job_id, 10)
    connector = YouTubeConnector(api_key=_api_key())
    contents = expand_niche(niche, connector=connector)
    if background_job_cancel_requested(job_id):
        return {"received": len(contents), "stored": 0, "project_linked": 0}
    update_background_job(job_id, 50)
    result = upsert_contents_for_niche(project_id, niche["id"], niche["name"], contents)

    filters = niche.get("filters", {})
    if filters.get("auto_fetch_comments", True) and contents:
        sorted_contents = sorted(
            contents, key=lambda c: c.get("relevance_score", 0), reverse=True
        )
        max_comment_videos = int(filters.get("max_comment_videos", 5))
        comments_per_video = int(filters.get("comments_per_video", 50))
        include_replies = bool(filters.get("include_replies", False))
        targets = sorted_contents[:max_comment_videos]

        received = 0
        imported = 0
        errors: list[dict[str, str]] = []
        for index, content in enumerate(targets):
            if background_job_cancel_requested(job_id):
                break
            try:
                _, comments = connector.fetch_comments(
                    content["external_id"],
                    niche=niche["name"],
                    topic=content.get("topic", ""),
                    max_comments=comments_per_video,
                    include_replies=include_replies,
                    content_title=content.get("title", ""),
                )
                received += len(comments)
                imported += insert_comments(comments, project_id)
            except YouTubeAPIError as exc:
                errors.append({"video_id": content["external_id"], "error": str(exc)})
            progress = 50 + round((index + 1) / max(len(targets), 1) * 40)
            update_background_job(job_id, progress)

        result["comments_received"] = received
        result["comments_imported"] = imported
        result["comment_errors"] = errors

    update_background_job(job_id, 95)
    analyzed = _analyze_new_comments(project_id, limit=500)
    result["comments_analyzed"] = analyzed

    return {
        "niche": niche["name"],
        "received": len(contents),
        **result,
    }


def _analyze_new_comments(project_id: int, limit: int = 500) -> int:
    analyzed = 0
    while True:
        batch = unprocessed_comments(project_id, limit=100)
        if not batch:
            break
        analyses = [analyze_comment(c["id"], c["text"]) for c in batch]
        save_comment_analysis(analyses)
        analyzed += len(analyses)
        if analyzed >= limit:
            break
    return analyzed


def _run_comment_analysis(job_id: int, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    limit = int(payload.get("limit", 500))
    analyzed = 0
    total = 0
    while True:
        if background_job_cancel_requested(job_id):
            break
        batch = unprocessed_comments(project_id, limit=100)
        if not batch:
            break
        total += len(batch)
        analyses = [analyze_comment(c["id"], c["text"]) for c in batch]
        save_comment_analysis(analyses)
        analyzed += len(analyses)
        progress = min(95, round(analyzed / max(total, 1) * 90) + 5)
        update_background_job(job_id, progress)
        if analyzed >= limit:
            break
    add_processing_log(
        project_id, "comment_analysis",
        {"analyzed": analyzed, "limit": limit},
    )
    return {"analyzed": analyzed}


def _run_niche_populate(job_id: int, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    niche = get_niche(int(payload["niche_id"]))
    if not niche:
        raise ValueError("Nicchia non trovata")
    update_background_job(job_id, 10)
    connector = YouTubeConnector(api_key=_api_key())
    contents = expand_niche(niche, connector=connector)
    selected_ids = set(payload.get("content_ids", []))
    if selected_ids:
        contents = [c for c in contents if c["external_id"] in selected_ids]
    if background_job_cancel_requested(job_id):
        return {"received": len(contents), "stored": 0, "project_linked": 0}
    update_background_job(job_id, 40)
    result = upsert_contents_for_niche(project_id, niche["id"], niche["name"], contents)

    if payload.get("auto_fetch_comments", True) and contents:
        sorted_contents = sorted(
            contents, key=lambda c: c.get("relevance_score", 0), reverse=True
        )
        max_comment_videos = int(payload.get("max_comment_videos", 5))
        comments_per_video = int(payload.get("comments_per_video", 50))
        include_replies = bool(payload.get("include_replies", False))
        targets = sorted_contents[:max_comment_videos]

        received = 0
        imported = 0
        errors: list[dict[str, str]] = []
        for index, content in enumerate(targets):
            if background_job_cancel_requested(job_id):
                break
            try:
                _, comments = connector.fetch_comments(
                    content["external_id"],
                    niche=niche["name"],
                    topic=content.get("topic", ""),
                    max_comments=comments_per_video,
                    include_replies=include_replies,
                    content_title=content.get("title", ""),
                )
                received += len(comments)
                imported += insert_comments(comments, project_id)
            except YouTubeAPIError as exc:
                errors.append({"video_id": content["external_id"], "error": str(exc)})
            progress = 40 + round((index + 1) / max(len(targets), 1) * 45)
            update_background_job(job_id, progress)

        result["comments_received"] = received
        result["comments_imported"] = imported
        result["comment_errors"] = errors

    update_background_job(job_id, 95)
    analyzed = _analyze_new_comments(project_id, limit=500)
    result["comments_analyzed"] = analyzed

    return {
        "niche": niche["name"],
        "received": len(contents),
        **result,
    }


def _filter_panorama_channels(
    channels: list[dict[str, Any]], definition: dict[str, Any],
) -> list[dict[str, Any]]:
    """Applica sul pool le regole persistite dal Niche Lab."""
    filters = (
        definition.get("local_filters")
        or definition.get("selection_filters")
        or definition.get("filters")
        or {}
    )
    include = {
        str(term).lower()
        for term in (filters.get("include_themes") or filters.get("themes_include") or [])
    }
    exclude = {
        str(term).lower()
        for term in (filters.get("exclude_themes") or filters.get("themes_exclude") or [])
    }
    minimum_subscribers = int(filters.get("min_subscribers", 0) or 0)
    maximum_subscribers = int(filters.get("max_subscribers", 0) or 0)
    minimum_views = int(filters.get("min_views", 0) or 0)
    maximum_views = int(filters.get("max_views", 0) or 0)
    minimum_score = float(filters.get("min_score", 0) or 0)
    country = str(filters.get("country", "") or "").upper()
    language = str(filters.get("language", "") or "").lower()
    promoted_only = bool(filters.get("promoted_only", False))
    result = []
    for channel in channels:
        themes = {theme["term"].lower() for theme in channel.get("themes", [])}
        subscribers = int(channel.get("subscribers", 0) or 0)
        if minimum_subscribers and subscribers < minimum_subscribers:
            continue
        if maximum_subscribers and subscribers > maximum_subscribers:
            continue
        if minimum_views and int(channel.get("total_views", 0) or 0) < minimum_views:
            continue
        if maximum_views and int(channel.get("total_views", 0) or 0) > maximum_views:
            continue
        if float(channel.get("score", 0) or 0) < minimum_score:
            continue
        if include and not include.intersection(themes):
            continue
        if exclude.intersection(themes):
            continue
        if country and str(channel.get("country", "")).upper() != country:
            continue
        if language and not str(channel.get("language", "")).lower().startswith(language):
            continue
        if promoted_only and not channel.get("promoted"):
            continue
        result.append(channel)
    return result


def _run_panorama_materialize(
    job_id: int, project_id: int, payload: dict[str, Any],
) -> dict[str, Any]:
    niche = get_niche(int(payload["niche_id"]))
    if not niche or niche["project_id"] != project_id:
        raise ValueError("Nicchia non trovata nel progetto")
    update_background_job(job_id, 10)
    stats: dict[str, Any] = {}
    panorama = build_panorama(
        niche, connector=YouTubeConnector(api_key=_api_key()), stats=stats,
    )
    channels = panorama["channels"]
    definition = niche.get("definition") or {}
    membership_mode = payload.get("membership_mode") or definition.get(
        "membership_mode", "rule_based"
    )
    selected_ids = set(payload.get("channel_ids") or [])
    if membership_mode == "curated":
        if not selected_ids:
            selected_ids = {
                channel["channel_id"] for channel in list_niche_channels(niche["id"])
            }
        channels = [channel for channel in channels if channel["channel_id"] in selected_ids]
    else:
        channels = _filter_panorama_channels(channels, definition)
    if background_job_cancel_requested(job_id):
        return {"channels": len(channels), "stored": 0}

    update_background_job(job_id, 65)
    memberships = sync_niche_channels(project_id, niche["id"], channels, replace=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    contents: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for channel in channels:
        for video in channel.get("videos", []):
            key = (video.get("platform", channel.get("platform", "YouTube")), video["external_id"])
            if key in seen:
                continue
            seen.add(key)
            contents.append({
                **video,
                "platform": key[0],
                "channel_id": channel["channel_id"],
                "channel_title": channel.get("channel_title", ""),
                "niche": niche["name"],
                "topic": niche.get("description", ""),
                "source_query": video.get("source_query") or "panorama_materialize",
                "acquired_at": video.get("acquired_at") or now,
                "relevance_score": channel.get("score", 0.0),
                "matched_seed": "channel",
                "matched_value": channel["channel_id"],
            })
    result = upsert_contents_for_niche(
        project_id, niche["id"], niche["name"], contents,
    ) if contents else {"stored": 0, "project_linked": 0}
    update_background_job(job_id, 95)
    return {
        "niche": niche["name"],
        "channels": len(memberships),
        "contents": len(contents),
        "stats": stats,
        **result,
    }


def _run_bulk_comments(job_id: int, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    targets = project_content_targets(
        project_id, payload.get("niche"), int(payload.get("video_limit", 5))
    )
    received = 0
    imported = 0
    errors = []
    for index, target in enumerate(targets):
        if background_job_cancel_requested(job_id):
            break
        try:
            _, comments = fetch_video_comments(
                api_key=_api_key(), video=target["external_id"],
                niche=target["niche"], topic=target["topic"],
                max_comments=int(payload.get("comments_per_video", 50)),
                salt=os.getenv("PSEUDONYM_SALT", "signaldesk-development-only"),
                content_title=target["title"],
                include_replies=payload.get("include_replies", False),
            )
            received += len(comments)
            imported += insert_comments(comments, project_id)
        except YouTubeAPIError as exc:
            errors.append({"video_id": target["external_id"], "error": str(exc)})
        update_background_job(job_id, round((index + 1) / max(len(targets), 1) * 95))
    return {
        "videos_requested": len(targets),
        "videos_completed": len(targets) - len(errors),
        "comments_received": received,
        "comments_imported": imported,
        "errors": errors,
    }


def _run_entity_extraction(job_id: int, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    contents = all_contents(project_id)
    if not contents:
        return {"contents": 0, "mentions_stored": 0, "entities_created": 0}

    if payload.get("full_refresh"):
        delete_all_entity_mentions(project_id)

    total = len(contents)
    mentions: list[dict[str, Any]] = []
    entities_created = 0
    mentions_stored = 0
    batch_size = 50

    for index, item in enumerate(contents):
        if background_job_cancel_requested(job_id):
            break
        batch_mentions = extract_entities_from_contents([item], project_id)
        mentions.extend(batch_mentions)
        if len(mentions) >= batch_size or index == total - 1:
            result = upsert_entity_mentions(project_id, mentions)
            entities_created += result["entities_created"]
            mentions_stored += result["mentions_stored"]
            mentions = []
        progress = min(95, round((index + 1) / max(total, 1) * 95))
        update_background_job(job_id, progress)

    add_processing_log(
        project_id, "entity_extraction",
        {"contents": total, "mentions_stored": mentions_stored, "entities_created": entities_created},
    )
    return {
        "contents": total,
        "mentions_stored": mentions_stored,
        "entities_created": entities_created,
    }


def _run_transcript_investigation(job_id: int, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Indagine premium: scarica e analizza le trascrizioni dei video richiesti.

    Ogni video tentato consuma 1 credito progetto (addebitato a prescindere
    dall'esito, perché il costo di estrazione è reale). I video già
    investigati con successo vengono saltati senza addebito.
    """
    video_ids = list(dict.fromkeys(payload.get("external_ids", [])))
    known_brands = [entity["name"] for entity in list_entities(project_id, limit=500)]
    already_done = transcribed_external_ids(project_id)

    processed = 0
    skipped = 0
    ad_reads = 0
    errors: list[dict[str, str]] = []
    for index, video_id in enumerate(video_ids):
        if background_job_cancel_requested(job_id):
            break
        if video_id in already_done:
            skipped += 1
            continue
        if not decrement_transcription_credits(project_id, 1):
            errors.append({"video_id": video_id, "error": "crediti trascrizione esauriti"})
            break
        try:
            transcript = fetch_transcript(video_id)
            analysis = analyze_transcript(transcript["segments"], known_brands=known_brands)
            upsert_transcript(project_id, {
                "external_id": video_id,
                "language": transcript["language"],
                "kind": transcript["kind"],
                "status": "ok",
                "text": transcript["text"],
                "segments": transcript["segments"],
                "analysis": analysis,
            })
            if analysis["ad_read_detected"]:
                ad_reads += 1
        except TranscriptionError as exc:
            upsert_transcript(project_id, {
                "external_id": video_id, "status": "no_captions", "error": str(exc)[:500],
            })
            errors.append({"video_id": video_id, "error": str(exc)[:200]})
        except Exception as exc:  # difensivo: un video non deve bloccare il job
            upsert_transcript(project_id, {
                "external_id": video_id, "status": "error", "error": str(exc)[:500],
            })
            errors.append({"video_id": video_id, "error": str(exc)[:200]})
        processed += 1
        update_background_job(job_id, min(95, round((index + 1) / max(len(video_ids), 1) * 95)))

    result = {
        "requested": len(video_ids),
        "processed": processed,
        "skipped_already_done": skipped,
        "ad_reads_detected": ad_reads,
        "errors": errors,
    }
    add_processing_log(project_id, "transcript_investigation", result)
    return result


def _api_key() -> str:
    value = os.getenv("YOUTUBE_API_KEY")
    if not value:
        raise YouTubeAPIError("YOUTUBE_API_KEY non configurata")
    return value
