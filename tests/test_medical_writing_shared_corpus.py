from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts import (
    MedicalWritingSharedCorpusAdmissionRequest,
    MedicalWritingSharedCorpusReviewRequest,
    ProtocolDocument,
    ProtocolSection,
)
from services.api.app import main as app_main
from services.api.app.medical_writing import MedicalWritingRevisionService
from services.api.app.medical_writing_shared_corpus import (
    MedicalWritingSharedCorpusConflictError,
    MedicalWritingSharedCorpusService,
    PHASE1_ASSET_PATH,
    PHASE1_MANIFEST_PATH,
)


def _service(tmp_path: Path) -> MedicalWritingSharedCorpusService:
    return MedicalWritingSharedCorpusService(tmp_path / "shared.sqlite3")


def _sentinel_candidate(service: MedicalWritingSharedCorpusService):
    return next(
        item
        for item in service.catalog().items
        if "sentinel" in item.corpus_function
    )


def test_phase1_asset_is_self_contained_and_all_candidates_start_unapproved(tmp_path: Path):
    service = _service(tmp_path)
    catalog = service.catalog()

    assert catalog.item_count == 18
    assert catalog.pending_review_count == 18
    assert catalog.approved_count == 0
    assert catalog.admitted_count == 0
    assert len({item.segment_id for item in catalog.items}) == 18
    assert all(item.source_text and item.translated_text for item in catalog.items)
    assert all(item.automatic_fidelity_status == "passed" for item in catalog.items)
    assert service.health_report()["status"] == "ok"


def test_candidate_requires_current_medical_review_before_admission(tmp_path: Path):
    service = _service(tmp_path)
    candidate = _sentinel_candidate(service)

    with pytest.raises(
        MedicalWritingSharedCorpusConflictError,
        match="current approved medical review",
    ):
        service.admit(
            candidate.segment_id,
            MedicalWritingSharedCorpusAdmissionRequest(
                medical_review_id="missing",
                expected_review_revision=1,
                idempotency_key="admission-before-review",
            ),
        )


def test_review_admission_and_withdrawal_are_audited_and_fail_closed(tmp_path: Path):
    service = _service(tmp_path)
    candidate = _sentinel_candidate(service)
    approved = service.review(
        candidate.segment_id,
        MedicalWritingSharedCorpusReviewRequest(
            decision="approved",
            comment="原文与译文的医学含义、数字、时序和否定关系一致。",
            expected_revision=0,
            idempotency_key="shared-review-approved-001",
        ),
    )
    admitted = service.admit(
        candidate.segment_id,
        MedicalWritingSharedCorpusAdmissionRequest(
            medical_review_id=approved.medical_review_id,
            expected_review_revision=approved.medical_review_revision,
            idempotency_key="shared-admission-001",
        ),
    )

    assert admitted.medical_review_status == "approved"
    assert admitted.admission_status == "admitted"
    phase1_results = service.search(
        "哨兵给药 安全性",
        project_phase="I期",
        project_indication="健康受试者",
        limit=10,
    )
    assert any(item["segment_id"] == admitted.segment_id for item in phase1_results)
    assert service.search(
        "哨兵给药 安全性",
        project_phase="II期",
        project_indication="阵发性睡眠性血红蛋白尿症",
    ) == []
    assert service.search(
        "哨兵给药 安全性",
        project_phase="IIb期",
        project_indication="类风湿关节炎",
    ) == []

    withdrawn = service.review(
        candidate.segment_id,
        MedicalWritingSharedCorpusReviewRequest(
            decision="returned",
            comment="复核发现适用范围说明不足，撤回后重新确认。",
            expected_revision=approved.medical_review_revision,
            idempotency_key="shared-review-withdraw-001",
        ),
    )
    assert withdrawn.medical_review_status == "returned"
    assert withdrawn.admission_status == "invalidated"
    assert service.search(
        "哨兵给药 安全性",
        project_phase="I期",
        project_indication="健康受试者",
    ) == []
    assert service.verify_audit_chain() == []


def test_stale_review_revision_and_reused_idempotency_key_are_rejected(tmp_path: Path):
    service = _service(tmp_path)
    candidate = _sentinel_candidate(service)
    request = MedicalWritingSharedCorpusReviewRequest(
        decision="approved",
        comment="原文与译文一致，可作为结构和措辞参考。",
        expected_revision=0,
        idempotency_key="shared-review-idempotent-001",
    )
    first = service.review(candidate.segment_id, request)
    replay = service.review(candidate.segment_id, request)
    assert replay.medical_review_id == first.medical_review_id

    with pytest.raises(MedicalWritingSharedCorpusConflictError, match="stale"):
        service.review(
            candidate.segment_id,
            MedicalWritingSharedCorpusReviewRequest(
                decision="returned",
                comment="使用陈旧修订号的处置必须失败。",
                expected_revision=0,
                idempotency_key="shared-review-stale-001",
            ),
        )
    with pytest.raises(MedicalWritingSharedCorpusConflictError, match="idempotency"):
        service.review(
            candidate.segment_id,
            MedicalWritingSharedCorpusReviewRequest(
                decision="returned",
                comment="同一幂等键不能换成另一项请求。",
                expected_revision=first.medical_review_revision,
                idempotency_key="shared-review-idempotent-001",
            ),
        )


