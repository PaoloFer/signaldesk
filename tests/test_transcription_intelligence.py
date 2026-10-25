import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database
from app.transcription_intelligence import (
    TranscriptionError,
    _extract_json_array,
    analyze_transcript,
    fetch_transcript,
    find_campaign_clusters,
)


WATCH_PAGE = """
<html><script>var ytInitialPlayerResponse = {"captions": {"playerCaptionsTracklistRenderer":
{"captionTracks": [
{"baseUrl": "https://www.youtube.com/api/timedtext?v=abc&lang=en", "languageCode": "en", "kind": "asr"},
{"baseUrl": "https://www.youtube.com/api/timedtext?v=abc&lang=it", "languageCode": "it",
 "name": {"simpleText": "Italiano [manuale]"}}
]}}};</script></html>
"""

TIMEDTEXT = """<?xml version="1.0" encoding="utf-8" ?>
<timedtext format="3">
<body>
<text start="0" dur="3.5">Ciao a tutti ragazzi e bentornati</text>
<text start="3.5" dur="4">questo video è sponsorizzato da NordVPN</text>
<text start="7.5" dur="4">usate il codice SCONTO10 per provarlo</text>
<text start="11.5" dur="4">cliccate il link in descrizione</text>
<text start="15.5" dur="5">ora torniamo all&apos;allenamento di oggi</text>
</body>
</timedtext>
"""


def _fake_fetcher(url: str) -> str:
    if "watch" in url:
        return WATCH_PAGE
    return TIMEDTEXT


def _segments(texts, step=5.0):
    return [
        {"start": index * step, "duration": step - 1, "text": text}
        for index, text in enumerate(texts)
    ]


class TranscriptFetchTest(unittest.TestCase):
    def test_fetches_and_parses_preferred_track(self):
        transcript = fetch_transcript("abc", fetcher=_fake_fetcher)
        self.assertEqual(transcript["language"], "it")
        self.assertEqual(transcript["kind"], "manual")
        self.assertEqual(len(transcript["segments"]), 5)
        self.assertIn("sponsorizzato", transcript["text"])

    def test_manual_track_preferred_over_asr(self):
        # La traccia italiana manuale vince su quella inglese automatica.
        transcript = fetch_transcript("abc", languages=("it", "en"), fetcher=_fake_fetcher)
        self.assertEqual(transcript["kind"], "manual")

    def test_missing_captions_raises(self):
        def no_captions_fetcher(url):
            return "<html>nessun player</html>"

        with self.assertRaises(TranscriptionError):
            fetch_transcript("abc", fetcher=no_captions_fetcher)

    def test_json_array_extraction_tolerates_brackets_in_strings(self):
        page = '{"captionTracks": [{"name": "Italiano [manuale]", "baseUrl": "x"}]}'
        tracks = _extract_json_array(page, '"captionTracks"')
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["name"], "Italiano [manuale]")


class AdReadAnalysisTest(unittest.TestCase):
    def test_detects_ad_read_with_brand_and_cta(self):
        transcript = fetch_transcript("abc", fetcher=_fake_fetcher)
        analysis = analyze_transcript(transcript["segments"], known_brands=["NordVPN"])
        self.assertTrue(analysis["ad_read_detected"])
        self.assertGreaterEqual(analysis["sponsor_score"], 0.9)
        self.assertIn("NordVPN", analysis["brands"])
        suspicious = analysis["suspicious_segments"]
        self.assertTrue(suspicious)
        self.assertIn("questo video è sponsorizzato", suspicious[0]["triggers"])

    def test_normal_speech_not_flagged(self):
        segments = _segments([
            "oggi parliamo di allenamento per la corsa",
            "la cosa importante è la costanza negli allenamenti",
            "vediamo come migliorare la tecnica di corsa",
            "ricordate di idratarvi bene durante l'uscita",
        ])
        analysis = analyze_transcript(segments, known_brands=["NordVPN"])
        self.assertFalse(analysis["ad_read_detected"])
        self.assertEqual(analysis["suspicious_segments"], [])

    def test_known_brand_match_is_word_bounded(self):
        segments = _segments(["parliamo di nordvpnica e altre cose tecniche"])
        analysis = analyze_transcript(segments, known_brands=["NordVPN"])
        self.assertNotIn("NordVPN", analysis["brands"])

    def test_empty_segments(self):
        analysis = analyze_transcript([])
        self.assertEqual(analysis["sponsor_score"], 0.0)
        self.assertEqual(analysis["chunks_analyzed"], 0)


