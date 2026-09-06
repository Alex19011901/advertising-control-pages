#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

SOURCE = Path("data/direct_tracking_diagnostic.json")
OUTPUT = Path("data/direct_tracking_summary.json")


def main() -> int:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    mapping: dict[str, set[str]] = defaultdict(set)
    ad_counts: dict[str, int] = defaultdict(int)
    for ad in payload.get("ads", []):
        campaign_id = str(ad.get("campaign_id") or "").strip()
        query = ((ad.get("href") or {}).get("query") or {})
        value = str(query.get("utm_campaign") or "").strip()
        if value and campaign_id:
            mapping[value].add(campaign_id)
            ad_counts[value] += 1

    exact = {
        value: {"campaign_id": next(iter(ids)), "ads": ad_counts[value]}
        for value, ids in sorted(mapping.items())
        if len(ids) == 1
    }
    ambiguous = {
        value: {"campaign_ids": sorted(ids), "ads": ad_counts[value]}
        for value, ids in sorted(mapping.items())
        if len(ids) > 1
    }
    out = {
        "schema_version": 1,
        "utm_campaign_values_total": len(mapping),
        "exact_unique_values": len(exact),
        "ambiguous_values": len(ambiguous),
        "exact_campaign_mapping": exact,
        "ambiguous_campaign_mapping": ambiguous,
    }
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("utm_campaign_values_total", "exact_unique_values", "ambiguous_values")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
