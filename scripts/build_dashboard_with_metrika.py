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
TILDA_SUBMIT_MATCH_WINDOW_SECONDS = int(os.getenv("TILDA_SUBMIT_MATCH_WINDOW_SECONDS", "900"))
MOSCOW = timezone(timedelta(hours=3))
METRIKA_EXACT_METHODS = {
    "metrika_client_session_exact",
    "metrika_client_session_utm_campaign_exact",
    "metrika_client_session_exact_utm_campaign_exact",
    "metrika_tilda_submit_visit_exact",
    "metrika_tilda_submit_visit_utm_campaign_exact",
}


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


def parse_unix_time(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(float(str(value).strip())), tz=timezone.utc).astimezone(MOSCOW)
    except (OSError, ValueError, OverflowError):
        return None


def tilda_submit_time(lead: dict[str, Any]) -> datetime | None:
    return parse_unix_time(lead.get("form_submit_timestamp"))


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


def is_hostess_lead(lead: dict[str, Any]) -> bool:
    source = str(lead.get("source") or "").casefold()
    return "заявки хост" in source


def has_metrika_client_id(lead: dict[str, Any]) -> bool:
    return bool(str(lead.get("metrika_client_id_sha256") or "").strip())


def has_ad_ids(lead: dict[str, Any]) -> bool:
    return bool(str(lead.get("ad_id") or lead.get("group_id") or lead.get("campaign_id") or "").strip())


def is_callibri_attribution(lead: dict[str, Any]) -> bool:
    return str(lead.get("advertising_id_source") or "").startswith("callibri")


def is_metrika_exact_match(lead: dict[str, Any]) -> bool:
    return str(lead.get("attribution_method") or "") in METRIKA_EXACT_METHODS


