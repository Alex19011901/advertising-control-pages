#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

REPORT = Path("data/direct_report.tsv")
TRACKING = Path("data/direct_tracking_diagnostic.json")
OUTPUT = Path("data/direct_source_audit.json")


def num(value: Any) -> float:
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    if text in {"", "-", "--", "—"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def main() -> int:
    with REPORT.open(encoding="utf-8") as fh:
        rows = [dict(r) for r in csv.DictReader(fh, delimiter="\t")]
    tracking = json.loads(TRACKING.read_text(encoding="utf-8")) if TRACKING.exists() else {}

    required = ["Date", "CampaignId", "AdGroupId", "AdId", "Impressions", "Clicks", "Cost"]
    fields = set(rows[0].keys()) if rows else set()
    missing_fields = [f for f in required if f not in fields]

    key_counts: dict[tuple[str, str], int] = defaultdict(int)
    campaign_ids: set[str] = set()
    campaign_names: set[str] = set()
    group_ids: set[str] = set()
    ad_ids: set[str] = set()
    dates: set[str] = set()
    totals = {"impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0}

    for row in rows:
        date = str(row.get("Date") or "")
        ad_id = str(row.get("AdId") or "")
        key_counts[(date, ad_id)] += 1
        dates.add(date)
        campaign_ids.add(str(row.get("CampaignId") or ""))
        campaign_names.add(str(row.get("CampaignName") or ""))
        group_ids.add(str(row.get("AdGroupId") or ""))
        ad_ids.add(ad_id)
        totals["impressions"] += num(row.get("Impressions"))
        totals["clicks"] += num(row.get("Clicks"))
        totals["cost"] += num(row.get("Cost"))
        totals["conversions"] += num(row.get("Conversions"))

    duplicate_date_ad_keys = [
        {"date": date, "ad_id": ad_id, "rows": count}
        for (date, ad_id), count in key_counts.items()
        if date and ad_id and count > 1
    ]

    active = []
    for item in tracking.get("campaign_counter_audit", []):
        if str(item.get("state") or "") == "ON":
            active.append({
                "campaign_id": str(item.get("campaign_id") or ""),
                "campaign_name": str(item.get("campaign_name") or ""),
                "present_in_report": str(item.get("campaign_id") or "") in campaign_ids,
            })

    active_missing = [x for x in active if not x["present_in_report"]]
    channel_signals = {
        "search_campaigns_present": any("Поиск" in name for name in campaign_names),
        "rsya_campaigns_present": any("РСЯ" in name for name in campaign_names),
        "remarketing_campaigns_present": any("Ремаркет" in name for name in campaign_names),
    }

    out = {
        "schema_version": 1,
        "source_report_type": "AD_PERFORMANCE_REPORT",
        "rows": len(rows),
        "date_min": min(dates) if dates else "",
        "date_max": max(dates) if dates else "",
        "required_fields_missing": missing_fields,
        "unique_campaigns_with_activity": len({x for x in campaign_ids if x}),
        "unique_groups_with_activity": len({x for x in group_ids if x}),
        "unique_ads_with_activity": len({x for x in ad_ids if x}),
        "duplicate_date_ad_keys": duplicate_date_ad_keys,
        "totals": {
            "impressions": int(round(totals["impressions"])),
            "clicks": int(round(totals["clicks"])),
            "cost": round(totals["cost"], 2),
            "conversions": round(totals["conversions"], 2),
        },
        "active_campaigns_total": len(active),
        "active_campaigns_with_activity_in_period": sum(1 for x in active if x["present_in_report"]),
        "active_campaigns_without_activity_in_period": active_missing,
        "channel_signals": channel_signals,
        "pass": not missing_fields and not duplicate_date_ad_keys and all(channel_signals.values()),
    }
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "pass": out["pass"],
        "rows": out["rows"],
        "unique_campaigns_with_activity": out["unique_campaigns_with_activity"],
        "duplicate_date_ad_keys": len(duplicate_date_ad_keys),
        "channel_signals": channel_signals,
        "active_campaigns_without_activity_in_period": len(active_missing),
    }, ensure_ascii=False))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
