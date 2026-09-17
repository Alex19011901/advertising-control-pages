#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

API_BASE = "https://api-metrika.yandex.net/management/v1"
COUNTER_ID = 52597240
ATTRIBUTION = "AUTOMATIC"
MOSCOW = timezone(timedelta(hours=3))
DEFAULT_OUTPUT = Path("data/metrika_52597240.json")
DEFAULT_STATUS = Path("data/metrika_status.json")

VISIT_FIELDS = (
    "ym:s:visitID",
    "ym:s:dateTime",
    "ym:s:dateTimeUTC",
    "ym:s:visitDuration",
    "ym:s:clientID",
    "ym:s:automaticDirectClickOrder",
    "ym:s:automaticDirectBannerGroup",
    "ym:s:automaticDirectClickBanner",
    "ym:s:automaticDirectClickOrderName",
    "ym:s:automaticClickBannerGroupName",
    "ym:s:automaticDirectClickBannerName",
    "ym:s:automaticDirectPhraseOrCond",
    "ym:s:automaticDirectPlatformType",
    "ym:s:automaticDirectPlatform",
    "ym:s:automaticUTMSource",
    "ym:s:automaticUTMMedium",
    "ym:s:automaticUTMCampaign",
    "ym:s:automaticUTMContent",
    "ym:s:automaticUTMTerm",
)

HIT_FIELDS = (
    "ym:pv:visitID",
    "ym:pv:clientID",
    "ym:pv:dateTime",
    "ym:pv:URL",
)

TERMINAL_STATUSES = {
    "canceled",
    "cleaned_by_user",
    "cleaned_automatically_as_too_old",
    "processing_failed",
}


class MetrikaLogsError(RuntimeError):
    pass


