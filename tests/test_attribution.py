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

    def test_direct_summary_puts_leads_on_matching_ad_rows(self) -> None:
        rows = [
            {"CampaignId": "10", "CampaignName": "Campaign", "AdGroupId": "20", "AdGroupName": "Group", "AdId": "30", "Cost": "100", "Clicks": "2", "Impressions": "20"},
            {"CampaignId": "10", "CampaignName": "Campaign", "AdGroupId": "20", "AdGroupName": "Group", "AdId": "31", "Cost": "50", "Clicks": "1", "Impressions": "10"},
        ]
        counts = {"exact_id_matches_available": 1, "by_campaign": {}, "by_group": {}, "by_ad": {"30": 1}}
        totals, breakdown = module.direct_summary(rows, counts)
        self.assertEqual(totals["real_leads"], 1)
        by_ad = {row["ad_id"]: row for row in breakdown}
        self.assertEqual(by_ad["30"]["real_leads"], 1)
        self.assertEqual(by_ad["30"]["fact_cpl"], 100.0)
        self.assertIsNone(by_ad["31"]["real_leads"])

    def test_linked_spend_summary_keeps_only_rows_with_leads(self) -> None:
        breakdown = [
            {"campaign": "A", "cost": 100.0, "real_leads": 2, "fact_cpl": 50.0},
            {"campaign": "B", "cost": 900.0, "real_leads": None, "fact_cpl": None},
            {"campaign": "C", "cost": 50.0, "real_leads": 1, "fact_cpl": 50.0},
        ]
        result = module.linked_spend_summary(breakdown)
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["cost"], 150.0)
        self.assertEqual(result["leads"], 3)
        self.assertEqual(result["cpl"], 50.0)
        self.assertEqual([row["campaign"] for row in result["rows"]], ["A", "C"])

    def test_range_payloads_filter_direct_rows_and_leads(self) -> None:
        rows = [
            {"Date": "2026-09-18", "CampaignId": "10", "CampaignName": "Campaign", "AdGroupId": "20", "AdGroupName": "Group", "AdId": "30", "Cost": "100", "Clicks": "2", "Impressions": "20"},
            {"Date": "2026-09-19", "CampaignId": "10", "CampaignName": "Campaign", "AdGroupId": "20", "AdGroupName": "Group", "AdId": "31", "Cost": "50", "Clicks": "1", "Impressions": "10"},
        ]
        leads = [
            {"created_at": "2026-09-18T12:00:00+03:00", "ad_id": "30", "has_yclid": False},
            {"created_at": "2026-09-19T12:00:00+03:00", "ad_id": "31", "has_yclid": False},
        ]
        ranges = {
            "yesterday": {"start": "2026-09-18", "end": "2026-09-18", "real_leads": 3},
        }

        result = module.build_range_payloads(rows, leads, ranges)["yesterday"]

        self.assertEqual(result["direct"]["row_count"], 1)
        self.assertEqual(result["direct"]["totals"]["cost"], 100.0)
        self.assertEqual(result["direct"]["summary"]["exact_id_matches_available"], 1)
        self.assertEqual(result["kpi"]["real_leads"], 3)
        self.assertEqual(result["kpi"]["attributed_leads"], 1)
        self.assertEqual(result["kpi"]["fact_cpl"], 100.0)


if __name__ == "__main__":
    unittest.main()
