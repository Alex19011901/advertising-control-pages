from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_dashboard_with_metrika as mod
from build_dashboard_with_metrika import enrich_leads
from build_dashboard_with_metrika import map_status_from_payload


class MetrikaClientJoinTests(unittest.TestCase):
    def test_unique_session_window_is_exactly_attributed(self) -> None:
        client_hash = "abc"
        leads = [{
            "lead_id": "lead1",
            "created_at": "2026-09-06T12:25:14+03:00",
            "metrika_client_id_sha256": client_hash,
            "campaign_id": "",
            "group_id": "",
            "ad_id": "",
        }]
        rows = [{
            "client_id_sha256": client_hash,
            "visit_datetime": "2026-09-06 12:20:00",
            "visit_duration_seconds": 600,
            "campaign_id": "118776779",
            "group_id": "5552984252",
            "ad_id": "16902921501",
        }]
        result, matched = enrich_leads(leads, rows)
        self.assertEqual(matched, 1)
        self.assertEqual(result[0]["campaign_id"], "118776779")
        self.assertEqual(result[0]["group_id"], "5552984252")
        self.assertEqual(result[0]["ad_id"], "16902921501")
        self.assertEqual(result[0]["attribution_method"], "metrika_client_session_exact")

    def test_unique_session_utm_campaign_maps_to_exact_campaign(self) -> None:
        leads = [{
            "lead_id": "lead2",
            "created_at": "2026-09-06T12:25:14+03:00",
            "metrika_client_id_sha256": "abc",
            "campaign_id": "",
            "group_id": "",
            "ad_id": "",
        }]
        rows = [{
            "client_id_sha256": "abc",
            "visit_datetime": "2026-09-06 12:20:00",
            "visit_duration_seconds": 600,
            "campaign_id": "",
            "group_id": "",
            "ad_id": "",
            "utm_campaign": "Svadba_poisk",
        }]
        result, matched = enrich_leads(leads, rows, {"Svadba_poisk": "118776779"})
        self.assertEqual(matched, 1)
        self.assertEqual(result[0]["campaign_id"], "118776779")
        self.assertEqual(result[0]["group_id"], "")
        self.assertEqual(result[0]["ad_id"], "")
        self.assertEqual(result[0]["attribution_method"], "metrika_client_session_utm_campaign_exact")

    def test_multiple_overlapping_sessions_are_not_guessed(self) -> None:
        leads = [{"created_at": "2026-09-06T12:25:14+03:00", "metrika_client_id_sha256": "abc"}]
        rows = [
            {"client_id_sha256": "abc", "visit_datetime": "2026-09-06 12:20:00", "visit_duration_seconds": 600, "ad_id": "1"},
            {"client_id_sha256": "abc", "visit_datetime": "2026-09-06 12:24:00", "visit_duration_seconds": 600, "ad_id": "2"},
        ]
        result, matched = enrich_leads(leads, rows)
        self.assertEqual(matched, 0)
        self.assertEqual(result[0]["attribution_method"], "ambiguous_client_sessions")
        self.assertFalse(result[0].get("ad_id"))

    def test_prior_visit_outside_session_is_not_guessed(self) -> None:
        leads = [{
            "lead_id": "lead3",
            "created_at": "2026-09-14T13:19:27+03:00",
            "metrika_client_id_sha256": "abc",
        }]
        rows = [
            {"client_id_sha256": "abc", "visit_datetime": "2026-09-12 10:20:00", "visit_duration_seconds": 0, "campaign_id": "old"},
            {"client_id_sha256": "abc", "visit_datetime": "2026-09-14 12:40:00", "visit_duration_seconds": 0, "campaign_id": "new"},
        ]
        result, matched = enrich_leads(leads, rows)
        self.assertEqual(matched, 0)
        self.assertFalse(result[0].get("campaign_id"))
        self.assertEqual(result[0]["attribution_method"], "client_id_no_session_match")

    def test_counter_mismatch_map_is_rejected(self) -> None:
        status, payload = map_status_from_payload("remote_legacy", "url", {
            "counter_id": 112267492,
            "rows": [{"client_id_sha256": "abc", "campaign_id": "123"}],
        })
        self.assertEqual(status["status"], "counter_mismatch")
        self.assertEqual(payload["rows"], [])

    def test_attribution_mismatch_map_is_rejected(self) -> None:
        status, payload = map_status_from_payload("remote_legacy", "url", {
            "counter_id": 52597240,
            "attribution": "LAST_YANDEX_DIRECT_CLICK",
            "rows": [{"client_id_sha256": "abc", "campaign_id": "123"}],
        })
        self.assertEqual(status["status"], "attribution_mismatch")
        self.assertEqual(payload["rows"], [])

    def test_local_missing_secret_falls_back_to_remote_map(self) -> None:
        class FakeResponse:
            def __enter__(self) -> FakeResponse:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps({
                    "status": "ok",
                    "counter_id": 52597240,
                    "attribution": "AUTOMATIC",
                    "rows": [{"client_id_sha256": "abc", "campaign_id": "123"}],
                }).encode("utf-8")

        def fake_urlopen(*_args: object, **_kwargs: object) -> FakeResponse:
            return FakeResponse()

        old_local = mod.LOCAL_METRIKA_EXPORT
        old_url = mod.METRIKA_ATTRIBUTION_URL
        old_urlopen = mod.urlopen
        try:
            with tempfile.TemporaryDirectory() as tmp:
                local = Path(tmp) / "metrika.json"
                local.write_text(json.dumps({
                    "status": "missing_secret",
                    "counter_id": 52597240,
                    "message": "GitHub Actions secret is not configured.",
                    "rows": [],
                }), encoding="utf-8")
                mod.LOCAL_METRIKA_EXPORT = local
                mod.METRIKA_ATTRIBUTION_URL = "https://example.test/metrika_attribution_map_52597240.json"
                mod.urlopen = fake_urlopen

                status, payload = mod.load_map()

            self.assertEqual(status["status"], "ok")
            self.assertEqual(status["source"], "remote_legacy")
            self.assertEqual(payload["rows"], [{"client_id_sha256": "abc", "campaign_id": "123"}])
        finally:
            mod.LOCAL_METRIKA_EXPORT = old_local
            mod.METRIKA_ATTRIBUTION_URL = old_url
            mod.urlopen = old_urlopen


if __name__ == "__main__":
    unittest.main()
