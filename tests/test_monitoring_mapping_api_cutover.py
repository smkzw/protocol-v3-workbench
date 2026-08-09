from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
from typing import Any

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "scripts"
    / "qc"
    / "monitoring_mapping_api_cutover.py"
)
SPEC = importlib.util.spec_from_file_location(
    "monitoring_mapping_api_cutover",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _options(**patch: Any):
    base = MODULE.CutoverOptions(
        base_url="http://127.0.0.1:8911",
        project_id="project-real",
        batch_id="batch-real",
        action="check",
        actor="medical_manager",
        reason="",
        expected_project_version=None,
        timeout_seconds=10.0,
    )
    return replace(base, **patch)


def _status(
    *,
    statuses: tuple[str, ...] = ("completed", "completed"),
) -> dict[str, Any]:
    completed = all(item == "completed" for item in statuses)
    return {
        "project_id": "project-real",
        "batch_id": "batch-real",
        "profile_sha256": "a" * 64,
        "input_sha256": "b" * 64,
        "field_count": 22,
        "job_count": len(statuses),
        "job_details": [
            {
                "job": {"job_id": f"job-{index}", "status": status},
                "candidates": [{"candidate_id": f"candidate-{index}"}]
                if completed
                else [],
            }
            for index, status in enumerate(statuses)
        ],
        "draft": None,
        "active_mapping": None,
    }


def test_default_check_is_read_only() -> None:
    calls: list[tuple[str, str, Any]] = []

    def requester(method, url, body, timeout):
        calls.append((method, url, body))
        return _status(statuses=("completed", "queued"))

    evidence = MODULE.run_cutover(_options(), requester=requester)

    assert evidence["result"] == "checked"
    assert evidence["status_summary"]["all_completed"] is False
    assert (
        evidence["status_summary"]["candidate_count_violation_job_ids"] == []
    )
    assert calls == [
        (
            "GET",
            "http://127.0.0.1:8911/api/projects/project-real/modules/"
            "medical-monitoring/ai/field-mapping-status?batch_id=batch-real",
            None,
        )
    ]


def test_adopt_refuses_incomplete_run_before_post() -> None:
    calls: list[str] = []

    def requester(method, url, body, timeout):
        calls.append(method)
        return _status(statuses=("completed", "running"))

    with pytest.raises(MODULE.CutoverError, match="incomplete"):
        MODULE.run_cutover(
            _options(
                action="adopt",
                reason="已完成跨域字段语义和来源核对。",
            ),
            requester=requester,
        )

    assert calls == ["GET"]


def test_confirm_stops_after_semantic_reject() -> None:
    calls: list[str] = []

    def requester(method, url, body, timeout):
        calls.append(method)
        if method == "GET":
            return _status()
        return {
            "draft_id": "draft-1",
            "version": 1,
            "status": "draft",
            "semantic_quality": {
                "status": "blocked",
                "activation_disposition": "reject",
            },
        }

    evidence = MODULE.run_cutover(
        _options(
            action="confirm",
            reason="已完成跨域字段语义和来源核对。",
        ),
        requester=requester,
    )

    assert evidence["result"] == "blocked_by_semantic_quality"
    assert calls == ["GET", "POST"]


def test_confirm_uses_public_cas_and_deterministic_idempotency() -> None:
    calls: list[tuple[str, str, Any]] = []

    def requester(method, url, body, timeout):
        calls.append((method, url, body))
        if method == "GET":
            return _status()
        if url.endswith("/field-mapping-runs/adopt"):
            return {
                "draft_id": "draft-1",
                "version": 4,
                "status": "draft",
                "semantic_quality": {
                    "status": "pass_with_warnings",
                    "activation_disposition": "activate_restricted",
                },
            }
        return {
            "mapping_revision": "monmaprev_1",
            "activation": {
                "state": {
                    "mapping_revision": "monmaprev_1",
                    "project_version": 1,
                }
            },
        }

    evidence = MODULE.run_cutover(
        _options(
            action="confirm",
            reason="已完成跨域字段语义和来源核对。",
        ),
        requester=requester,
    )

    assert evidence["result"] == "confirmed_and_activated"
    assert [item[0] for item in calls] == ["GET", "POST", "POST"]
    confirm = calls[-1][2]
    assert confirm["expected_version"] == 4
    assert confirm["expected_project_version"] == 0
    assert confirm["idempotency_key"].startswith(
        "monitoring-mapping-cutover-"
    )
