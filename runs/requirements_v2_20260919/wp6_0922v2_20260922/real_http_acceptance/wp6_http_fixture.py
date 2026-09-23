"""Isolated WP6 HTTP acceptance fixture over the real Protocol v3 composition.

The fixture supplies two immutable v0.10 candidate artifacts while every
study/manuscript/event write still goes through the product SQLite adapter and
the mounted FastAPI routes.  It never imports or mutates the live workbench.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI

from app.medical_writing_authoring_journey import MedicalWritingAuthoringJourneyService
from app.protocol_workflow.api.composition import (
    ProtocolWorkflowMountConfig,
    admit_project,
    mount_protocol_workflow_router,
)


HERE = Path(__file__).resolve().parent
PROJECT_ID = "proj_user_8a5a00cb014a"
RUNTIME = HERE / "isolated_runtime"
DB_PATH = HERE / "wp6_fixture_product.sqlite"
JOURNEYS = MedicalWritingAuthoringJourneyService(
    RUNTIME / "medical_writing_authoring_journey.sqlite3"
)


def _artifact(job_id: str, node_id: str, proposal: str, *, gap: bool) -> dict:
    journey = JOURNEYS.get(PROJECT_ID)
    definition = journey.study_definition
    assert definition is not None
    section_id = f"section:{node_id}"
    return {
        "schema_version": "protocol_full_draft_artifact_v10",
        "project_id": PROJECT_ID,
        "job_id": job_id,
        "study_definition": {
            "id": definition.definition_id,
            "sha256": definition.state_sha256,
        },
        "coverage": {"working_draft_ready": True},
        "target_sections": [
            {"section_id": section_id, "semantic_node_id": node_id}
        ],
        "sections": [
            {
                "section_id": section_id,
                "proposal_text": proposal,
                "evidence_bindings": [
                    {
                        "source_id": "tp-ma-07-v2",
                        "locator": "1.1 概要",
                        "claim": "研究设计概要按已确认项目事实组织。",
                    }
                ],
                "gap_items": ([
                    {
                        "gap_id": f"gap:{node_id}:follow-up",
                        "category": "source_gap",
                        "target": node_id,
                        "action": "补充本节的长期随访资料。",
                        "missing_source_classes": ["long_term_follow_up"],
                    }
                ] if gap else []),
                "decision_items": [],
            }
        ],
        "source_manifest": {
            "sources": [
                {
                    "source_id": "tp-ma-07-v2",
                    "source_version": "2.0-20260905",
                    "content_sha256": "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756",
                    "locator": "TP-MA-07 清洁版 v2.0",
                    "role": "company_sop_or_protocol_reference",
                }
            ]
        },
    }


ARTIFACTS = {
    "wp6-v10-a": _artifact(
        "wp6-v10-a",
        "v2_n_1_1",
        "本研究为一项随机、双盲、平行对照的二期临床试验，用于评估研究药物在目标人群中的有效性与安全性。",
        gap=True,
    ),
    "wp6-v10-b": _artifact(
        "wp6-v10-b",
        "v2_n_2_1",
        "现有临床证据提示目标人群仍存在未满足的治疗需求，因此需要开展本研究以验证预设的临床获益与风险。",
        gap=False,
    ),
}


def journey_provider(project_id: str):
    if project_id != PROJECT_ID:
        raise KeyError(project_id)
    return JOURNEYS.get(project_id)


def artifact_provider(project_id: str, job_id: str):
    if project_id != PROJECT_ID:
        raise KeyError(project_id)
    artifact = ARTIFACTS[job_id]
    encoded = json.dumps(
        artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return artifact, hashlib.sha256(encoded).hexdigest()


admit_project({"backend": "sqlite", "path": str(DB_PATH)}, PROJECT_ID)
app = FastAPI(title="Protocol v3 WP6 isolated acceptance")
assert mount_protocol_workflow_router(
    app,
    ProtocolWorkflowMountConfig(enabled=True, db_path=DB_PATH),
    authoring_journey_provider=journey_provider,
    full_draft_artifact_provider=artifact_provider,
)