class CampaignClusterTest(unittest.TestCase):
    def test_clusters_identical_ad_reads_across_channels(self):
        entries = [
            {
                "external_id": "v1", "channel": "Canale A",
                "text": "questo video è sponsorizzato da nordvpn usate il codice sconto10 "
                        "cliccate il link in descrizione per approfittare dell offerta",
            },
            {
                "external_id": "v2", "channel": "Canale B",
                "text": "questo video è sponsorizzato da nordvpn usate il codice sconto10 "
                        "cliccate il link in descrizione per approfittare dell offerta oggi",
            },
            {
                "external_id": "v3", "channel": "Canale C",
                "text": "benvenuti in questo nuovo episodio di cucina oggi prepariamo "
                        "la pasta al pomodoro fresco con basilico",
            },
        ]
        clusters = find_campaign_clusters(entries)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["size"], 2)
        self.assertEqual(clusters[0]["videos"], ["v1", "v2"])
        self.assertEqual(clusters[0]["channels"], ["Canale A", "Canale B"])

    def test_no_clusters_when_all_different(self):
        entries = [
            {"external_id": "v1", "channel": "A", "text": "parliamo di scarpe da corsa e tecnica"},
            {"external_id": "v2", "channel": "B", "text": "oggi cuciniamo il risotto ai funghi"},
        ]
        self.assertEqual(find_campaign_clusters(entries), [])


class TranscriptionCreditsTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "transcripts.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_credits_lifecycle(self):
        self.assertEqual(database.get_transcription_credits(1), 25)
        self.assertTrue(database.decrement_transcription_credits(1, 5))
        self.assertEqual(database.get_transcription_credits(1), 20)
        self.assertFalse(database.decrement_transcription_credits(1, 21))
        self.assertEqual(database.get_transcription_credits(1), 20)
        self.assertEqual(database.add_transcription_credits(1, 10), 30)

    def test_new_project_gets_default_credits(self):
        project = database.create_project("Progetto crediti")
        self.assertEqual(project["transcription_credits"], 25)

    @patch("app.jobs.fetch_transcript")
    def test_investigation_job_stores_results_and_consumes_credits(self, mock_fetch):
        from app.jobs import process_next_job

        mock_fetch.return_value = {
            "language": "it",
            "kind": "manual",
            "segments": [{
                "start": 0.0, "duration": 4.0,
                "text": "questo video è sponsorizzato da NordVPN usate il codice X cliccate il link in descrizione",
            }],
            "text": "questo video è sponsorizzato da NordVPN usate il codice X cliccate il link in descrizione",
        }
        job = database.enqueue_background_job(
            1, "transcript_investigation", {"external_ids": ["vid-1", "vid-2"]}
        )
        self.assertTrue(process_next_job())
        finished = database.background_job(job["id"])
        self.assertEqual(finished["status"], "completed")
        result = json.loads(finished["result_json"])
        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["ad_reads_detected"], 2)

        transcripts = database.list_transcripts(1)
        self.assertEqual(len(transcripts), 2)
        self.assertTrue(all(item["analysis"]["ad_read_detected"] for item in transcripts))
        self.assertEqual(database.get_transcription_credits(1), 23)

        # Un secondo giro sugli stessi video non scala altri crediti.
        database.enqueue_background_job(1, "transcript_investigation", {"external_ids": ["vid-1"]})
        self.assertTrue(process_next_job())
        self.assertEqual(database.get_transcription_credits(1), 23)

    @patch("app.jobs.fetch_transcript")
    def test_no_captions_recorded_but_still_charged(self, mock_fetch):
        from app.jobs import process_next_job

        mock_fetch.side_effect = TranscriptionError("Nessuna traccia sottotitoli disponibile")
        database.enqueue_background_job(1, "transcript_investigation", {"external_ids": ["vid-x"]})
        self.assertTrue(process_next_job())
        transcripts = database.list_transcripts(1)
        self.assertEqual(transcripts[0]["status"], "no_captions")
        self.assertEqual(database.get_transcription_credits(1), 24)


if __name__ == "__main__":
    unittest.main()
