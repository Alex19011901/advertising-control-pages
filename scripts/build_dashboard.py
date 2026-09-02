#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import re
import ssl
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


DATA_DIR = Path(os.getenv("AD_CONTROL_DATA_DIR", "data"))
DIRECT_REPORT = DATA_DIR / "direct_report.tsv"
DIRECT_STATUS = DATA_DIR / "direct_status.json"
DASHBOARD_PATH = DATA_DIR / "dashboard.json"
LEAD_CONTROL_URL = os.getenv(
    "LEAD_CONTROL_DASHBOARD_URL",
    "https://alex19011901.github.io/lead-control-pages/dashboard_view.json",
)
QUALITY_STATUSES = [
    item.strip()
    for item in os.getenv("LEAD_CONTROL_QUALITY_STATUSES", "").split(",")
    if item.strip()
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ssl_context() -> ssl.SSLContext:
    cafile = Path("/etc/ssl/cert.pem")
    if cafile.exists():
        return ssl.create_default_context(cafile=str(cafile))
    return ssl.create_default_context()


def parse_number(value: Any) -> float:
    if value is None:
        return 0.0
    cleaned = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if not cleaned or cleaned in {"-", "--", "—"}:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def as_int(value: float) -> int:
    return int(round(value))


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return numerator / denominator


def load_direct_rows(status: dict[str, Any]) -> list[dict[str, str]]:
    if status.get("status") != "ok" or not DIRECT_REPORT.exists():
        return []
    text = DIRECT_REPORT.read_text(encoding="utf-8").strip()
    if not text:
        return []
    reader = csv.DictReader(text.splitlines(), delimiter="\t")
    return [dict(row) for row in reader if any((value or "").strip() for value in row.values())]


def load_lead_control() -> tuple[dict[str, Any], dict[str, Any]]:
    request = Request(LEAD_CONTROL_URL, headers={"User-Agent": "advertising-control-pages"})
    try:
        with urlopen(request, timeout=30, context=ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return (
            {
                "status": "lead_unavailable",
                "message": f"Lead Control JSON could not be fetched: {exc}",
                "url": LEAD_CONTROL_URL,
            },
            {"ranges": {}},
        )
    return (
        {
            "status": "ok",
            "message": "Lead Control JSON loaded.",
            "url": LEAD_CONTROL_URL,
            "snapshot_at": payload.get("snapshot_at"),
            "snapshot_generated_at": payload.get("snapshot_generated_at"),
        },
        payload,
    )


def lead_ranges(payload: dict[str, Any]) -> dict[str, Any]:
    ranges: dict[str, Any] = {}
    for key in ["today", "yesterday", "7", "30", "all"]:
        item = (payload.get("ranges") or {}).get(key) or {}
        ranges[key] = {
            "start": item.get("start") or item.get("s"),
            "end": item.get("end") or item.get("e"),
            "real_leads": item.get("total") if item.get("total") is not None else item.get("t"),
            "status": item.get("status") or item.get("st") or {},
            "source": item.get("source") or item.get("src") or {},
            "event": item.get("event") or item.get("ev") or {},
            "channel": item.get("channel") or item.get("ch") or {},
        }
    return ranges


def derive_quality_leads(range_payload: dict[str, Any]) -> int | None:
    if not QUALITY_STATUSES:
        return None
    status_counts = range_payload.get("status") or {}
    return sum(int(status_counts.get(status, 0) or 0) for status in QUALITY_STATUSES)


def direction_from_campaign(campaign: str) -> str:
    rules_raw = os.getenv("DIRECTION_RULES_JSON", "").strip()
    if rules_raw:
        try:
            rules = json.loads(rules_raw)
        except json.JSONDecodeError:
            rules = {}
        for pattern, direction in rules.items():
            if str(pattern).lower() in campaign.lower():
                return str(direction)
    value = campaign.strip()
    if not value:
        return "Без направления"
    head = re.split(r"\s(?:->|/|\||:|—|-)\s|[|/]", value, maxsplit=1)[0].strip()
    return head or "Без направления"


def add_metrics(target: dict[str, float], row: dict[str, str]) -> None:
    target["cost"] += parse_number(row.get("Cost"))
    target["impressions"] += parse_number(row.get("Impressions"))
    target["clicks"] += parse_number(row.get("Clicks"))
    target["direct_conversions"] += parse_number(row.get("Conversions"))
    target["revenue"] += parse_number(row.get("Revenue"))


def finalize_metrics(metrics: dict[str, float], real_leads: int | None = None) -> dict[str, Any]:
    cost = metrics.get("cost", 0.0)
    impressions = metrics.get("impressions", 0.0)
    clicks = metrics.get("clicks", 0.0)
    conversions = metrics.get("direct_conversions", 0.0)
    revenue = metrics.get("revenue", 0.0)
    result = {
        "cost": round(cost, 2) if cost else None,
        "impressions": as_int(impressions) if impressions else None,
        "clicks": as_int(clicks) if clicks else None,
        "ctr": round(clicks / impressions * 100, 2) if impressions else None,
        "cpc": round(cost / clicks, 2) if clicks else None,
        "direct_conversions": round(conversions, 2) if conversions else None,
        "revenue": round(revenue, 2) if revenue else None,
        "real_leads": real_leads,
        "fact_cpl": round(cost / real_leads, 2) if cost and real_leads else None,
        "roas": round(revenue / cost, 2) if revenue and cost else None,
    }
    return result


def direct_summary(rows: list[dict[str, str]], real_leads: int | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    totals: dict[str, float] = defaultdict(float)
    grouped: dict[tuple[str, ...], dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for row in rows:
        add_metrics(totals, row)
        campaign = row.get("CampaignName") or ""
        direction = direction_from_campaign(campaign)
        group = row.get("AdGroupName") or ""
        ad_or_query = row.get("Query") or row.get("Criterion") or row.get("AdId") or ""
        key = (
            direction,
            row.get("CampaignId") or campaign,
            campaign,
            row.get("AdGroupId") or group,
            group,
            row.get("AdId") or "",
            ad_or_query,
        )
        add_metrics(grouped[key], row)

    total_payload = finalize_metrics(totals, real_leads)
    breakdown = []
    for key, metrics in grouped.items():
        direction, campaign_id, campaign, group_id, group, ad_id, ad_or_query = key
        payload = finalize_metrics(metrics)
        payload.update(
            {
                "direction": direction,
                "campaign_id": campaign_id,
                "campaign": campaign,
                "group_id": group_id,
                "group": group,
                "ad_id": ad_id,
                "ad_or_query": ad_or_query,
            }
        )
        breakdown.append(payload)
    breakdown.sort(key=lambda item: item.get("cost") or 0, reverse=True)
    return total_payload, breakdown[:500]


def main() -> int:
    direct_status = read_json(
        DIRECT_STATUS,
        {
            "status": "not_checked",
            "message": "Yandex Direct API has not been checked yet.",
            "client_login": "e-20027205",
            "api_access_pending": True,
        },
    )
    lead_status, lead_payload = load_lead_control()
    ranges = lead_ranges(lead_payload)
    selected_range = ranges.get("30") or {}
    real_leads = selected_range.get("real_leads")
    quality_leads = derive_quality_leads(selected_range)

    rows = load_direct_rows(direct_status)
    if direct_status.get("status") == "ok" and not rows:
        direct_status = {
            **direct_status,
            "status": "no_data",
            "message": "Yandex Direct report was loaded but returned no rows.",
        }

    totals, breakdown = direct_summary(rows, real_leads if isinstance(real_leads, int) else None)
    quality_cpl = safe_div(totals.get("cost"), quality_leads)
    kpi = {
        "cost": totals.get("cost"),
        "impressions": totals.get("impressions"),
        "clicks": totals.get("clicks"),
        "ctr": totals.get("ctr"),
        "cpc": totals.get("cpc"),
        "direct_conversions": totals.get("direct_conversions"),
        "real_leads": real_leads,
        "fact_cpl": totals.get("fact_cpl"),
        "quality_leads": quality_leads,
        "quality_cpl": round(quality_cpl, 2) if quality_cpl is not None else None,
        "sales_result": None,
        "roas": totals.get("roas"),
    }

    payload = {
        "schema_version": 1,
        "generated_at": now_utc(),
        "project": "advertising-control-pages",
        "client_login": direct_status.get("client_login") or "e-20027205",
        "data_sources": {
            "direct": {
                "status": direct_status.get("status"),
                "message": direct_status.get("message"),
                "http_status": direct_status.get("http_status"),
                "request_id": direct_status.get("request_id"),
                "updated_at": direct_status.get("updated_at"),
                "report_type": direct_status.get("report_type"),
                "date_range": direct_status.get("date_range"),
            },
            "lead_control": lead_status,
        },
        "kpi": kpi,
        "direct": {
            "row_count": len(rows),
            "totals": totals,
            "breakdown": breakdown,
        },
        "lead_control": {
            "ranges": ranges,
            "quality_statuses": QUALITY_STATUSES,
        },
    }
    write_json(DASHBOARD_PATH, payload)
    print(f"Dashboard JSON written to {DASHBOARD_PATH}")
    print(f"Direct status: {payload['data_sources']['direct']['status']}")
    print(f"Lead Control status: {payload['data_sources']['lead_control']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
