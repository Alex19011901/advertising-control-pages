#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import ssl
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import Request, urlopen

REPORT = Path("data/direct_report.tsv")
OUTPUT = Path("data/direct_tracking_diagnostic.json")
BASE = "https://api.direct.yandex.com/json/v5"
CLIENT_LOGIN = os.getenv("YANDEX_DIRECT_CLIENT_LOGIN", "e-20027205")
TARGET_METRIKA_COUNTER = int(os.getenv("YANDEX_METRIKA_TARGET_COUNTER", "52597240"))


def ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def post(service: str, payload: dict[str, Any], token: str) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"{BASE}/{service}",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Client-Login": CLIENT_LOGIN,
            "Accept-Language": "ru",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urlopen(req, timeout=60, context=ssl_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Direct {service} HTTP {exc.code}: {text[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Direct {service} unavailable: {exc.reason}") from exc


def campaign_ids() -> list[int]:
    if not REPORT.exists():
        return []
    ids: list[int] = []
    with REPORT.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            value = str(row.get("CampaignId") or "").strip()
            if value.isdigit() and int(value) not in ids:
                ids.append(int(value))
    return ids


def sanitize_href(href: str) -> dict[str, Any]:
    text = str(href or "")
    if not text:
        return {"host": "", "path": "", "query": {}}
    parsed = urlsplit(text)
    query: dict[str, str] = {}
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower().startswith("utm_") or key.lower() in {"yclid", "campaign", "cid", "gid", "gbid", "ad", "aid"}:
            query[key] = value[:200]
    return {"host": parsed.hostname or "", "path": parsed.path or "/", "query": query}


def counter_items(value: Any) -> list[int]:
    if isinstance(value, dict):
        value = value.get("Items")
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def campaign_counter_audit(token: str) -> list[dict[str, Any]]:
    payload = {
        "method": "get",
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["Id", "Name", "Type", "State", "Status"],
            "TextCampaignFieldNames": ["CounterIds"],
            "DynamicTextCampaignFieldNames": ["CounterIds"],
            "CpmBannerCampaignFieldNames": ["CounterIds"],
            "SmartCampaignFieldNames": ["CounterId"],
            "Page": {"Limit": 10000},
        },
    }
    response = post("campaigns", payload, token)
    campaigns = ((response.get("result") or {}).get("Campaigns") or [])
    safe: list[dict[str, Any]] = []
    for item in campaigns:
        campaign_type = str(item.get("Type") or "")
        counters: list[int] = []
        if campaign_type == "TEXT_CAMPAIGN":
            counters = counter_items((item.get("TextCampaign") or {}).get("CounterIds"))
        elif campaign_type == "DYNAMIC_TEXT_CAMPAIGN":
            counters = counter_items((item.get("DynamicTextCampaign") or {}).get("CounterIds"))
        elif campaign_type == "CPM_BANNER_CAMPAIGN":
            counters = counter_items((item.get("CpmBannerCampaign") or {}).get("CounterIds"))
        elif campaign_type == "SMART_CAMPAIGN":
            counter_id = (item.get("SmartCampaign") or {}).get("CounterId")
            try:
                counters = [int(counter_id)] if counter_id is not None else []
            except (TypeError, ValueError):
                counters = []
        safe.append({
            "campaign_id": str(item.get("Id") or ""),
            "campaign_name": str(item.get("Name") or ""),
            "type": campaign_type,
            "state": str(item.get("State") or ""),
            "status": str(item.get("Status") or ""),
            "metrika_counter_ids": counters,
            "has_target_counter": TARGET_METRIKA_COUNTER in counters,
        })
    return safe


def main() -> int:
    token = os.getenv("YANDEX_DIRECT_TOKEN", "").strip()
    if not token:
        raise SystemExit("YANDEX_DIRECT_TOKEN is required")

    campaigns = campaign_ids()
    if not campaigns:
        raise SystemExit("No campaign IDs in Direct report")

    campaign_audit = campaign_counter_audit(token)

    group_payload = {
        "method": "get",
        "params": {
            "SelectionCriteria": {"CampaignIds": campaigns},
            "FieldNames": ["Id", "Name", "CampaignId", "TrackingParams"],
            "Page": {"Limit": 10000},
        },
    }
    group_response = post("adgroups", group_payload, token)
    groups = ((group_response.get("result") or {}).get("AdGroups") or [])

    ad_payload = {
        "method": "get",
        "params": {
            "SelectionCriteria": {"CampaignIds": campaigns},
            "FieldNames": ["Id", "CampaignId", "AdGroupId", "Type"],
            "TextAdFieldNames": ["Href"],
            "Page": {"Limit": 10000},
        },
    }
    ad_response = post("ads", ad_payload, token)
    ads = ((ad_response.get("result") or {}).get("Ads") or [])

    safe_groups = []
    for item in groups:
        tracking = str(item.get("TrackingParams") or "")
        safe_groups.append({
            "campaign_id": str(item.get("CampaignId") or ""),
            "group_id": str(item.get("Id") or ""),
            "group_name": str(item.get("Name") or ""),
            "tracking_params": tracking[:500],
        })

    safe_ads = []
    for item in ads:
        href = ""
        for nested_key in ("TextAd", "TextImageAd", "TextAdBuilderAd", "CpcVideoAdBuilderAd"):
            nested = item.get(nested_key)
            if isinstance(nested, dict) and nested.get("Href"):
                href = str(nested.get("Href"))
                break
        safe_ads.append({
            "campaign_id": str(item.get("CampaignId") or ""),
            "group_id": str(item.get("AdGroupId") or ""),
            "ad_id": str(item.get("Id") or ""),
            "type": str(item.get("Type") or ""),
            "href": sanitize_href(href),
        })

    active_campaigns = [x for x in campaign_audit if x["state"] != "ARCHIVED"]
    active_with_target = [x for x in active_campaigns if x["has_target_counter"]]

    payload = {
        "schema_version": 2,
        "mode": "read_only_direct_get",
        "target_metrika_counter": TARGET_METRIKA_COUNTER,
        "campaign_ids_from_report": [str(x) for x in campaigns],
        "campaigns_total": len(campaign_audit),
        "campaigns_active_or_nonarchived": len(active_campaigns),
        "campaigns_active_with_target_counter": len(active_with_target),
        "all_active_campaigns_have_target_counter": bool(active_campaigns) and len(active_with_target) == len(active_campaigns),
        "campaign_counter_audit": campaign_audit,
        "group_count": len(safe_groups),
        "ad_count": len(safe_ads),
        "groups_with_tracking_params": sum(1 for x in safe_groups if x["tracking_params"]),
        "ads_with_utm_campaign": sum(1 for x in safe_ads if "utm_campaign" in x["href"]["query"]),
        "ads_with_dynamic_campaign_id": sum(1 for x in safe_ads if "{campaign_id}" in " ".join(x["href"]["query"].values())),
        "ads_with_dynamic_group_id": sum(1 for x in safe_ads if any(v in " ".join(x["href"]["query"].values()) for v in ("{gbid}", "{group_id}"))),
        "ads_with_dynamic_ad_id": sum(1 for x in safe_ads if "{ad_id}" in " ".join(x["href"]["query"].values())),
        "groups": safe_groups,
        "ads": safe_ads,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "target_metrika_counter": payload["target_metrika_counter"],
        "campaigns_total": payload["campaigns_total"],
        "campaigns_active_or_nonarchived": payload["campaigns_active_or_nonarchived"],
        "campaigns_active_with_target_counter": payload["campaigns_active_with_target_counter"],
        "all_active_campaigns_have_target_counter": payload["all_active_campaigns_have_target_counter"],
        "group_count": payload["group_count"],
        "ad_count": payload["ad_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
