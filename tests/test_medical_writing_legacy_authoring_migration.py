from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.contracts.workbench_contracts import (
    MedicalWritingLegacyAuthoringBootstrapConfirmRequest,
    MedicalWritingLegacyAuthoringBootstrapPrepareRequest,
    MedicalWritingLegacyAuthoringBootstrapStatus,
    MedicalWritingPicosFieldApplicability,
    MedicalWritingSynopsisEvidenceSpan,
    ProtocolDocument,
    ProtocolSection,
    SynopsisImportJobStartResponse,
    SynopsisImportJobStatusResponse,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_legacy_authoring_migration import (
    MedicalWritingLegacyAuthoringMigrationService,
)
from services.api.app.medical_writing_study_consistency import (
    MedicalWritingStudyConsistencyService,
)
from tests.test_medical_writing_authoring_journey import (
    _complete_framing,
    _complete_picos,
    _review_pending_synopsis_import,
)


NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)


class _LegacyDocuments:
    def __init__(self, source_path: Path):
        self.source_path = source_path
        self.document = ProtocolDocument(
            document_id="mwdoc_legacy_001",
            project_id="proj_legacy",
            protocol_id="CMS-LEGACY-001",
            version="V1.0",
            status="source_imported_unverified",
            sections=[
                ProtocolSection(
                    section_id=f"mwsec_legacy_{index}",
                    document_id="mwdoc_legacy_001",
                    heading=heading,
                    content_blocks=[],
                )
                for index, heading in enumerate(
                    ("方案摘要", "研究背景", "研究设计", "入排标准"), start=1
                )
            ],
        )

    def document_for_revision(self, project_id: str) -> ProtocolDocument:
        assert project_id == "proj_legacy"
        return self.document.model_copy(deep=True)

    def original_protocol_path(self, project_id: str) -> Path:
        assert project_id == "proj_legacy"
        return self.source_path

    def source_mode(self, project_id: str) -> str:
        assert project_id == "proj_legacy"
        return "original_protocol_docx"


class _FakeSynopsisImports:
    def __init__(self, imported):
        self.imported = imported
        self.start_calls: list[dict] = []
        self.job_status = "review_ready"
        self.latest_job_key = ""

    def latest_job_for_source(self, project_id: str, source_sha256: str):
        assert project_id == "proj_legacy"
        assert source_sha256 == self.imported.source.content_sha256
        return self.latest_job_key

    def start_job(self, project_id: str, **kwargs):
        self.start_calls.append({"project_id": project_id, **kwargs})
        return SynopsisImportJobStartResponse(
            job_id="synjob_legacy_001",
            idempotency_key=kwargs["idempotency_key"],
            status="uploaded",
            phase="uploaded",
            content_sha256=hashlib.sha256(kwargs["payload"]).hexdigest(),
            media_type=kwargs["content_type"],
        )

    def get_job(self, project_id: str, idempotency_key: str):
        return SynopsisImportJobStatusResponse(
            job_id="synjob_legacy_001",
            status=self.job_status,
            phase=self.job_status,
            content_sha256=self.imported.source.content_sha256,
            source_filename=self.imported.source.original_filename,
            warnings=list(self.imported.source.validation_warnings),
            result_ref=(
                f"/api/projects/{project_id}/medical-writing/"
                f"authoring-journey/synopsis-import/jobs/{idempotency_key}/result"
            ),
        )

    def get_job_result(self, project_id: str, idempotency_key: str):
        assert project_id == "proj_legacy"
        assert idempotency_key == "legacy-extract-001"
        return self.imported.model_copy(deep=True)


class _ProjectMetadata:
    indication = "类风湿关节炎"
    product_name = "CMS-LEGACY-001注射液"
    study_phase = "II期"


@pytest.fixture()
def legacy_runtime(tmp_path):
    source_path = tmp_path / "CMS-LEGACY-001临床试验方案.docx"
    source_bytes = b"PK\x03\x04immutable-source-protocol"
    source_path.write_bytes(source_bytes)
    imported = _review_pending_synopsis_import()
    imported.source.original_filename = source_path.name
    imported.source.content_sha256 = hashlib.sha256(source_bytes).hexdigest()
    documents = _LegacyDocuments(source_path)
    journeys = MedicalWritingAuthoringJourneyService(
        tmp_path / "authoring_journey.sqlite3"
    )
    synopsis_imports = _FakeSynopsisImports(imported)
    service = MedicalWritingLegacyAuthoringMigrationService(
        document_service=documents,
        authoring_journey_service=journeys,
        synopsis_import_service=synopsis_imports,
        project_metadata_resolver=lambda _project_id: _ProjectMetadata(),
    )
    return SimpleNamespace(
        service=service,
        documents=documents,
        journeys=journeys,
        synopsis_imports=synopsis_imports,
        imported=imported,
        source_path=source_path,
        source_bytes=source_bytes,
    )


