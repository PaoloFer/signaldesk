import unittest

from datetime import datetime, timezone

from app.youtube import (
    discover_videos,
    extract_video_id,
    fetch_channel_details,
    fetch_channel_upload_video_ids,
    fetch_popular_video_ids,
    fetch_video_comments,
    fetch_video_metrics,
    parse_channel_reference,
    parse_duration,
    pseudonymize,
    resolve_channel_id,
    search_videos,
)


class YouTubeConnectorTest(unittest.TestCase):
    def test_extracts_ids_from_supported_urls(self):
        video_id = "dQw4w9WgXcQ"
        self.assertEqual(extract_video_id(video_id), video_id)
        self.assertEqual(extract_video_id(f"https://youtu.be/{video_id}"), video_id)
        self.assertEqual(extract_video_id(f"https://www.youtube.com/watch?v={video_id}"), video_id)
        self.assertEqual(extract_video_id(f"https://youtube.com/shorts/{video_id}"), video_id)

    def test_pseudonyms_are_stable_but_salt_specific(self):
        self.assertEqual(pseudonymize("author", "salt"), pseudonymize("author", "salt"))
        self.assertNotEqual(pseudonymize("author", "salt"), pseudonymize("author", "other"))
        self.assertNotIn("author", pseudonymize("author", "salt"))

    def test_parses_iso_video_duration(self):
        self.assertEqual(parse_duration("PT1H2M3S"), 3723)
        self.assertEqual(parse_duration("PT8M12S"), 492)

    def test_maps_api_comments_without_storing_public_author_name(self):
        responses = iter([
            {"items": [{"snippet": {"title": "Video test", "channelTitle": "Canale"}}]},
            {"items": [{"snippet": {"topLevelComment": {"id": "comment-1", "snippet": {
                "authorDisplayName": "Nome pubblico",
                "authorChannelId": {"value": "channel-123"},
                "textDisplay": "Commento reale",
                "publishedAt": "2026-09-17T10:00:00Z",
            }}}}]},
        ])

        metadata, comments = fetch_video_comments(
            "key", "dQw4w9WgXcQ", "Musica", "Ascolto", 10, "salt",
            request_json=lambda _: next(responses),
        )

        self.assertEqual(metadata["title"], "Video test")
        self.assertEqual(comments[0]["text"], "Commento reale")
        self.assertTrue(comments[0]["author_hash"].startswith("yt-"))
        self.assertNotIn("Nome pubblico", str(comments[0]))

    def test_discovers_public_videos_and_maps_statistics(self):
        responses = iter([
            {"items": [{"id": {"videoId": "dQw4w9WgXcQ"}}]},
            {"items": [{
                "id": "dQw4w9WgXcQ",
                "snippet": {
                    "title": "Correre piano", "description": "Test",
                    "channelId": "channel-1", "channelTitle": "Run Lab",
                    "publishedAt": "2026-09-16T10:00:00Z",
                },
                "statistics": {"viewCount": "12000", "likeCount": "800", "commentCount": "42"},
                "contentDetails": {"duration": "PT8M12S"},
            }]},
        ])
        contents = discover_videos(
            "key", "corsa lenta", "Running", request_json=lambda _: next(responses),
            now=datetime(2026, 9, 17, tzinfo=timezone.utc),
        )
        self.assertEqual(contents[0]["views"], 12000)
        self.assertEqual(contents[0]["duration_seconds"], 492)
        self.assertEqual(contents[0]["source_query"], "corsa lenta")

    def test_refreshes_video_metrics(self):
        payload = {"items": [{"id": "video-1", "statistics": {
            "viewCount": "1500", "likeCount": "90", "commentCount": "12",
        }}]}
        metrics = fetch_video_metrics("key", ["video-1"], request_json=lambda _: payload)
        self.assertEqual(metrics[0]["views"], 1500)
        self.assertEqual(metrics[0]["comments"], 12)

    def test_search_videos_adds_region_and_language_to_query(self):
        captured = []
        payload = {"items": [{"id": {"videoId": "dQw4w9WgXcQ"}}]}
        ids = search_videos(
            "key", query="vlog", region_code="it", relevance_language="IT",
            request_json=lambda url: captured.append(url) or payload,
            now=datetime(2026, 9, 17, tzinfo=timezone.utc),
        )
        self.assertEqual(ids, ["dQw4w9WgXcQ"])
        self.assertIn("regionCode=IT", captured[0])
        self.assertIn("relevanceLanguage=it", captured[0])

    def test_fetch_popular_uses_chart_and_region_with_minimal_quota(self):
        captured = []
        payload = {"items": [{"id": "video-1"}, {"id": "video-2"}]}
        ids = fetch_popular_video_ids(
            "key", "it", request_json=lambda url: captured.append(url) or payload,
        )
        self.assertEqual(ids, ["video-1", "video-2"])
        self.assertIn("chart=mostPopular", captured[0])
        self.assertIn("regionCode=IT", captured[0])
        self.assertNotIn("/search?", captured[0])

    def test_fetch_channel_details_maps_declared_geo_signals(self):
        payload = {"items": [
            {
                "id": "UCit",
                "snippet": {"title": "Creator", "country": "IT", "defaultLanguage": "it", "publishedAt": "2025-01-02T10:00:00Z"},
                "statistics": {"subscriberCount": "1200000", "videoCount": "350"},
            },
            {
                "id": "UCunknown",
                "snippet": {"title": "Senza dichiarazioni"},
                "statistics": {"subscriberCount": "8000", "videoCount": "40"},
            },
        ]}
        details = fetch_channel_details("key", ["UCit", "UCunknown"], request_json=lambda _: payload)
        self.assertEqual(details["UCit"]["country"], "IT")
        self.assertEqual(details["UCit"]["default_language"], "it")
        self.assertEqual(details["UCit"]["subscribers"], 1200000)
        self.assertEqual(details["UCit"]["published_at"], "2025-01-02T10:00:00Z")
        # Paese e lingua non dichiarati restano vuoti, non inventati.
        self.assertEqual(details["UCunknown"]["country"], "")
        self.assertEqual(details["UCunknown"]["default_language"], "")

    def test_fetch_channel_uploads_uses_playlist_without_search(self):
        captured = []

        def request(url):
            captured.append(url)
            if "/channels?" in url:
                return {"items": [{
                    "id": "UCit", "snippet": {"title": "Creator"}, "statistics": {},
                    "contentDetails": {"relatedPlaylists": {"uploads": "UUuploads"}},
                }]}
            return {"items": [
                {"contentDetails": {"videoId": "video-id-01"}},
                {"contentDetails": {"videoId": "video-id-02"}},
            ]}

        result = fetch_channel_upload_video_ids(
            "key", ["UCit"], max_results_per_channel=2, request_json=request,
        )
        self.assertEqual(result["UCit"], ["video-id-01", "video-id-02"])
        self.assertTrue(any("/playlistItems?" in url for url in captured))
        self.assertFalse(any("/search?" in url for url in captured))

    def test_unavailable_upload_playlist_does_not_break_other_channels(self):
        def request(url):
            if "/channels?" in url:
                return {"items": [
                    {"id": "UCbad", "snippet": {}, "statistics": {}, "contentDetails": {"relatedPlaylists": {"uploads": "UUbad"}}},
                    {"id": "UCgood", "snippet": {}, "statistics": {}, "contentDetails": {"relatedPlaylists": {"uploads": "UUgood"}}},
                ]}
            if "playlistId=UUbad" in url:
                from app.youtube import YouTubeAPIError
                raise YouTubeAPIError("playlist non disponibile")
            return {"items": [{"contentDetails": {"videoId": "video-id-01"}}]}

        result = fetch_channel_upload_video_ids(
            "key", ["UCbad", "UCgood"], max_results_per_channel=1, request_json=request,
        )
        self.assertEqual(result["UCbad"], [])
        self.assertEqual(result["UCgood"], ["video-id-01"])

    def test_parses_channel_references(self):
        channel_id = "UC" + "a" * 22
        self.assertEqual(parse_channel_reference(channel_id), {"kind": "id", "value": channel_id})
        self.assertEqual(
            parse_channel_reference(f"https://youtube.com/channel/{channel_id}"),
            {"kind": "id", "value": channel_id},
        )
        self.assertEqual(parse_channel_reference("@marcelloascani"), {"kind": "handle", "value": "marcelloascani"})
        self.assertEqual(parse_channel_reference("marcelloascani"), {"kind": "handle", "value": "marcelloascani"})
        self.assertEqual(
            parse_channel_reference("https://youtube.com/@marcelloascani"),
            {"kind": "handle", "value": "marcelloascani"},
        )
        # Un nome libero con spazi non è risolvibile in modo deterministico.
        self.assertEqual(parse_channel_reference("Marcello Ascani"), {"kind": "name", "value": "Marcello Ascani"})

    def test_resolve_channel_id_passes_ids_without_api_calls(self):
        channel_id = "UC" + "b" * 22
        calls = []
        resolved = resolve_channel_id(
            "key", channel_id, request_json=lambda url: calls.append(url) or {},
        )
        self.assertEqual(resolved, channel_id)
        self.assertEqual(calls, [])

    def test_resolve_channel_id_resolves_handles_with_minimal_quota(self):
        captured = []
        payload = {"items": [{"id": "UC" + "c" * 22}]}
        resolved = resolve_channel_id(
            "key", "@marcelloascani", request_json=lambda url: captured.append(url) or payload,
        )
        self.assertEqual(resolved, "UC" + "c" * 22)
        self.assertIn("forHandle=marcelloascani", captured[0])
        self.assertIn("/channels?", captured[0])
        self.assertNotIn("/search?", captured[0])

    def test_resolve_channel_id_returns_none_for_unresolvable_references(self):
        self.assertIsNone(resolve_channel_id("key", "Marcello Ascani", request_json=lambda _: {}))
        payload = {"items": []}
        self.assertIsNone(resolve_channel_id("key", "@handleinesistente", request_json=lambda _: payload))

    def test_includes_replies_when_requested(self):
        top_comment = {
            "id": "top-1",
            "snippet": {
                "authorDisplayName": "A",
                "authorChannelId": {"value": "channel-1"},
                "textDisplay": "Top level",
                "publishedAt": "2026-09-17T10:00:00Z",
            },
        }
        reply_comment = {
            "id": "reply-1",
            "snippet": {
                "authorDisplayName": "B",
                "authorChannelId": {"value": "channel-2"},
                "textDisplay": "Risposta",
                "publishedAt": "2026-09-17T11:00:00Z",
            },
        }
        responses = iter([
            {"items": [{"snippet": {"title": "Video test", "channelTitle": "Canale"}}]},
            {"items": [{"snippet": {"topLevelComment": top_comment}, "replies": {"comments": [reply_comment]}}]},
        ])

        _, comments = fetch_video_comments(
            "key", "dQw4w9WgXcQ", "Musica", "Ascolto", 10, "salt",
            request_json=lambda _: next(responses), include_replies=True,
        )
        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[1]["text"], "Risposta")


if __name__ == "__main__":
    unittest.main()
