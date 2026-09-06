#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import build_dashboard as base

METRIKA_ATTRIBUTION_URL = os.getenv(
    "LEAD_CONTROL_METRIKA_ATTRIBUTION_URL",
    "https://raw.githubusercontent.com/Alex19011901/lead-control-pages/main/runtime-data/metrika_attribution_map.json",
)
TRACKING_SUMMARY = Path(os.getenv("DIRECT_TRACKING_SUMMARY", "data/direct_tracking_summary.json"))
MOSCOW = timezone(timedelta(hours=3))


def parse_lead_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=MOSCOW)


def parse_visit_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=MOSCOW)


def load_exact_utm_campaign_map(path: Path = TRACKING_SUMMARY) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    result: dict[str, str] = {}
    for label, item in (payload.get("exact_campaign_mapping") or {}).items():
        campaign_id = str((item or {}).get("campaign_id") or "").strip()
        if str(label).strip() and campaign_id:
            result[str(label).strip()] = campaign_id
    return result


def enrich_leads(
    leads: list[dict[str, Any]],
    map_rows: list[dict[str, Any]],
    utm_campaign_map: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    campaign_map = utm_campaign_map or {}
    by_client: dict[str, list[dict[str, Any]]] = {}
    for row in map_rows:
        client_hash = str(row.get("client_id_sha256") or "").strip()
        if client_hash:
            by_client.setdefault(client_hash, []).append(row)

    enriched: list[dict[str, Any]] = []
    matched = 0
    for original in leads:
        lead = copy.deepcopy(original)
        if str(lead.get("ad_id") or lead.get("group_id") or lead.get("campaign_id") or "").strip():
            lead["attribution_method"] = "direct_url_ids"
            enriched.append(lead)
            continue

        client_hash = str(lead.get("metrika_client_id_sha256") or "").strip()
        lead_time = parse_lead_time(lead.get("created_at"))
        candidates: list[dict[str, Any]] = []
        if client_hash and lead_time:
            for row in by_client.get(client_hash, []):
                start = parse_visit_time(row.get("visit_datetime"))
                if not start:
                    continue
                duration = int(row.get("visit_duration_seconds") or 0)
                end = start + timedelta(seconds=max(0, duration))
                if start <= lead_time <= end:
                    candidates.append(row)

        if len(candidates) == 1:
            row = candidates[0]
            campaign_id = str(row.get("campaign_id") or "").strip()
            group_id = str(row.get("group_id") or "").strip()
            ad_id = str(row.get("ad_id") or "").strip()
            utm_campaign = str(row.get("utm_campaign") or "").strip()
            method = "metrika_client_session_exact"
            if not campaign_id and utm_campaign:
                campaign_id = campaign_map.get(utm_campaign, "")
                if campaign_id:
                    method = "metrika_client_session_utm_campaign_exact"
            if campaign_id or group_id or ad_id:
                lead["campaign_id"] = campaign_id
                lead["group_id"] = group_id
                lead["ad_id"] = ad_id
                lead["attribution_method"] = method
                lead["metrika_visit_datetime"] = str(row.get("visit_datetime") or "")
                lead["metrika_utm_campaign"] = utm_campaign
                matched += 1
            else:
                lead["attribution_method"] = "client_session_unmapped_utm_campaign"
        elif len(candidates) > 1:
            lead["attribution_method"] = "ambiguous_client_sessions"
        elif client_hash:
            lead["attribution_method"] = "client_id_no_session_match"
        else:
            lead["attribution_method"] = "no_client_id"
        enriched.append(lead)
    return enriched, matched


def load_map() -> tuple[dict[str, Any], dict[str, Any]]:
    request = Request(METRIKA_ATTRIBUTION_URL, headers={"User-Agent": "advertising-control-pages"})
    try:
        with urlopen(request, timeout=30, context=ssl.create_default_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"status": "unavailable", "message": str(exc), "url": METRIKA_ATTRIBUTION_URL}, {"rows": []}
    return {"status": "ok", "url": METRIKA_ATTRIBUTION_URL, "mapped_rows": payload.get("mapped_rows")}, payload


def patched_load_advertising_leads() -> tuple[dict[str, Any], dict[str, Any]]:
    status, payload = ORIGINAL_LOAD_ADVERTISING_LEADS()
    map_status, map_payload = load_map()
    leads = list(payload.get("leads") or [])
    exact_campaign_map = load_exact_utm_campaign_map()
    enriched, matched = enrich_leads(leads, list(map_payload.get("rows") or []), exact_campaign_map)
    payload = dict(payload)
    payload["leads"] = enriched
    payload["metrika_client_session_matches"] = matched
    payload["metrika_exact_utm_campaign_mappings"] = len(exact_campaign_map)
    payload["metrika_attribution_map_status"] = map_status
    status = dict(status)
    status["metrika_attribution_map"] = map_status
    status["metrika_client_session_matches"] = matched
    status["metrika_exact_utm_campaign_mappings"] = len(exact_campaign_map)
    return status, payload


ORIGINAL_LOAD_ADVERTISING_LEADS = base.load_advertising_leads


def main() -> int:
    base.load_advertising_leads = patched_load_advertising_leads
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
