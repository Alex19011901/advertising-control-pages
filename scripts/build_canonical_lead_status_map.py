from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _has_value(value: Any) -> bool:
    return value is not None and value != ""


def extract_leads(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [lead for lead in payload if isinstance(lead, dict)]
    if isinstance(payload, dict):
        leads = payload.get("leads")
        if isinstance(leads, list):
            return [lead for lead in leads if isinstance(lead, dict)]
    return []


def build_status_map(payload: Any) -> dict[str, dict[str, Any]]:
    """Build a read-only canonical CRM-status map keyed by stable Lead Control lead.id.

    The canonical status source is lead["crm_feedback"]. This function deliberately
    does not fall back to the technical Lead Control lead["status"] field or to
    lead["crm"]["status"].
    """
    result: dict[str, dict[str, Any]] = {}

    for lead in extract_leads(payload):
        lead_id = _clean_text(lead.get("id"))
        feedback = lead.get("crm_feedback")

        if not lead_id or not isinstance(feedback, dict):
            continue

        status_id = feedback.get("status_id")
        status_name = _clean_text(feedback.get("status_name"))
        pipeline_id = feedback.get("pipeline_id")

        if not (status_name or _has_value(status_id) or _has_value(pipeline_id)):
            continue

        result[lead_id] = {
            "status_id": status_id,
            "status_name": status_name,
            "pipeline_id": pipeline_id,
        }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build an isolated canonical CRM-status map from Lead Control leads.json."
    )
    parser.add_argument("--input", required=True, help="Path to Lead Control leads.json")
    parser.add_argument("--output", required=True, help="Path for derived status map JSON")
    args = parser.parse_args()

    source = Path(args.input)
    destination = Path(args.output)
    payload = json.loads(source.read_text(encoding="utf-8"))
    status_map = build_status_map(payload)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(status_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