def test_asset_tampering_fails_before_repository_use(tmp_path: Path):
    asset = tmp_path / "candidates.json"
    manifest = tmp_path / "candidates.manifest.json"
    asset.write_bytes(PHASE1_ASSET_PATH.read_bytes() + b" ")
    manifest.write_bytes(PHASE1_MANIFEST_PATH.read_bytes())

    with pytest.raises(ValueError, match="asset hash"):
        MedicalWritingSharedCorpusService(
            tmp_path / "shared.sqlite3",
            asset_path=asset,
            manifest_path=manifest,
        )


def test_generated_asset_contains_no_local_absolute_source_paths():
    payload = json.loads(PHASE1_ASSET_PATH.read_text(encoding="utf-8"))
    rendered = json.dumps(payload, ensure_ascii=False)

    assert "/Users/" not in rendered
    assert "source_file" not in rendered


def test_shared_corpus_api_review_admission_and_phase_gate(tmp_path: Path):
    service = _service(tmp_path)
    candidate = _sentinel_candidate(service)
    client = TestClient(app_main.app)

    with patch(
        "services.api.app.main.medical_writing_shared_corpus_service",
        service,
    ):
        catalog = client.get("/api/medical-writing/shared-corpus/phase1")
        assert catalog.status_code == 200
        assert catalog.json()["item_count"] == 18

        approved = client.post(
            f"/api/medical-writing/shared-corpus/phase1/{candidate.segment_id}/medical-review",
            json={
                "decision": "approved",
                "comment": "已逐项核对原文与监管中文的医学含义、数字、时序和否定关系。",
                "expected_revision": 0,
                "actor": "medical_manager_test",
                "idempotency_key": "api-shared-review-approved-001",
            },
        )
        assert approved.status_code == 200, approved.text
        admitted = client.post(
            f"/api/medical-writing/shared-corpus/phase1/{candidate.segment_id}/admissions",
            json={
                "medical_review_id": approved.json()["medical_review_id"],
                "expected_review_revision": approved.json()["medical_review_revision"],
                "actor": "medical_manager_test",
                "idempotency_key": "api-shared-admission-001",
            },
        )
        assert admitted.status_code == 200, admitted.text
        assert admitted.json()["admission_status"] == "admitted"

        phase1 = client.get(
            "/api/medical-writing/shared-corpus/phase1/search",
            params={
                "query": "哨兵给药 安全性",
                "project_phase": "I期",
                "project_indication": "健康受试者",
            },
        )
        assert phase1.status_code == 200
        assert any(
            item["segment_id"] == candidate.segment_id
            for item in phase1.json()["items"]
        )
        for phase in ("II期", "IIb期"):
            response = client.get(
                "/api/medical-writing/shared-corpus/phase1/search",
                params={
                    "query": "哨兵给药 安全性",
                    "project_phase": phase,
                    "project_indication": "类风湿关节炎",
                },
            )
            assert response.status_code == 200
            assert response.json()["items"] == []


def test_revision_source_selection_is_available_only_to_phase1_projects(tmp_path: Path):
    service = _service(tmp_path)
    candidate = _sentinel_candidate(service)
    approved = service.review(
        candidate.segment_id,
        MedicalWritingSharedCorpusReviewRequest(
            decision="approved",
            comment="已核对原文与译文，可作为I期方案结构和监管中文措辞参考。",
            expected_revision=0,
            idempotency_key="source-selection-review-001",
        ),
    )
    service.admit(
        candidate.segment_id,
        MedicalWritingSharedCorpusAdmissionRequest(
            medical_review_id=approved.medical_review_id,
            expected_review_revision=approved.medical_review_revision,
            idempotency_key="source-selection-admission-001",
        ),
    )

    class JourneyStub:
        phases = {
            "proj_d017_phase1": ("I期", "健康受试者"),
            "proj_pnh_phase2": ("II期", "阵发性睡眠性血红蛋白尿症"),
            "proj_ra_phase2b": ("IIb期", "类风湿关节炎"),
        }

        @classmethod
        def has_project(cls, project_id: str) -> bool:
            return project_id in cls.phases

        @classmethod
        def get(cls, project_id: str):
            phase, indication = cls.phases[project_id]
            return SimpleNamespace(
                framing=SimpleNamespace(
                    indication=indication,
                    study_phase=phase,
                )
            )

    revision = MedicalWritingRevisionService(
        repo=object(),
        ai_task_runner=object(),
        shared_corpus_service=service,
        authoring_journey_service=JourneyStub(),
    )
    section = ProtocolSection(
        section_id="section_design",
        document_id="doc",
        heading="研究设计与安全性观察",
        section_number="4",
    )

    def sources(project_id: str):
        protocol = ProtocolDocument(
            document_id="doc",
            project_id=project_id,
            protocol_id="TEST-001",
            version="V0.1",
        )
        return revision._shared_corpus_sources(
            protocol,
            section,
            "哨兵给药 安全性",
            "medical_writing_revision",
        )

    phase1_sources = sources("proj_d017_phase1")
    assert phase1_sources
    assert all(
        source.source_type == "shared_phase1_protocol_reference_corpus"
        for source in phase1_sources
    )
    assert all(source.project_id == "proj_d017_phase1" for source in phase1_sources)
    assert all(source.text_preview for source in phase1_sources)
    assert sources("proj_pnh_phase2") == []
    assert sources("proj_ra_phase2b") == []