def _prepare_request(runtime, *, source_sha256: str | None = None):
    return MedicalWritingLegacyAuthoringBootstrapPrepareRequest(
        expected_document_id=runtime.documents.document.document_id,
        expected_source_sha256=source_sha256
        or hashlib.sha256(runtime.source_bytes).hexdigest(),
        actor="medical_manager_test",
        idempotency_key="legacy-extract-001",
    )


def _confirm_request(runtime, **updates):
    payload = {
        "expected_document_id": runtime.documents.document.document_id,
        "expected_source_sha256": hashlib.sha256(runtime.source_bytes).hexdigest(),
        "import_idempotency_key": "legacy-extract-001",
        "source_id": runtime.imported.source.source_id,
        "confirmed_source_role": "protocol",
        "framing": _complete_framing(),
        "picos": _complete_picos(),
        "synopsis_text": runtime.imported.proposed_synopsis_text,
        "actor": "medical_manager_test",
        "idempotency_key": "legacy-confirm-001",
    }
    payload.update(updates)
    return MedicalWritingLegacyAuthoringBootstrapConfirmRequest(**payload)


def test_status_keeps_legacy_source_role_as_detected_role():
    status = MedicalWritingLegacyAuthoringBootstrapStatus(
        project_id="proj_legacy",
        state="eligible",
        source_role="synopsis",
    )

    assert status.source_role == "synopsis"
    assert status.detected_source_role == "synopsis"
    assert status.confirmed_source_role is None
    assert status.source_role_overridden is False


def test_legacy_bootstrap_stays_unbound_until_medical_confirmation(legacy_runtime):
    runtime = legacy_runtime
    initial = runtime.service.status("proj_legacy")
    assert initial.state == "eligible"
    assert initial.source_read_only is True
    assert initial.document_id == runtime.documents.document.document_id
    assert initial.source_sha256 == hashlib.sha256(runtime.source_bytes).hexdigest()
    assert initial.source_role == "protocol"
    assert initial.detected_source_role == "protocol"
    assert initial.confirmed_source_role is None
    assert initial.source_role_overridden is False
    assert not runtime.journeys.has_project("proj_legacy")

    started = runtime.service.prepare("proj_legacy", _prepare_request(runtime))
    assert started.state == "extracting"
    assert started.import_idempotency_key == "legacy-extract-001"
    assert runtime.synopsis_imports.start_calls[0]["expected_indication"] == "类风湿关节炎"
    assert runtime.synopsis_imports.start_calls[0]["payload"] == runtime.source_bytes
    assert not runtime.journeys.has_project("proj_legacy")

    review = runtime.service.status(
        "proj_legacy", import_idempotency_key="legacy-extract-001"
    )
    assert review.state == "review_pending"
    assert review.candidate.source.source_id == runtime.imported.source.source_id
    assert not runtime.journeys.has_project("proj_legacy")


def test_legacy_bootstrap_recovers_latest_durable_job_without_browser_key(
    legacy_runtime,
):
    runtime = legacy_runtime
    runtime.synopsis_imports.latest_job_key = "legacy-extract-001"

    recovered = runtime.service.status("proj_legacy")

    assert recovered.state == "review_pending"
    assert recovered.import_idempotency_key == "legacy-extract-001"
    assert recovered.candidate.source.source_id == runtime.imported.source.source_id
    assert not runtime.journeys.has_project("proj_legacy")


def test_legacy_bootstrap_rejects_stale_source_without_starting_extraction(
    legacy_runtime,
):
    runtime = legacy_runtime
    with pytest.raises(ValueError, match="source.*changed|源文件.*变化"):
        runtime.service.prepare(
            "proj_legacy", _prepare_request(runtime, source_sha256="0" * 64)
        )
    assert runtime.synopsis_imports.start_calls == []
    assert not runtime.journeys.has_project("proj_legacy")


def test_legacy_bootstrap_requires_warning_acknowledgement_and_override(
    legacy_runtime,
):
    runtime = legacy_runtime
    runtime.imported.source.source_role_status = "warning"
    runtime.imported.source.validation_warnings = [
        "未识别到明确的“方案摘要/Protocol Synopsis”标题，请确认文件角色。"
    ]
    with pytest.raises(ValueError, match="warnings|警告"):
        runtime.service.confirm("proj_legacy", _confirm_request(runtime))
    assert not runtime.journeys.has_project("proj_legacy")

    with pytest.raises(ValueError, match="reason|理由"):
        runtime.service.confirm(
            "proj_legacy",
            _confirm_request(
                runtime,
                acknowledged_validation_warnings=list(
                    runtime.imported.source.validation_warnings
                ),
                validation_override_reason="确认",
            ),
        )
    assert not runtime.journeys.has_project("proj_legacy")


