from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_dashboard_with_metrika as mod
from build_dashboard_with_metrika import enrich_leads
from build_dashboard_with_metrika import hostess_call_summary
from build_dashboard_with_metrika import map_status_from_payload
from build_dashboard_with_metrika import tilda_client_id_summary


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

    def test_tilda_client_id_summary_counts_tilda_sources(self) -> None:
        moscow = timezone(timedelta(hours=3))
        summary = tilda_client_id_summary([
            {
                "lead_id": "site-old",
                "created_at": "2026-09-17T10:00:00+03:00",
                "source": "САЙТ ТИЛЬДА",
                "metrika_client_id_sha256": "",
                "attribution_method": "no_client_id",
            },
            {
                "lead_id": "host",
                "created_at": "2026-09-17T11:00:00+03:00",
                "source": "Заявки хост",
                "metrika_client_id_sha256": "",
                "attribution_method": "no_client_id",
            },
            {
                "lead_id": "site-new",
                "created_at": "2026-09-17T12:00:00+03:00",
                "source": "Tilda Veranda",
                "metrika_client_id_sha256": "hash",
                "attribution_method": "client_id_no_session_match",
            },
        ], now=datetime(2026, 9, 17, 13, 0, tzinfo=moscow))
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["with_client_id"], 1)
        self.assertEqual(summary["without_client_id"], 1)
        self.assertEqual(summary["today"], {"total": 2, "with_client_id": 1, "without_client_id": 1})
        self.assertEqual(summary["last_7_days"], {"total": 2, "with_client_id": 1, "without_client_id": 1})
        self.assertEqual(summary["latest"][0]["lead_id"], "site-new")
        self.assertTrue(summary["latest"][0]["has_metrika_client_id"])

    def test_callibri_ids_are_labeled_without_metrika_match(self) -> None:
        leads = [{
            "lead_id": "marquiz-callibri",
            "created_at": "2026-09-17T12:00:00+03:00",
            "source": "MARQUIZ",
            "campaign_id": "712849433",
            "group_id": "5773918659",
            "ad_id": "1915822986185365500",
            "advertising_id_source": "callibri",
        }]
        result, matched = enrich_leads(leads, [])
        self.assertEqual(matched, 0)
        self.assertEqual(result[0]["attribution_method"], "callibri_url_ids")

    def test_callibri_phone_match_is_labeled_separately(self) -> None:
        leads = [{
            "lead_id": "host-callibri",
            "created_at": "2026-09-17T12:00:00+03:00",
            "source": "Заявки хост",
            "campaign_id": "712849433",
            "group_id": "5773918677",
            "ad_id": "1915822986185365518",
            "advertising_id_source": "callibri_phone_time_match",
        }]
        result, matched = enrich_leads(leads, [])
        self.assertEqual(matched, 0)
        self.assertEqual(result[0]["attribution_method"], "callibri_phone_time_match")

    def test_hostess_call_summary_counts_host_source(self) -> None:
        moscow = timezone(timedelta(hours=3))
        summary = hostess_call_summary([
            {
                "lead_id": "host-no-ads",
                "created_at": "2026-09-17T10:00:00+03:00",
                "source": "Заявки хост",
                "attribution_method": "no_client_id",
            },
            {
                "lead_id": "host-callibri",
                "created_at": "2026-09-17T12:00:00+03:00",
                "source": "Заявки хост",
                "campaign_id": "712849433",
                "advertising_id_source": "callibri_phone_time_match",
                "attribution_method": "callibri_phone_time_match",
            },
            {
                "lead_id": "site",
                "created_at": "2026-09-17T13:00:00+03:00",
                "source": "САЙТ ТИЛЬДА",
            },
        ], now=datetime(2026, 9, 17, 14, 0, tzinfo=moscow))
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["with_ad_ids"], 1)
        self.assertEqual(summary["with_callibri"], 1)
        self.assertEqual(summary["today"]["total"], 2)
        self.assertEqual(summary["last_7_days"]["with_ad_ids"], 1)
        self.assertEqual(summary["latest"][0]["lead_id"], "host-callibri")

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
