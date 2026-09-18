from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_metrika_52597240 as mod


class FetchMetrika52597240Tests(unittest.TestCase):
    def test_constants_follow_target_scheme(self) -> None:
        self.assertEqual(mod.COUNTER_ID, 52597240)
        self.assertEqual(mod.ATTRIBUTION, "AUTOMATIC")
        self.assertIn("ym:s:automaticDirectClickOrder", mod.VISIT_FIELDS)
        self.assertIn("ym:s:automaticUTMCampaign", mod.VISIT_FIELDS)
        self.assertIn("ym:pv:visitID", mod.HIT_FIELDS)

    def test_safe_visit_rows_hash_client_id_and_keep_visit_id(self) -> None:
        rows = [{
            "ym:s:visitID": "123",
            "ym:s:clientID": "456",
            "ym:s:dateTime": "2026-09-15 12:00:00",
            "ym:s:dateTimeUTC": "2026-09-15 12:00:00",
            "ym:s:visitDuration": "45",
            "ym:s:automaticDirectClickOrder": "111",
            "ym:s:automaticDirectBannerGroup": "222",
            "ym:s:automaticDirectClickBanner": "333",
            "ym:s:automaticUTMCampaign": "Bankety_poisk",
        }]
        result = mod.safe_visit_rows(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["visit_id"], "123")
        self.assertEqual(result[0]["campaign_id"], "111")
        self.assertEqual(result[0]["group_id"], "222")
        self.assertEqual(result[0]["ad_id"], "333")
        self.assertEqual(result[0]["client_id_sha256"], hashlib.sha256(b"456").hexdigest())
        self.assertNotIn("client_id", result[0])

    def test_submit_event_requires_tilda_submitted_and_strips_query(self) -> None:
        rows = [
            {
                "ym:pv:visitID": "123",
                "ym:pv:clientID": "456",
                "ym:pv:dateTime": "2026-09-15 12:05:00",
                "ym:pv:URL": "https://example.ru/tilda/form123/submitted?phone=secret",
            },
            {
                "ym:pv:visitID": "124",
                "ym:pv:clientID": "456",
                "ym:pv:dateTime": "2026-09-15 12:06:00",
                "ym:pv:URL": "https://example.ru/ordinary-page",
            },
        ]
        result = mod.safe_submit_events(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["visit_id"], "123")
        self.assertEqual(result[0]["event_path"], "/tilda/form123/submitted")
        self.assertNotIn("secret", result[0]["event_path"])

    def test_query_uses_automatic(self) -> None:
        client = mod.MetrikaLogsClient("token")
        query = client._query(
            date1="2026-09-15",
            date2="2026-09-15",
            fields=("ym:s:visitID",),
            source="visits",
        )
        self.assertEqual(query["attribution"], "AUTOMATIC")
        self.assertEqual(query["source"], "visits")

    def test_main_without_secret_writes_missing_secret_payload(self) -> None:
        old_token = os.environ.pop("YANDEX_METRIKA_READ_TOKEN", None)
        old_fallback = os.environ.pop("YANDEX_METRIKA_REMOTE_FALLBACK_URL", None)
        old_argv = sys.argv[:]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "metrika.json"
                status = Path(tmp) / "status.json"
                sys.argv = [
                    "fetch_metrika_52597240.py",
                    "--date1",
                    "2026-09-15",
                    "--date2",
                    "2026-09-15",
                    "--output",
                    str(output),
                    "--status-output",
                    str(status),
                ]
                self.assertEqual(mod.main(), 0)
                self.assertIn("missing_secret", output.read_text(encoding="utf-8"))
                self.assertIn("missing_secret", status.read_text(encoding="utf-8"))
        finally:
            sys.argv = old_argv
            if old_token is not None:
                os.environ["YANDEX_METRIKA_READ_TOKEN"] = old_token
            if old_fallback is not None:
                os.environ["YANDEX_METRIKA_REMOTE_FALLBACK_URL"] = old_fallback

    def test_main_without_secret_can_write_remote_map_fallback_payload(self) -> None:
        old_token = os.environ.pop("YANDEX_METRIKA_READ_TOKEN", None)
        old_fallback = os.environ.get("YANDEX_METRIKA_REMOTE_FALLBACK_URL")
        old_argv = sys.argv[:]
        try:
            os.environ["YANDEX_METRIKA_REMOTE_FALLBACK_URL"] = "https://example.test/metrika_attribution_map_52597240.json"
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "metrika.json"
                status = Path(tmp) / "status.json"
                sys.argv = [
                    "fetch_metrika_52597240.py",
                    "--date1",
                    "2026-09-15",
                    "--date2",
                    "2026-09-15",
                    "--output",
                    str(output),
                    "--status-output",
                    str(status),
                ]
                self.assertEqual(mod.main(), 0)
                self.assertIn("remote_map_fallback", output.read_text(encoding="utf-8"))
                self.assertIn("remote_map_fallback", status.read_text(encoding="utf-8"))
                self.assertIn("https://example.test/metrika_attribution_map_52597240.json", status.read_text(encoding="utf-8"))
        finally:
            sys.argv = old_argv
            if old_token is not None:
                os.environ["YANDEX_METRIKA_READ_TOKEN"] = old_token
            if old_fallback is not None:
                os.environ["YANDEX_METRIKA_REMOTE_FALLBACK_URL"] = old_fallback
            else:
                os.environ.pop("YANDEX_METRIKA_REMOTE_FALLBACK_URL", None)


if __name__ == "__main__":
    unittest.main()
