from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_dashboard", ROOT / "scripts" / "build_dashboard.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class AttributionTests(unittest.TestCase):
    def test_lead_match_counts_uses_ids_only(self) -> None:
        leads = [
            {"ad_id": "30", "group_id": "20", "campaign_id": "10", "has_yclid": True},
            {"ad_id": "", "group_id": "21", "campaign_id": "10", "has_yclid": False},
            {"ad_id": "", "group_id": "", "campaign_id": "11", "has_yclid": False},
            {"ad_id": "", "group_id": "", "campaign_id": "", "utm_campaign": "name-only", "has_yclid": True},
        ]
        result = module.lead_match_counts(leads)
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["with_yclid"], 2)
        self.assertEqual(result["exact_id_matches_available"], 3)
        self.assertEqual(result["unmatched"], 1)
        self.assertEqual(result["by_ad"], {"30": 1})
        self.assertEqual(result["by_group"], {"21": 1})
        self.assertEqual(result["by_campaign"], {"11": 1})

    def test_entity_breakdown_calculates_cpl_without_duplication(self) -> None:
        rows = [
            {"CampaignId": "10", "CampaignName": "Campaign", "AdGroupId": "20", "AdGroupName": "Group", "AdId": "30", "Cost": "100", "Clicks": "2", "Impressions": "20"},
            {"CampaignId": "10", "CampaignName": "Campaign", "AdGroupId": "20", "AdGroupName": "Group", "AdId": "30", "Cost": "50", "Clicks": "1", "Impressions": "10"},
        ]
        counts = {"by_campaign": {}, "by_group": {}, "by_ad": {"30": 1}}
        result = module.entity_breakdown(rows, counts)
        self.assertEqual(len(result["ads"]), 1)
        self.assertEqual(result["ads"][0]["cost"], 150.0)
        self.assertEqual(result["ads"][0]["real_leads"], 1)
        self.assertEqual(result["ads"][0]["fact_cpl"], 150.0)


if __name__ == "__main__":
    unittest.main()
