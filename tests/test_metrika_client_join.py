from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_dashboard_with_metrika import enrich_leads


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


if __name__ == "__main__":
    unittest.main()
