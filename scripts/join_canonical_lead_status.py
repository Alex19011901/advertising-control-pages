from __future__ import annotations

import copy
from typing import Any


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def join_canonical_statuses(
    advertising_payload: dict[str, Any],
    status_map: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Join canonical CRM statuses onto advertising leads by exact stable lead_id only.

    No fallback matching by timestamps, contact data, names, source, or any other
    heuristic is allowed. Existing non-canonical crm_status values are not trusted:
    an unmatched row is returned with crm_status cleared.
    """
    result = copy.deepcopy(advertising_payload)
    leads = result.get("leads")
    if not isinstance(leads, list):
        leads = []
        result["leads"] = leads

    matched = 0
    unmatched = 0
    without_lead_id = 0

    for lead in leads:
        if not isinstance(lead, dict):
            unmatched += 1
            continue

        lead_id = _clean_text(lead.get("lead_id"))
        canonical = status_map.get(lead_id) if lead_id else None

        # Never expose or consume a non-canonical fallback status.
        lead["crm_status"] = ""
        lead.pop("crm_status_id", None)
        lead.pop("crm_pipeline_id", None)
        lead.pop("crm_status_source", None)

        if not lead_id:
            without_lead_id += 1
            continue

        if not isinstance(canonical, dict):
            unmatched += 1
            continue

        status_name = _clean_text(canonical.get("status_name"))
        status_id = canonical.get("status_id")
        pipeline_id = canonical.get("pipeline_id")

        if not status_name and status_id in (None, "") and pipeline_id in (None, ""):
            unmatched += 1
            continue

        lead["crm_status"] = status_name
        lead["crm_status_id"] = status_id
        lead["crm_pipeline_id"] = pipeline_id
        lead["crm_status_source"] = "crm_feedback_exact_lead_id"
        matched += 1

    stats = {
        "matched": matched,
        "unmatched": unmatched,
        "without_lead_id": without_lead_id,
        "total": len(leads),
    }
    return result, stats
