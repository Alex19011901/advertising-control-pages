#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
import ssl
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import build_dashboard as base

METRIKA_ATTRIBUTION_URL = os.getenv(
    "LEAD_CONTROL_METRIKA_ATTRIBUTION_URL",
    "https://raw.githubusercontent.com/Alex19011901/lead-control-pages/main/runtime-data/metrika_attribution_map_52597240.json",
)
LOCAL_METRIKA_EXPORT = Path(os.getenv("YANDEX_METRIKA_EXPORT", "data/metrika_52597240.json"))
TARGET_METRIKA_COUNTER = int(os.getenv("YANDEX_METRIKA_TARGET_COUNTER", "52597240"))
TARGET_METRIKA_ATTRIBUTION = os.getenv("YANDEX_METRIKA_TARGET_ATTRIBUTION", "AUTOMATIC").strip().upper()
TRACKING_SUMMARY = Path(os.getenv("DIRECT_TRACKING_SUMMARY", "data/direct_tracking_summary.json"))
MANUAL_UTM_CAMPAIGN_MAP = Path(os.getenv("UTM_CAMPAIGN_MAP", "data/utm_campaign_map.json"))
BOUNCE_SESSION_GRACE_SECONDS = int(os.getenv("METRIKA_BOUNCE_SESSION_GRACE_SECONDS", "1800"))
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


def load_manual_utm_campaign_map(path: Path = MANUAL_UTM_CAMPAIGN_MAP) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    raw = payload.get("campaigns") if isinstance(payload, dict) else payload
    if not isinstance(raw, dict):
        return {}
    result: dict[str, str] = {}
    for label, campaign_id in raw.items():
        label_text = str(label or "").strip()
        campaign_text = str(campaign_id or "").strip()
        if label_text and campaign_text:
            result[label_text] = campaign_text
    return result