def tilda_window_summary(leads: list[dict[str, Any]], start: datetime) -> dict[str, int]:
    window = [
        lead
        for lead in leads
        if (parse_lead_time(lead.get("created_at")) or datetime.min.replace(tzinfo=MOSCOW)) >= start
    ]
    with_client_id = sum(1 for lead in window if has_metrika_client_id(lead))
    metrika_matched = sum(1 for lead in window if is_metrika_exact_match(lead))
    return {
        "total": len(window),
        "with_client_id": with_client_id,
        "without_client_id": len(window) - with_client_id,
        "metrika_matched": metrika_matched,
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
    metrika_matched = sum(1 for lead in tilda_leads if is_metrika_exact_match(lead))
    method_counts = Counter(str(lead.get("attribution_method") or "unknown") for lead in tilda_leads)
    return {
        "total": len(tilda_leads),
        "with_client_id": with_client_id,
        "without_client_id": len(tilda_leads) - with_client_id,
        "metrika_matched": metrika_matched,
        "with_client_id_unmatched": max(0, with_client_id - metrika_matched),
        "client_id_not_in_metrika_map": method_counts.get("client_id_not_in_metrika_map", 0),
        "client_id_no_session_match": method_counts.get("client_id_no_session_match", 0),
        "ambiguous_client_sessions": method_counts.get("ambiguous_client_sessions", 0),
        "method_counts": dict(sorted(method_counts.items())),
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


def hostess_window_summary(leads: list[dict[str, Any]], start: datetime) -> dict[str, int]:
    window = [
        lead
        for lead in leads
        if (parse_lead_time(lead.get("created_at")) or datetime.min.replace(tzinfo=MOSCOW)) >= start
    ]
    with_ad_ids = sum(1 for lead in window if has_ad_ids(lead))
    with_callibri = sum(1 for lead in window if is_callibri_attribution(lead))
    return {
        "total": len(window),
        "with_ad_ids": with_ad_ids,
        "without_ad_ids": len(window) - with_ad_ids,
        "with_callibri": with_callibri,
    }


def hostess_call_summary(leads: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    now_moscow = (now or datetime.now(MOSCOW)).astimezone(MOSCOW)
    today_start = now_moscow.replace(hour=0, minute=0, second=0, microsecond=0)
    last_7_days_start = now_moscow - timedelta(days=7)
    hostess_leads = [lead for lead in leads if is_hostess_lead(lead)]
    latest = sorted(
        hostess_leads,
        key=lambda lead: parse_lead_time(lead.get("created_at")) or datetime.min.replace(tzinfo=MOSCOW),
        reverse=True,
    )[:5]
    with_ad_ids = sum(1 for lead in hostess_leads if has_ad_ids(lead))
    with_callibri = sum(1 for lead in hostess_leads if is_callibri_attribution(lead))
    match_status_counts = Counter(str(lead.get("callibri_match_status") or "not_matched") for lead in hostess_leads)
    callibri_phone_not_found = match_status_counts.get("no_callibri_phone_match", 0)
    callibri_ambiguous = match_status_counts.get("ambiguous_callibri_calls", 0)
    return {
        "total": len(hostess_leads),
        "with_ad_ids": with_ad_ids,
        "without_ad_ids": len(hostess_leads) - with_ad_ids,
        "with_callibri": with_callibri,
        "callibri_phone_not_found": callibri_phone_not_found,
        "callibri_ambiguous": callibri_ambiguous,
        "match_status_counts": dict(sorted(match_status_counts.items())),
        "today": hostess_window_summary(hostess_leads, today_start),
        "last_7_days": hostess_window_summary(hostess_leads, last_7_days_start),
        "latest": [
            {
                "lead_id": str(lead.get("lead_id") or ""),
                "created_at": str(lead.get("created_at") or ""),
                "source": str(lead.get("source") or ""),
                "has_ad_ids": has_ad_ids(lead),
                "advertising_id_source": str(lead.get("advertising_id_source") or ""),
                "attribution_method": str(lead.get("attribution_method") or ""),
                "callibri_match_status": str(lead.get("callibri_match_status") or ""),
                "callibri_candidate_count": lead.get("callibri_candidate_count"),
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


def submit_events_from_map_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("submit_events")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def map_status_from_payload(source: str, url: str | None, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = rows_from_map_payload(payload)
    submit_events = submit_events_from_map_payload(payload)
    submit_events_available = isinstance(payload.get("submit_events"), list)
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
        "submit_events_total": payload.get("submit_events_total", len(submit_events)),
        "submit_events_available": submit_events_available,
    }

    try:
        counter_matches = int(counter_id) == TARGET_METRIKA_COUNTER
    except (TypeError, ValueError):
        counter_matches = False

    if counter_id is not None and not counter_matches:
        status_payload["status"] = "counter_mismatch"
        status_payload["message"] = f"Metrika export counter {counter_id} does not match target {TARGET_METRIKA_COUNTER}."
        return status_payload, {"rows": [], "submit_events": [], "submit_events_available": False}

    if attribution and attribution != TARGET_METRIKA_ATTRIBUTION:
        status_payload["status"] = "attribution_mismatch"
        status_payload["message"] = f"Metrika export attribution {attribution} does not match target {TARGET_METRIKA_ATTRIBUTION}."
        return status_payload, {"rows": [], "submit_events": [], "submit_events_available": False}

    if status != "ok":
        status_payload["message"] = payload.get("message") or "Metrika export is not ready."
        return status_payload, {"rows": [], "submit_events": [], "submit_events_available": submit_events_available}

    return status_payload, {**payload, "rows": rows, "submit_events": submit_events, "submit_events_available": submit_events_available}


def enrich_leads(
    leads: list[dict[str, Any]],
    map_rows: list[dict[str, Any]],
    utm_campaign_map: dict[str, str] | None = None,
    *,
    submit_events: list[dict[str, Any]] | None = None,
    include_diagnostics: bool = False,
) -> tuple[list[dict[str, Any]], int] | tuple[list[dict[str, Any]], int, dict[str, Any]]:
    campaign_map = utm_campaign_map or {}
    submit_events_available = submit_events is not None
    by_client: dict[str, list[dict[str, Any]]] = {}
    by_visit: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in map_rows:
        client_hash = str(row.get("client_id_sha256") or "").strip()
        if client_hash:
            by_client.setdefault(client_hash, []).append(row)
            visit_id = str(row.get("visit_id") or "").strip()
            if visit_id:
                by_visit.setdefault((client_hash, visit_id), []).append(row)
    for rows in by_client.values():
        rows.sort(key=lambda item: parse_visit_time(item.get("visit_datetime")) or datetime.min.replace(tzinfo=MOSCOW))
    submit_events = submit_events or []
    submit_by_client: dict[str, list[dict[str, Any]]] = {}
    for event in submit_events:
        client_hash = str(event.get("client_id_sha256") or "").strip()
        visit_id = str(event.get("visit_id") or "").strip()
        if client_hash and visit_id:
            submit_by_client.setdefault(client_hash, []).append(event)
    for events in submit_by_client.values():
        events.sort(key=lambda item: parse_visit_time(item.get("event_datetime")) or datetime.min.replace(tzinfo=MOSCOW))

    enriched: list[dict[str, Any]] = []
    matched = 0
    methods: Counter[str] = Counter()
    for original in leads:
        lead = copy.deepcopy(original)
        if has_ad_ids(lead):
            source = str(lead.get("advertising_id_source") or "")
            method = "callibri_phone_time_match" if source == "callibri_phone_time_match" else ("callibri_url_ids" if source.startswith("callibri") else "direct_url_ids")
            lead["attribution_method"] = method
            methods[method] += 1
            enriched.append(lead)
            continue

        client_hash = str(lead.get("metrika_client_id_sha256") or "").strip()
        lead_time = parse_lead_time(lead.get("created_at"))
        submit_time = tilda_submit_time(lead)
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

        if client_hash and is_tilda_lead(lead):
            submit_candidates = submit_by_client.get(client_hash, [])
            if submit_time:
                start = submit_time - timedelta(seconds=TILDA_SUBMIT_MATCH_WINDOW_SECONDS)
                end = submit_time + timedelta(seconds=TILDA_SUBMIT_MATCH_WINDOW_SECONDS)
                submit_candidates = [
                    event
                    for event in submit_candidates
                    if (parse_visit_time(event.get("event_datetime")) or datetime.min.replace(tzinfo=MOSCOW)) >= start
                    and (parse_visit_time(event.get("event_datetime")) or datetime.max.replace(tzinfo=MOSCOW)) <= end
                ]
            if not by_client.get(client_hash):
                lead["attribution_method"] = "client_id_not_in_metrika_map"
            elif not submit_events_available:
                lead["attribution_method"] = "tilda_submit_events_unavailable"
            elif not submit_time:
                lead["attribution_method"] = "tilda_no_submit_time"
            elif len(submit_candidates) == 0:
                lead["attribution_method"] = "tilda_no_matching_submit_event"
            elif len(submit_candidates) > 1:
                lead["attribution_method"] = "tilda_ambiguous_submit_events"
                lead["metrika_submit_candidate_count"] = len(submit_candidates)
            else:
                submit_event = submit_candidates[0]
                visit_id = str(submit_event.get("visit_id") or "").strip()
                visit_candidates = by_visit.get((client_hash, visit_id), [])
                if len(visit_candidates) == 1:
                    lead["metrika_submit_datetime"] = str(submit_event.get("event_datetime") or "")
                    lead["metrika_submit_path"] = str(submit_event.get("event_path") or "")
                    matched += apply_visit_attribution(lead, visit_candidates[0], campaign_map, "metrika_tilda_submit_visit_exact")
                elif len(visit_candidates) > 1:
                    lead["attribution_method"] = "tilda_ambiguous_submit_visits"
                    lead["metrika_submit_visit_id"] = visit_id
                    lead["metrika_submit_visit_candidate_count"] = len(visit_candidates)
                else:
                    lead["attribution_method"] = "tilda_submit_visit_not_in_metrika_map"
                    lead["metrika_submit_visit_id"] = visit_id
        elif len(exact_candidates) == 1:
            matched += apply_visit_attribution(lead, exact_candidates[0], campaign_map, "metrika_client_session_exact")
        elif len(exact_candidates) > 1:
            lead["attribution_method"] = "ambiguous_client_sessions"
        elif client_hash and not by_client.get(client_hash):
            lead["attribution_method"] = "client_id_not_in_metrika_map"
        elif client_hash and not lead_time:
            lead["attribution_method"] = "client_id_no_lead_time"
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
        "metrika_submit_events": len(submit_events),
        "metrika_submit_events_available": submit_events_available,
        "matched": matched,
        "unmatched": len(leads) - matched,
        "method_counts": dict(sorted(methods.items())),
        "bounce_session_grace_seconds": BOUNCE_SESSION_GRACE_SECONDS,
        "tilda_submit_match_window_seconds": TILDA_SUBMIT_MATCH_WINDOW_SECONDS,
        "tilda_client_id": tilda_client_id_summary(enriched),
        "hostess_calls": hostess_call_summary(enriched),
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
            if base_method == "metrika_client_session_exact":
                method = "metrika_client_session_utm_campaign_exact"
            elif base_method == "metrika_tilda_submit_visit_exact":
                method = "metrika_tilda_submit_visit_utm_campaign_exact"
            else:
                method = f"{base_method}_utm_campaign_exact"

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
        submit_events=list(map_payload.get("submit_events") or []) if map_payload.get("submit_events_available") else None,
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
