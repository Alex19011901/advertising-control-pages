#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


DATA_DIR = Path(os.getenv("AD_CONTROL_DATA_DIR", "data"))
STATUS_PATH = DATA_DIR / "direct_status.json"
REPORT_PATH = DATA_DIR / "direct_report.tsv"

CLIENT_LOGIN = os.getenv("YANDEX_DIRECT_CLIENT_LOGIN", "e-20027205")
REPORTS_URL = os.getenv("YANDEX_DIRECT_REPORTS_URL", "https://api.direct.yandex.com/json/v501/reports")
DATE_RANGE = os.getenv("YANDEX_DIRECT_DATE_RANGE", "LAST_30_DAYS")
REPORT_TYPE = os.getenv("YANDEX_DIRECT_REPORT_TYPE", "SEARCH_QUERY_PERFORMANCE_REPORT")
INCLUDE_VAT = os.getenv("YANDEX_DIRECT_INCLUDE_VAT", "YES")
INCLUDE_DISCOUNT = os.getenv("YANDEX_DIRECT_INCLUDE_DISCOUNT", "NO")
MAX_ATTEMPTS = int(os.getenv("YANDEX_DIRECT_MAX_ATTEMPTS", "8"))
REQUEST_TIMEOUT = int(os.getenv("YANDEX_DIRECT_REQUEST_TIMEOUT", "80"))

FIELD_NAMES = [
    "Date",
    "CampaignId",
    "CampaignName",
    "AdGroupId",
    "AdGroupName",
    "AdId",
    "Query",
    "Criterion",
    "Impressions",
    "Clicks",
    "Ctr",
    "Cost",
    "AvgCpc",
    "Conversions",
    "Revenue",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_moscow() -> str:
    return datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()


def effective_date_range() -> str:
    date_from = os.getenv("YANDEX_DIRECT_DATE_FROM", "").strip()
    if not date_from:
        return DATE_RANGE
    date_to = os.getenv("YANDEX_DIRECT_DATE_TO", "").strip() or today_moscow()
    return f"{date_from}..{date_to}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_status(
    status: str,
    message: str,
    *,
    http_status: int | None = None,
    request_id: str | None = None,
    units: str | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "status": status,
        "message": message,
        "client_login": CLIENT_LOGIN,
        "updated_at": now_utc(),
        "http_status": http_status,
        "request_id": request_id,
        "units": units,
        "api_access_pending": status in {"api_access_pending", "missing_secret", "not_checked"},
        "report_type": REPORT_TYPE,
        "date_range": effective_date_range(),
    }
    if error:
        payload["error"] = error
    write_json(STATUS_PATH, payload)
    print(f"Yandex Direct status: {status}. {message}")
    if request_id:
        print(f"Yandex Direct RequestId: {request_id}")
    if units:
        print(f"Yandex Direct Units: {units}")


def clear_report() -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("", encoding="utf-8")


def ssl_context() -> ssl.SSLContext:
    cafile = Path("/etc/ssl/cert.pem")
    if cafile.exists():
        return ssl.create_default_context(cafile=str(cafile))
    return ssl.create_default_context()


def report_body() -> bytes:
    date_from = os.getenv("YANDEX_DIRECT_DATE_FROM", "").strip()
    date_to = os.getenv("YANDEX_DIRECT_DATE_TO", "").strip()
    selection: dict[str, Any] = {}
    date_range_type = DATE_RANGE
    if date_from:
        date_to = date_to or today_moscow()
        selection = {"DateFrom": date_from, "DateTo": date_to}
        date_range_type = "CUSTOM_DATE"
    payload = {
        "params": {
            "SelectionCriteria": selection,
            "FieldNames": FIELD_NAMES,
            "ReportName": f"advertising_control_{int(time.time())}",
            "ReportType": REPORT_TYPE,
            "DateRangeType": date_range_type,
            "Format": "TSV",
            "IncludeVAT": INCLUDE_VAT,
            "IncludeDiscount": INCLUDE_DISCOUNT,
        }
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def parse_error_body(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text[:700]}
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return {
            "error_code": error.get("error_code"),
            "error_string": error.get("error_string"),
            "error_detail": error.get("error_detail"),
            "request_id": error.get("request_id"),
        }
    return {"raw": text[:700]}


def is_access_pending(http_status: int, error: dict[str, Any]) -> bool:
    if http_status in {401, 403}:
        return True
    combined = " ".join(str(value or "") for value in error.values()).lower()
    markers = [
        "access",
        "permission",
        "not allowed",
        "not approved",
        "rights",
        "agreement",
        "доступ",
        "прав",
        "разреш",
        "соглаш",
        "одобр",
    ]
    return http_status == 400 and any(marker in combined for marker in markers)


def request_once(body: bytes, headers: dict[str, str]) -> tuple[int, dict[str, str], str]:
    request = Request(REPORTS_URL, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT, context=ssl_context()) as response:
            text = response.read().decode("utf-8", errors="replace")
            return response.status, dict(response.headers), text
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return exc.code, dict(exc.headers), text


def main() -> int:
    token = os.getenv("YANDEX_DIRECT_TOKEN", "").strip()
    if not token:
        clear_report()
        write_status("missing_secret", "GitHub Actions secret YANDEX_DIRECT_TOKEN is not configured.")
        return 0

    body = report_body()
    headers = {
        "Authorization": f"Bearer {token}",
        "Client-Login": CLIENT_LOGIN,
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8",
        "processingMode": "auto",
        "returnMoneyInMicros": "false",
        "skipReportHeader": "true",
        "skipReportSummary": "true",
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            status_code, response_headers, text = request_once(body, headers)
        except URLError as exc:
            clear_report()
            write_status("direct_unavailable", f"Could not connect to Yandex Direct API: {exc.reason}")
            return 0

        request_id = response_headers.get("RequestId") or response_headers.get("requestid")
        units = response_headers.get("Units") or response_headers.get("units")

        if status_code == 200:
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            REPORT_PATH.write_text(text, encoding="utf-8")
            write_status(
                "ok",
                "Yandex Direct report downloaded.",
                http_status=status_code,
                request_id=request_id,
                units=units,
            )
            return 0

        if status_code in {201, 202}:
            retry_in = int(response_headers.get("retryIn", response_headers.get("retryin", "60")))
            print(f"Yandex Direct report is not ready yet: HTTP {status_code}, attempt {attempt}/{MAX_ATTEMPTS}.")
            if attempt == MAX_ATTEMPTS:
                clear_report()
                write_status(
                    "direct_unavailable",
                    "Yandex Direct report was queued but did not finish within workflow attempts.",
                    http_status=status_code,
                    request_id=request_id,
                    units=units,
                )
                return 0
            time.sleep(max(1, min(retry_in, 120)))
            continue

        error = parse_error_body(text)
        clear_report()
        if is_access_pending(status_code, error):
            write_status(
                "api_access_pending",
                "Yandex Direct API rejected access. Full API access may still be under review.",
                http_status=status_code,
                request_id=request_id or error.get("request_id"),
                units=units,
                error=error,
            )
            return 0

        status = "request_error" if status_code == 400 else "direct_unavailable"
        write_status(
            status,
            f"Yandex Direct API returned HTTP {status_code}.",
            http_status=status_code,
            request_id=request_id or error.get("request_id"),
            units=units,
            error=error,
        )
        return 0

    clear_report()
    write_status("direct_unavailable", "Yandex Direct report did not complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