def merge_campaign_maps(*maps: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for item in maps:
        merged.update(item)
    return merged


def is_tilda_lead(lead: dict[str, Any]) -> bool:
    source = str(lead.get("source") or "").casefold()
    return "tilda" in source or "тильда" in source


def has_metrika_client_id(lead: dict[str, Any]) -> bool:
    return bool(str(lead.get("metrika_client_id_sha256") or "").strip())


def tilda_window_summary(leads: list[dict[str, Any]], start: datetime) -> dict[str, int]:
    window = [
        lead
        for lead in leads
        if (parse_lead_time(lead.get("created_at")) or datetime.min.replace(tzinfo=MOSCOW)) >= start
    ]
    with_client_id = sum(1 for lead in window if has_metrika_client_id(lead))
    return {
        "total": len(window),
        "with_client_id": with_client_id,
        "without_client_id": len(window) - with_client_id,
    }


def tilda_client_id_summary(leads: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    now_moscow = (now or datetime.now(MOSCOW)).astimezone(MOSCOW)
    today_start = now_moscow.replace(hour=0, minute=0, second=0, microsecond=0)
    last_7_days_start = now_moscow - timedelta(days=7)
    tilda_leads = [lead for lead in leads if is_tilda_lead(lead)]
    latest = sorted(
        tilda_leads,
        key=lambda lead: parse_lead_time(lead.get("created_at")) or datetime.min.replace(tzinfo=MOSCOW),
        reverse=True,
    )[:5]
    with_client_id = sum(1 for lead in tilda_leads if has_metrika_client_id(lead))
    return {
        "total": len(tilda_leads),
        "with_client_id": with_client_id,
        "without_client_id": len(tilda_leads) - with_client_id,
        "today": tilda_window_summary(tilda_leads, today_start),
        "last_7_days": tilda_window_summary(tilda_leads, last_7_days_start),
        "latest": [
            {
                "lead_id": str(lead.get("lead_id") or ""),
                "created_at": str(lead.get("created_at") or ""),
                "source": str(lead.get("source") or ""),
                "has_metrika_client_id": has_metrika_client_id(lead),
                "attribution_method": str(lead.get("attribution_method") or ""),
            }
            for lead in latest
        ],
    }


def rows_from_map_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    visits = payload.get("visits")
    if isinstance(visits, list):
        return [row for row in visits if isinstance(row, dict)]
    return []


def map_status_from_payload(source: str, url: str | None, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = rows_from_map_payload(payload)
    counter_id = payload.get("counter_id")
    attribution = str(payload.get("attribution") or "").strip().upper()
    status = str(payload.get("status") or "ok")
    status_payload: dict[str, Any] = {
        "status": status,
        "source": source,
        "url": url,
        "counter_id": counter_id,
        "target_counter_id": TARGET_METRIKA_COUNTER,
        "attribution": attribution or None,
        "target_attribution": TARGET_METRIKA_ATTRIBUTION,
        "date1": payload.get("date1"),
        "date2": payload.get("date2"),
        "mapped_rows": len(rows),
        "rows_with_client_id": payload.get("rows_with_client_id"),
        "visits_total": payload.get("visits_total"),
        "hits_total": payload.get("hits_total"),
    }

    try:
        counter_matches = int(counter_id) == TARGET_METRIKA_COUNTER
    except (TypeError, ValueError):
        counter_matches = False

    if counter_id is not None and not counter_matches:
        status_payload["status"] = "counter_mismatch"
        status_payload["message"] = f"Metrika export counter {counter_id} does not match target {TARGET_METRIKA_COUNTER}."
        return status_payload, {"rows": []}

    if attribution and attribution != TARGET_METRIKA_ATTRIBUTION:
        status_payload["status"] = "attribution_mismatch"
        status_payload["message"] = f"Metrika export attribution {attribution} does not match target {TARGET_METRIKA_ATTRIBUTION}."
        return status_payload, {"rows": []}

    if status != "ok":
        status_payload["message"] = payload.get("message") or "Metrika export is not ready."
        return status_payload, {"rows": []}

    return status_payload, {**payload, "rows": rows}


def enrich_leads(
    leads: list[dict[str, Any]],
    map_rows: list[dict[str, Any]],
    utm_campaign_map: dict[str, str] | None = None,
    *,
    include_diagnostics: bool = False,
) -> tuple[list[dict[str, Any]], int] | tuple[list[dict[str, Any]], int, dict[str, Any]]:
    campaign_map = utm_campaign_map or {}
    by_client: dict[str, list[dict[str, Any]]] = {}
    for row in map_rows:
        client_hash = str(row.get("client_id_sha256") or "").strip()
        if client_hash:
            by_client.setdefault(client_hash, []).append(row)
    for rows in by_client.values():
        rows.sort(key=lambda item: parse_visit_time(item.get("visit_datetime")) or datetime.min.replace(tzinfo=MOSCOW))

    enriched: list[dict[str, Any]] = []
    matched = 0
    methods: Counter[str] = Counter()
    for original in leads:
        lead = copy.deepcopy(original)
        if str(lead.get("ad_id") or lead.get("group_id") or lead.get("campaign_id") or "").strip():
            lead["attribution_method"] = "direct_url_ids"
            methods["direct_url_ids"] += 1
            enriched.append(lead)
            continue

        client_hash = str(lead.get("metrika_client_id_sha256") or "").strip()
        lead_time = parse_lead_time(lead.get("created_at"))
        exact_candidates: list[dict[str, Any]] = []
        if client_hash and lead_time:
            for row in by_client.get(client_hash, []):
                start = parse_visit_time(row.get("visit_datetime"))
                if not start:
                    continue
                duration = int(row.get("visit_duration_seconds") or 0)
                end = start + timedelta(seconds=max(BOUNCE_SESSION_GRACE_SECONDS, duration))
                if start <= lead_time <= end:
                    exact_candidates.append(row)

        if len(exact_candidates) == 1:
            matched += apply_visit_attribution(lead, exact_candidates[0], campaign_map, "metrika_client_session_exact")
        elif len(exact_candidates) > 1:
            lead["attribution_method"] = "ambiguous_client_sessions"
        elif client_hash:
            lead["attribution_method"] = "client_id_no_session_match"
        else:
            lead["attribution_method"] = "no_client_id"
        methods[str(lead.get("attribution_method") or "unknown")] += 1
        enriched.append(lead)

    diagnostics = {
        "leads_total": len(leads),
        "leads_with_metrika_client_id": sum(1 for lead in leads if str(lead.get("metrika_client_id_sha256") or "").strip()),
        "metrika_clients_in_map": len(by_client),
        "metrika_rows": len(map_rows),
        "matched": matched,
        "unmatched": len(leads) - matched,
        "method_counts": dict(sorted(methods.items())),
        "bounce_session_grace_seconds": BOUNCE_SESSION_GRACE_SECONDS,
        "tilda_client_id": tilda_client_id_summary(enriched),
    }
    if include_diagnostics:
        return enriched, matched, diagnostics
    return enriched, matched


def apply_visit_attribution(
    lead: dict[str, Any],
    row: dict[str, Any],
    campaign_map: dict[str, str],
    base_method: str,
) -> int:
    campaign_id = str(row.get("campaign_id") or "").strip()
    group_id = str(row.get("group_id") or "").strip()
    ad_id = str(row.get("ad_id") or "").strip()
    utm_campaign = str(row.get("utm_campaign") or "").strip()
    method = base_method
    if not campaign_id and utm_campaign:
        campaign_id = campaign_map.get(utm_campaign, "")
        if campaign_id:
            method = (
                "metrika_client_session_utm_campaign_exact"
                if base_method == "metrika_client_session_exact"
                else f"{base_method}_utm_campaign_exact"
            )

    lead["metrika_visit_datetime"] = str(row.get("visit_datetime") or "")
    lead["metrika_utm_source"] = str(row.get("utm_source") or "")
    lead["metrika_utm_medium"] = str(row.get("utm_medium") or "")
    lead["metrika_utm_campaign"] = utm_campaign
    lead["metrika_phrase_or_condition"] = str(row.get("phrase_or_condition") or "")
    lead["metrika_campaign_name"] = str(row.get("campaign_name") or "")
    lead["metrika_group_name"] = str(row.get("group_name") or "")
    lead["metrika_ad_name"] = str(row.get("ad_name") or "")

    if campaign_id or group_id or ad_id:
        lead["campaign_id"] = campaign_id
        lead["group_id"] = group_id
        lead["ad_id"] = ad_id
        lead["attribution_method"] = method
        return 1

    lead["attribution_method"] = "client_session_unmapped_utm_campaign" if utm_campaign else "client_session_without_direct_ids"
    return 0


def load_map() -> tuple[dict[str, Any], dict[str, Any]]:
    if LOCAL_METRIKA_EXPORT.exists():
        try:
            payload = json.loads(LOCAL_METRIKA_EXPORT.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            local_status = {"status": "invalid_json", "message": str(exc), "source": "local_file", "url": str(LOCAL_METRIKA_EXPORT)}
            remote_status, remote_payload = load_remote_map()
            return (remote_status, remote_payload) if remote_status.get("status") == "ok" else (local_status, {"rows": []})
        local_status, local_payload = map_status_from_payload("local_file", str(LOCAL_METRIKA_EXPORT), payload)
        if local_status.get("status") == "ok":
            return local_status, local_payload
        remote_status, remote_payload = load_remote_map()
        return (remote_status, remote_payload) if remote_status.get("status") == "ok" else (local_status, local_payload)

    return load_remote_map()


def load_remote_map() -> tuple[dict[str, Any], dict[str, Any]]:
    request = Request(METRIKA_ATTRIBUTION_URL, headers={"User-Agent": "advertising-control-pages"})
    try:
        with urlopen(request, timeout=30, context=ssl.create_default_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(getattr(exc, "reason", exc)):
            return {"status": "unavailable", "message": str(exc), "url": METRIKA_ATTRIBUTION_URL}, {"rows": []}
        try:
            with urlopen(request, timeout=30, context=ssl._create_unverified_context()) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (URLError, TimeoutError, json.JSONDecodeError) as fallback_exc:
            return {"status": "unavailable", "message": str(fallback_exc), "url": METRIKA_ATTRIBUTION_URL}, {"rows": []}
    except (TimeoutError, json.JSONDecodeError) as exc:
        return {"status": "unavailable", "message": str(exc), "url": METRIKA_ATTRIBUTION_URL}, {"rows": []}
    return map_status_from_payload("remote_legacy", METRIKA_ATTRIBUTION_URL, payload)


def patched_load_advertising_leads() -> tuple[dict[str, Any], dict[str, Any]]:
    status, payload = ORIGINAL_LOAD_ADVERTISING_LEADS()
    map_status, map_payload = load_map()
    leads = list(payload.get("leads") or [])
    exact_campaign_map = merge_campaign_maps(load_exact_utm_campaign_map(), load_manual_utm_campaign_map())
    enriched, matched, diagnostics = enrich_leads(
        leads,
        list(map_payload.get("rows") or []),
        exact_campaign_map,
        include_diagnostics=True,
    )
    payload = dict(payload)
    payload["leads"] = enriched
    payload["metrika_client_session_matches"] = matched
    payload["metrika_exact_utm_campaign_mappings"] = len(exact_campaign_map)
    payload["metrika_attribution_map_status"] = map_status
    payload["metrika_attribution_diagnostics"] = diagnostics
    status = dict(status)
    status["metrika_attribution_map"] = map_status
    status["metrika_client_session_matches"] = matched
    status["metrika_exact_utm_campaign_mappings"] = len(exact_campaign_map)
    status["metrika_attribution_diagnostics"] = diagnostics
    return status, payload


ORIGINAL_LOAD_ADVERTISING_LEADS = base.load_advertising_leads


def main() -> int:
    base.load_advertising_leads = patched_load_advertising_leads
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
