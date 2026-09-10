from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "join_canonical_lead_status.py"
SPEC = importlib.util.spec_from_file_location("join_canonical_lead_status", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_exact_lead_id_join_overrides_noncanonical_status() -> None:
    payload = {
        "schema_version": 4,
        "leads": [
            {
                "lead_id": "lead-1",
                "crm_status": "WRONG_FALLBACK",
                "campaign_id": "123",
                "group_id": "456",
                "ad_id": "789",
            }
        ],
    }
    status_map = {
        "lead-1": {
            "status_id": 142,
            "status_name": "Успешно реализовано",
            "pipeline_id": 99,
        }
    }

    joined, stats = MODULE.join_canonical_statuses(payload, status_map)

    assert joined["leads"][0] == {
        "lead_id": "lead-1",
        "crm_status": "Успешно реализовано",
        "campaign_id": "123",
        "group_id": "456",
        "ad_id": "789",
        "crm_status_id": 142,
        "crm_pipeline_id": 99,
        "crm_status_source": "crm_feedback_exact_lead_id",
    }
    assert stats == {
        "matched": 1,
        "unmatched": 0,
        "without_lead_id": 0,
        "total": 1,
    }
    assert payload["leads"][0]["crm_status"] == "WRONG_FALLBACK"


def test_never_falls_back_when_exact_lead_id_is_missing_or_unmatched() -> None:
    payload = {
        "leads": [
            {
                "lead_id": "lead-missing",
                "crm_status": "WRONG_STATUS",
                "created_at": "2026-09-10T10:00:00+03:00",
                "source": "telegram",
            },
            {
                "lead_id": "",
                "crm_status": "ALSO_WRONG",
                "created_at": "2026-09-10T10:00:00+03:00",
                "source": "telegram",
            },
        ]
    }
    status_map = {
        "another-lead": {
            "status_id": 321,
            "status_name": "Ждуны",
            "pipeline_id": 77,
        }
    }

    joined, stats = MODULE.join_canonical_statuses(payload, status_map)

    assert joined["leads"][0]["crm_status"] == ""
    assert joined["leads"][1]["crm_status"] == ""
    assert "crm_status_source" not in joined["leads"][0]
    assert "crm_status_source" not in joined["leads"][1]
    assert stats == {
        "matched": 0,
        "unmatched": 1,
        "without_lead_id": 1,
        "total": 2,
    }