@dataclass(frozen=True)
class LogRequest:
    request_id: int
    status: str
    parts: tuple[int, ...]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def normalize_id(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text in {"", "0", "0.0"} else text


def parse_tsv(text: str) -> list[dict[str, str]]:
    if not text.strip():
        return []
    return [dict(row) for row in csv.DictReader(io.StringIO(text), delimiter="\t")]


def safe_submit_path(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parsed = urllib.parse.urlsplit(text)
        if parsed.scheme or parsed.netloc:
            return parsed.path or "/"
    except ValueError:
        pass
    return text.split("?", 1)[0].split("#", 1)[0]


def is_tilda_submit(url: str) -> bool:
    text = str(url or "").lower()
    return "tilda/form" in text and "submitted" in text


def safe_visit_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        client_id = str(row.get("ym:s:clientID") or "").strip()
        visit_id = normalize_id(row.get("ym:s:visitID"))
        if not client_id or not visit_id:
            continue
        duration_text = str(row.get("ym:s:visitDuration") or "0").strip()
        try:
            duration = max(0, int(float(duration_text or "0")))
        except ValueError:
            duration = 0
        result.append(
            {
                "client_id_sha256": sha256_text(client_id),
                "visit_id": visit_id,
                "visit_datetime": str(row.get("ym:s:dateTime") or ""),
                "visit_datetime_utc": str(row.get("ym:s:dateTimeUTC") or ""),
                "visit_duration_seconds": duration,
                "campaign_id": normalize_id(row.get("ym:s:automaticDirectClickOrder")),
                "group_id": normalize_id(row.get("ym:s:automaticDirectBannerGroup")),
                "ad_id": normalize_id(row.get("ym:s:automaticDirectClickBanner")),
                "campaign_name": str(row.get("ym:s:automaticDirectClickOrderName") or ""),
                "group_name": str(row.get("ym:s:automaticClickBannerGroupName") or ""),
                "ad_name": str(row.get("ym:s:automaticDirectClickBannerName") or ""),
                "phrase_or_condition": str(row.get("ym:s:automaticDirectPhraseOrCond") or ""),
                "platform_type": str(row.get("ym:s:automaticDirectPlatformType") or ""),
                "platform": str(row.get("ym:s:automaticDirectPlatform") or ""),
                "utm_source": str(row.get("ym:s:automaticUTMSource") or ""),
                "utm_medium": str(row.get("ym:s:automaticUTMMedium") or ""),
                "utm_campaign": str(row.get("ym:s:automaticUTMCampaign") or ""),
                "utm_content": str(row.get("ym:s:automaticUTMContent") or ""),
                "utm_term": str(row.get("ym:s:automaticUTMTerm") or ""),
            }
        )
    result.sort(key=lambda item: (item["visit_datetime"], item["visit_id"]))
    return result


def safe_submit_events(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in rows:
        url = str(row.get("ym:pv:URL") or "")
        if not is_tilda_submit(url):
            continue
        client_id = str(row.get("ym:pv:clientID") or "").strip()
        visit_id = normalize_id(row.get("ym:pv:visitID"))
        if not client_id or not visit_id:
            continue
        result.append(
            {
                "client_id_sha256": sha256_text(client_id),
                "visit_id": visit_id,
                "event_datetime": str(row.get("ym:pv:dateTime") or ""),
                "event_path": safe_submit_path(url),
            }
        )
    result.sort(key=lambda item: (item["event_datetime"], item["visit_id"]))
    return result


def _parse_request(payload: dict[str, Any]) -> LogRequest:
    item = payload.get("log_request")
    if not isinstance(item, dict):
        raise MetrikaLogsError("missing_log_request")
    parts: list[int] = []
    for part in item.get("parts") or []:
        if isinstance(part, dict) and part.get("part_number") is not None:
            parts.append(int(part["part_number"]))
    return LogRequest(
        request_id=int(item.get("request_id")),
        status=str(item.get("status") or ""),
        parts=tuple(parts),
    )


class MetrikaLogsClient:
    def __init__(self, token: str, counter_id: int = COUNTER_ID, timeout: int = 30) -> None:
        token = str(token or "").strip()
        if not token:
            raise ValueError("YANDEX_METRIKA_READ_TOKEN is required")
        self.token = token
        self.counter_id = int(counter_id)
        self.timeout = int(timeout)

    def _request(self, method: str, path: str, query: dict[str, str] | None = None) -> str:
        url = API_BASE + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(
            url,
            method=method,
            headers={"Authorization": f"OAuth {self.token}", "Accept": "application/json"},
            data=b"" if method == "POST" else None,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise MetrikaLogsError(f"http_{int(exc.code)}") from None
        except Exception as exc:
            raise MetrikaLogsError(type(exc).__name__) from None

    def _json(self, method: str, path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            payload = json.loads(self._request(method, path, query))
        except json.JSONDecodeError as exc:
            raise MetrikaLogsError("invalid_json") from exc
        if not isinstance(payload, dict):
            raise MetrikaLogsError("invalid_payload")
        return payload

    def _query(self, *, date1: str, date2: str, fields: Iterable[str], source: str) -> dict[str, str]:
        return {
            "date1": date1,
            "date2": date2,
            "fields": ",".join(fields),
            "source": source,
            "attribution": ATTRIBUTION,
        }

    def evaluate(self, *, date1: str, date2: str, fields: Iterable[str], source: str) -> None:
        self._json(
            "GET",
            f"/counter/{self.counter_id}/logrequests/evaluate",
            self._query(date1=date1, date2=date2, fields=fields, source=source),
        )

    def create(self, *, date1: str, date2: str, fields: Iterable[str], source: str) -> LogRequest:
        return _parse_request(
            self._json(
                "POST",
                f"/counter/{self.counter_id}/logrequests",
                self._query(date1=date1, date2=date2, fields=fields, source=source),
            )
        )

    def status(self, request_id: int) -> LogRequest:
        return _parse_request(
            self._json("GET", f"/counter/{self.counter_id}/logrequest/{int(request_id)}")
        )

    def download(self, request_id: int, part_number: int) -> str:
        return self._request(
            "GET",
            f"/counter/{self.counter_id}/logrequest/{int(request_id)}/part/{int(part_number)}/download",
        )

    def clean(self, request_id: int) -> None:
        self._request("POST", f"/counter/{self.counter_id}/logrequest/{int(request_id)}/clean")

    def export(
        self,
        *,
        date1: str,
        date2: str,
        fields: Iterable[str],
        source: str,
        poll_seconds: float,
        max_polls: int,
    ) -> list[dict[str, str]]:
        self.evaluate(date1=date1, date2=date2, fields=fields, source=source)
        current = self.create(date1=date1, date2=date2, fields=fields, source=source)
        for _ in range(max_polls + 1):
            if current.status == "processed":
                break
            if current.status in TERMINAL_STATUSES:
                raise MetrikaLogsError(f"log_request_{current.status}")
            if poll_seconds > 0:
                time.sleep(poll_seconds)
            current = self.status(current.request_id)
        if current.status != "processed":
            raise MetrikaLogsError("log_request_timeout")
        rows: list[dict[str, str]] = []
        for part_number in current.parts:
            rows.extend(parse_tsv(self.download(current.request_id, part_number)))
        return rows


def previous_day() -> str:
    return (datetime.now(MOSCOW).date() - timedelta(days=1)).isoformat()


def build_payload(
    client: MetrikaLogsClient,
    *,
    date1: str,
    date2: str,
    poll_seconds: float,
    max_polls: int,
) -> dict[str, Any]:
    visit_rows = client.export(
        date1=date1,
        date2=date2,
        fields=VISIT_FIELDS,
        source="visits",
        poll_seconds=poll_seconds,
        max_polls=max_polls,
    )
    hit_rows = client.export(
        date1=date1,
        date2=date2,
        fields=HIT_FIELDS,
        source="hits",
        poll_seconds=poll_seconds,
        max_polls=max_polls,
    )
    visits = safe_visit_rows(visit_rows)
    submit_events = safe_submit_events(hit_rows)
    return {
        "schema_version": 2,
        "status": "ok",
        "counter_id": client.counter_id,
        "attribution": ATTRIBUTION,
        "date1": date1,
        "date2": date2,
        "visits_total": len(visit_rows),
        "hits_total": len(hit_rows),
        "visits": visits,
        "rows": visits,
        "submit_events": submit_events,
        "rows_with_client_id": len({row["client_id_sha256"] for row in visits if row.get("client_id_sha256")}),
        "mapped_rows": sum(1 for row in visits if row.get("campaign_id") or row.get("group_id") or row.get("ad_id") or row.get("utm_campaign")),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_status(path: Path, status: str, message: str, *, output: Path, date1: str, date2: str, counter_id: int) -> None:
    write_json(path, {
        "status": status,
        "message": message,
        "counter_id": counter_id,
        "date1": date1,
        "date2": date2,
        "output": str(output),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


def empty_payload(counter_id: int, date1: str, date2: str, status: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "status": status,
        "message": message,
        "counter_id": counter_id,
        "attribution": ATTRIBUTION,
        "date1": date1,
        "date2": date2,
        "visits_total": 0,
        "hits_total": 0,
        "visits": [],
        "rows": [],
        "submit_events": [],
        "rows_with_client_id": 0,
        "mapped_rows": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Yandex Metrika Logs API export for Advertising Control")
    parser.add_argument("--counter-id", type=int, default=COUNTER_ID)
    parser.add_argument("--date1", default=previous_day())
    parser.add_argument("--date2", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--status-output", default=str(DEFAULT_STATUS))
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--max-polls", type=int, default=60)
    args = parser.parse_args()

    output = Path(args.output)
    status_output = Path(args.status_output)
    date2 = args.date2 or args.date1
    token = os.environ.get("YANDEX_METRIKA_READ_TOKEN", "").strip()
    if not token:
        message = "GitHub Actions secret YANDEX_METRIKA_READ_TOKEN is not configured."
        write_json(output, empty_payload(args.counter_id, args.date1, date2, "missing_secret", message))
        write_status(status_output, "missing_secret", message, output=output, date1=args.date1, date2=date2, counter_id=args.counter_id)
        print(f"Yandex Metrika status: missing_secret. {message}")
        return 0

    client = MetrikaLogsClient(token, counter_id=args.counter_id)
    try:
        payload = build_payload(
            client,
            date1=args.date1,
            date2=date2,
            poll_seconds=args.poll_seconds,
            max_polls=args.max_polls,
        )
    except MetrikaLogsError as exc:
        message = f"Yandex Metrika Logs API error: {exc}"
        write_json(output, empty_payload(args.counter_id, args.date1, date2, "metrika_unavailable", message))
        write_status(status_output, "metrika_unavailable", message, output=output, date1=args.date1, date2=date2, counter_id=args.counter_id)
        print(f"Yandex Metrika status: metrika_unavailable. {message}")
        return 0

    write_json(output, payload)
    write_status(status_output, "ok", "Yandex Metrika Logs export downloaded.", output=output, date1=args.date1, date2=date2, counter_id=args.counter_id)
    print(f"Metrika export written: {output}")
    print(f"Visits: {len(payload['visits'])}; submit events: {len(payload['submit_events'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