def test_legacy_bootstrap_rejects_incomplete_core_identity(legacy_runtime):
    runtime = legacy_runtime
    incomplete = _complete_framing()
    incomplete.protocol_id = ""

    with pytest.raises(ValueError, match="framing.protocol_id"):
        runtime.service.confirm(
            "proj_legacy",
            _confirm_request(runtime, framing=incomplete),
        )
    assert not runtime.journeys.has_project("proj_legacy")


def test_same_role_confirmation_atomically_creates_source_bound_study_definition(
    legacy_runtime,
):
    runtime = legacy_runtime
    source_before = runtime.source_path.read_bytes()
    confirmed = runtime.service.confirm("proj_legacy", _confirm_request(runtime))

    assert confirmed.state == "confirmed_ready_for_binding"
    assert confirmed.next_action == "bind_imported_document"
    assert confirmed.study_definition_id
    assert confirmed.study_definition_revision == 1
    assert len(confirmed.study_definition_sha256) == 64
    assert confirmed.source_role == "protocol"
    assert confirmed.detected_source_role == "protocol"
    assert confirmed.confirmed_source_role == "protocol"
    assert confirmed.source_role_overridden is False
    assert runtime.source_path.read_bytes() == source_before

    journey = runtime.journeys.get("proj_legacy")
    assert journey.synopsis_import.status == "confirmed"
    assert journey.study_definition.origin == "full_protocol_import"
    assert journey.study_definition.source_artifact_ids == [
        runtime.imported.source.source_id
    ]
    assert (
        journey.study_definition.field_states["framing.indication"].status
        == "confirmed"
    )
    assert (
        journey.study_definition.field_states["framing.indication"]
        .evidence[0]
        .evidence_span_id
        == "mwsynopsis_span_indication"
    )
    assert journey.framing_complete is True
    assert journey.picos_complete is True
    assert journey.status == "corpus_not_ready"

    consistency = MedicalWritingStudyConsistencyService(
        runtime.documents, runtime.journeys
    ).status("proj_legacy")
    assert consistency.status == "binding_required"

    replay = runtime.service.confirm("proj_legacy", _confirm_request(runtime))
    assert replay.model_dump(mode="json") == confirmed.model_dump(mode="json")


def test_legacy_core_confirmation_does_not_confirm_hidden_picos_fields(
    legacy_runtime,
):
    runtime = legacy_runtime
    hidden_safety_endpoint = "错误候选：仅记录死亡事件，不收集其他TEAE。"
    hidden_span_text = f"安全性终点：{hidden_safety_endpoint}"
    hidden_span = MedicalWritingSynopsisEvidenceSpan(
        span_id="mwsynopsis_span_hidden_safety",
        source_id=runtime.imported.source.source_id,
        locator="docx:paragraph:88",
        source_text=hidden_span_text,
        source_text_sha256=hashlib.sha256(
            hidden_span_text.encode("utf-8")
        ).hexdigest(),
    )
    runtime.imported.evidence_spans.append(hidden_span)
    runtime.imported.field_evidence_span_ids["picos.safety_endpoints"] = [
        hidden_span.span_id
    ]
    candidate_picos = runtime.imported.proposed_picos.model_copy(
        update={
            "design_archetype": "single_arm_early_phase",
            "safety_endpoints": [hidden_safety_endpoint],
            "estimand_strategy": "",
            "field_applicability": {
                "estimand_strategy": MedicalWritingPicosFieldApplicability(
                    status="not_applicable",
                    reason="AI候选认为该早期研究暂不设置确证性估计目标。",
                )
            },
        },
        deep=True,
    )
    runtime.imported.proposed_picos = candidate_picos

    runtime.service.confirm(
        "proj_legacy",
        _confirm_request(runtime, picos=candidate_picos),
    )

    field_states = runtime.journeys.get("proj_legacy").study_definition.field_states
    assert field_states["framing.indication"].status == "confirmed"
    assert field_states["picos.primary_endpoint"].status == "confirmed"
    assert field_states["picos.safety_endpoints"].status == "extracted_candidate"
    assert field_states["picos.safety_endpoints"].confirmed_by == ""
    assert field_states["picos.safety_endpoints"].confirmed_at is None
    assert field_states["picos.estimand_strategy"].status == "missing"
    assert field_states["picos.estimand_strategy"].confirmed_by == ""


