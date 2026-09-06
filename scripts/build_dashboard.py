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
ADVERTISING_LEADS_URL = os.getenv(
    "LEAD_CONTROL_ADVERTISING_URL",
    "https://alex19011901.github.io/lead-control-pages/advertising_leads.json",
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


def fetch_json(url: str, label: str, fallback: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    request = Request(url, headers={"User-Agent": "advertising-control-pages"})
    try:
        with urlopen(request, timeout=30, context=ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return (
            {"status": "unavailable", "message": f"{label} could not be fetched: {exc}", "url": url},
            fallback,
        )
    return ({"status": "ok", "message": f"{label} loaded.", "url": url}, payload)


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
    status, payload = fetch_json(LEAD_CONTROL_URL, "Lead Control JSON", {"ranges": {}})
    if status.get("status") == "ok":
        status["snapshot_at"] = payload.get("snapshot_at")
        status["snapshot_generated_at"] = payload.get("snapshot_generated_at")
    else:
        status["status"] = "lead_unavailable"
    return status, payload


def load_advertising_leads() -> tuple[dict[str, Any], dict[str, Any]]:
    status, payload = fetch_json(
        ADVERTISING_LEADS_URL,
        "Lead Control advertising export",
        {"schema_version": 0, "start_date": None, "lead_count": 0, "leads": []},
    )
    if status.get("status") != "ok":
        status["status"] = "lead_attribution_unavailable"
    else:
        status["start_date"] = payload.get("start_date")
        status["lead_count"] = payload.get("lead_count")
    return status, payload


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
    return {
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
        payload.update({
            "direction": direction,
            "campaign_id": campaign_id,
            "campaign": campaign,
            "group_id": group_id,
            "group": group,
            "ad_id": ad_id,
            "ad_or_query": ad_or_query,
        })
        breakdown.append(payload)
    breakdown.sort(key=lambda item: item.get("cost") or 0, reverse=True)
    return total_payload, breakdown[:500]


def lead_match_counts(leads: list[dict[str, Any]]) -> dict[str, Any]:
    by_campaign: dict[str, int] = defaultdict(int)
    by_group: dict[str, int] = defaultdict(int)
    by_ad: dict[str, int] = defaultdict(int)
    exact = 0
    unmatched = 0
    with_yclid = 0
    for lead in leads:
        if lead.get("has_yclid"):
            with_yclid += 1
        ad_id = str(lead.get("ad_id") or "").strip()
        group_id = str(lead.get("group_id") or "").strip()
        campaign_id = str(lead.get("campaign_id") or "").strip()
        if ad_id:
            by_ad[ad_id] += 1
            exact += 1
        elif group_id:
            by_group[group_id] += 1
            exact += 1
        elif campaign_id:
            by_campaign[campaign_id] += 1
            exact += 1
        else:
            unmatched += 1
    return {
        "total": len(leads),
        "with_yclid": with_yclid,
        "exact_id_matches_available": exact,
        "unmatched": unmatched,
        "by_campaign": dict(by_campaign),
        "by_group": dict(by_group),
        "by_ad": dict(by_ad),
    }


def entity_breakdown(rows: list[dict[str, str]], counts: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, dict[str, dict[str, float]]] = {
        "campaigns": defaultdict(lambda: defaultdict(float)),
        "groups": defaultdict(lambda: defaultdict(float)),
        "ads": defaultdict(lambda: defaultdict(float)),
    }
    labels: dict[str, dict[str, dict[str, str]]] = {"campaigns": {}, "groups": {}, "ads": {}}
    for row in rows:
        campaign_id = str(row.get("CampaignId") or "")
        group_id = str(row.get("AdGroupId") or "")
        ad_id = str(row.get("AdId") or "")
        if campaign_id:
            add_metrics(buckets["campaigns"][campaign_id], row)
            labels["campaigns"][campaign_id] = {"campaign": row.get("CampaignName") or ""}
        if group_id:
            add_metrics(buckets["groups"][group_id], row)
            labels["groups"][group_id] = {
                "campaign_id": campaign_id,
                "campaign": row.get("CampaignName") or "",
                "group": row.get("AdGroupName") or "",
            }
        if ad_id:
            add_metrics(buckets["ads"][ad_id], row)
            labels["ads"][ad_id] = {
                "campaign_id": campaign_id,
                "campaign": row.get("CampaignName") or "",
                "group_id": group_id,
                "group": row.get("AdGroupName") or "",
            }

    result: dict[str, list[dict[str, Any]]] = {}
    count_maps = {
        "campaigns": counts.get("by_campaign") or {},
        "groups": counts.get("by_group") or {},
        "ads": counts.get("by_ad") or {},
    }
    id_names = {"campaigns": "campaign_id", "groups": "group_id", "ads": "ad_id"}
    for kind in ("campaigns", "groups", "ads"):
        items = []
        for entity_id, metrics in buckets[kind].items():
            lead_count = int(count_maps[kind].get(entity_id, 0) or 0)
            item = finalize_metrics(metrics, lead_count)
            item[id_names[kind]] = entity_id
            item.update(labels[kind].get(entity_id) or {})
            items.append(item)
        items.sort(key=lambda item: item.get("cost") or 0, reverse=True)
        result[kind] = items
    return result


def main() -> int:
    direct_status = read_json(
        DIRECT_STATUS,
        {"status": "not_checked", "message": "Yandex Direct API has not been checked yet.", "client_login": "e-20027205", "api_access_pending": True},
    )
    lead_status, lead_payload = load_lead_control()
    attribution_status, attribution_payload = load_advertising_leads()
    ranges = lead_ranges(lead_payload)
    selected_range = ranges.get("30") or {}
    quality_leads = derive_quality_leads(selected_range)

    rows = load_direct_rows(direct_status)
    if direct_status.get("status") == "ok" and not rows:
        direct_status = {**direct_status, "status": "no_data", "message": "Yandex Direct report was loaded but returned no rows."}

    advertising_leads = attribution_payload.get("leads") or []
    counts = lead_match_counts(advertising_leads)
    exact_leads = int(counts.get("exact_id_matches_available") or 0)
    totals, breakdown = direct_summary(rows, exact_leads)
    entity = entity_breakdown(rows, counts)
    quality_cpl = safe_div(totals.get("cost"), quality_leads)

    kpi = {
        "cost": totals.get("cost"),
        "impressions": totals.get("impressions"),
        "clicks": totals.get("clicks"),
        "ctr": totals.get("ctr"),
        "cpc": totals.get("cpc"),
        "direct_conversions": totals.get("direct_conversions"),
        "real_leads": exact_leads,
        "fact_cpl": totals.get("fact_cpl"),
        "quality_leads": quality_leads,
        "quality_cpl": round(quality_cpl, 2) if quality_cpl is not None else None,
        "sales_result": None,
        "roas": totals.get("roas"),
    }

    payload = {
        "schema_version": 2,
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
            "lead_attribution": attribution_status,
        },
        "kpi": kpi,
        "direct": {"row_count": len(rows), "totals": totals, "breakdown": breakdown, "entities": entity},
        "lead_attribution": {
            "mode": "exact_ids_only",
            "historical_backfill": False,
            "start_date": attribution_payload.get("start_date"),
            "summary": counts,
            "leads": advertising_leads,
        },
        "lead_control": {"ranges": ranges, "quality_statuses": QUALITY_STATUSES},
    }
    write_json(DASHBOARD_PATH, payload)
    print(f"Dashboard JSON written to {DASHBOARD_PATH}")
    print(f"Direct status: {payload['data_sources']['direct']['status']}")
    print(f"Lead Control status: {payload['data_sources']['lead_control']['status']}")
    print(f"Lead attribution status: {payload['data_sources']['lead_attribution']['status']}")
    print(f"Exact attributed leads: {exact_leads}/{counts['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
