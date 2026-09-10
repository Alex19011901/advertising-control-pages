from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_canonical_lead_status_map.py"
SPEC = importlib.util.spec_from_file_location("build_canonical_lead_status_map", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_uses_only_crm_feedback_for_canonical_status() -> None:
    payload = {
        "leads": [
            {
                "id": "lead-1",
                "status": "SPAM",
                "crm": {
                    "found": True,
                    "status": "WRONG_CRM_STATUS",
                },
                "crm_feedback": {
                    "status_id": 142,
                    "status_name": "Успешно реализовано",
                    "pipeline_id": 99,
                },
            },
            {
                "id": "lead-2",
                "status": "OK",
                "crm": {
                    "found": True,
                    "status": "WRONG_FALLBACK",
                },
            },
        ]
    }

    assert MODULE.build_status_map(payload) == {
        "lead-1": {
            "status_id": 142,
            "status_name": "Успешно реализовано",
            "pipeline_id": 99,
        }
    }


def test_accepts_list_payload_and_skips_empty_feedback() -> None:
    payload = [
        {
            "id": "lead-3",
            "crm_feedback": {
                "status_id": "321",
                "status_name": " Ждуны ",
                "pipeline_id": "77",
            },
        },
        {
            "id": "lead-4",
            "crm_feedback": {
                "status_id": None,
                "status_name": "",
                "pipeline_id": None,
            },
        },
        {"id": "", "crm_feedback": {"status_name": "Не должно попасть"}},
    ]

    assert MODULE.build_status_map(payload) == {
        "lead-3": {
            "status_id": "321",
            "status_name": "Ждуны",
            "pipeline_id": "77",
        }
    }