def test_confirmation_requires_explicit_source_role(legacy_runtime):
    runtime = legacy_runtime
    with pytest.raises(ValueError, match="confirmed_source_role.*required"):
        runtime.service.confirm(
            "proj_legacy",
            _confirm_request(runtime, confirmed_source_role=None),
        )
    assert not runtime.journeys.has_project("proj_legacy")


@pytest.mark.parametrize("override_reason", ["", "确认"])
def test_source_role_override_requires_substantive_reason(
    legacy_runtime,
    override_reason,
):
    runtime = legacy_runtime
    with pytest.raises(ValueError, match="override reason|理由|10 characters"):
        runtime.service.confirm(
            "proj_legacy",
            _confirm_request(
                runtime,
                confirmed_source_role="synopsis",
                validation_override_reason="内容校验理由已充分记录但不能替代文件角色调整理由",
                source_role_override_reason=override_reason,
            ),
        )
    assert not runtime.journeys.has_project("proj_legacy")


def test_source_role_override_preserves_detection_and_uses_confirmed_origin(
    legacy_runtime,
):
    runtime = legacy_runtime
    source_before = runtime.source_path.read_bytes()
    captured: dict[str, str] = {}
    bootstrap = runtime.journeys.bootstrap_confirmed_legacy_import

    def capture_origin(project_id, imported, request, *, source_origin):
        captured["source_origin"] = source_origin
        return bootstrap(
            project_id,
            imported,
            request,
            source_origin=source_origin,
        )

    runtime.journeys.bootstrap_confirmed_legacy_import = capture_origin
    validation_reason = "医学作者复核内容校验警告后确认候选内容可继续使用"
    source_role_reason = "医学作者核对全文结构后确认该文件属于方案摘要"
    runtime.imported.source.source_role_status = "warning"
    runtime.imported.source.validation_warnings = [
        "内容校验提示需要医学作者复核后方可继续。"
    ]
    confirmed = runtime.service.confirm(
        "proj_legacy",
        _confirm_request(
            runtime,
            confirmed_source_role="synopsis",
            acknowledged_validation_warnings=list(
                runtime.imported.source.validation_warnings
            ),
            validation_override_reason=validation_reason,
            source_role_override_reason=source_role_reason,
        ),
    )

    assert captured["source_origin"] == "synopsis_import"
    assert confirmed.source_role == "protocol"
    assert confirmed.detected_source_role == "protocol"
    assert confirmed.confirmed_source_role == "synopsis"
    assert confirmed.source_role_overridden is True
    assert runtime.source_path.read_bytes() == source_before
    assert (
        runtime.journeys.get("proj_legacy").study_definition.origin
        == "imported_synopsis"
    )

    refreshed = runtime.service.status("proj_legacy")
    assert refreshed.source_role == "protocol"
    assert refreshed.detected_source_role == "protocol"
    assert refreshed.confirmed_source_role == "synopsis"
    assert refreshed.source_role_overridden is True

    with sqlite3.connect(runtime.journeys.db_path) as connection:
        detail = json.loads(
            connection.execute(
                """
                SELECT payload_json
                FROM medical_writing_authoring_journey_events
                WHERE project_id = ?
                  AND event_type = ?
                """,
                (
                    "proj_legacy",
                    "authoring_journey_legacy_bootstrap_confirmed",
                ),
            ).fetchone()[0]
        )
    assert detail["source_origin"] == "synopsis_import"
    assert detail["validation_override_reason"] == validation_reason
    assert detail["source_role_override_reason"] == source_role_reason
    assert detail["validation_override_reason"] != detail["source_role_override_reason"]


def test_source_role_override_idempotent_replay(legacy_runtime):
    runtime = legacy_runtime
    request = _confirm_request(
        runtime,
        confirmed_source_role="synopsis",
        source_role_override_reason="医学作者核对全文结构后确认该文件属于方案摘要",
    )
    confirmed = runtime.service.confirm("proj_legacy", request)
    replay = runtime.service.confirm("proj_legacy", request)

    assert replay.model_dump(mode="json") == confirmed.model_dump(mode="json")
    with sqlite3.connect(runtime.journeys.db_path) as connection:
        event_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM medical_writing_authoring_journey_events
            WHERE project_id = ?
              AND event_type = ?
            """,
            (
                "proj_legacy",
                "authoring_journey_legacy_bootstrap_confirmed",
            ),
        ).fetchone()[0]
    assert event_count == 1


def test_confirmation_fails_if_original_source_changed_after_extraction(
    legacy_runtime,
):
    runtime = legacy_runtime
    runtime.source_path.write_bytes(runtime.source_bytes + b"-changed")
    with pytest.raises(ValueError, match="source.*changed|源文件.*变化"):
        runtime.service.confirm("proj_legacy", _confirm_request(runtime))
    assert not runtime.journeys.has_project("proj_legacy")
