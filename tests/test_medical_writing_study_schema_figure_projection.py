from datetime import datetime, timezone
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts import (
    ApprovalState,
    MedicalWritingStudySchemaPresentation,
    MedicalWritingStudySchemaSnapshot,
    MedicalWritingWorkingCopy,
    ProtocolDocument,
    ProtocolSection,
)
from services.api.app import main as app_main
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app.medical_writing_study_schema import render_study_schema_svg
from tests.test_medical_writing_study_schema import _pnh_schema


def _confirmed_plan_state():
    """Stub confirmed plan identity for figure-projection API tests."""
    plan = SimpleNamespace(
        plan_id="plan_test_schema",
        revision=1,
        state_sha256="c" * 64,
        project_id="proj_mgk10_crswnp",
        confirmation_status="author_confirmed",
    )
    return SimpleNamespace(plan=plan, available=True, source_current=True)


def _patch_plan_gate():
    return patch.object(
        app_main,
        "require_plan_for_study_schema",
        return_value=_confirmed_plan_state(),
    )


class _AuthoringService:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def study_schema_snapshot(self, project_id):
        assert project_id == "proj_mgk10_crswnp"
        return self.snapshot


class _DocumentService:
    def __init__(self, section):
        self.current_section = section

    def section(self, project_id, section_id):
        assert project_id == "proj_mgk10_crswnp"
        assert section_id == self.current_section.section_id
        return self.current_section


class _RuntimeRepository:
    def __init__(self, document, working_copy):
        self.document = document
        self.current = working_copy

    def protocol(self, project_id):
        assert project_id == "proj_mgk10_crswnp"
        return self.document

    def working_copy(self, project_id, section_id):
        assert project_id == "proj_mgk10_crswnp"
        assert section_id == self.current.section_id
        return self.current

    def save_working_copy(
        self,
        project_id,
        section_id,
        request,
        *,
        authorized_generated_blocks=None,
    ):
        assert request.expected_revision == self.current.revision
        MedicalWritingRuntimeRepository._validate_working_copy_blocks(
            self.document.sections[0].content_blocks,
            request.content_blocks,
            existing_blocks=self.current.content_blocks,
            authorized_generated_blocks=authorized_generated_blocks,
        )
        self.current = self.current.model_copy(
            update={
                "revision": self.current.revision + 1,
                "content_blocks": request.content_blocks,
                "updated_at": datetime.now(timezone.utc),
                "updated_by": request.actor,
            },
            deep=True,
        )
        return self.current


@pytest.fixture
def projection_runtime():
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    schema = _pnh_schema()
    presentation = MedicalWritingStudySchemaPresentation(
        schema_id=schema.schema_id,
        schema_revision=schema.revision,
        source_schema_sha256=schema.state_sha256,
        layout_revision=0,
        node_overrides=[],
        updated_at=now,
        updated_by="medical_manager",
    )
    svg = render_study_schema_svg(schema, presentation)
    snapshot = MedicalWritingStudySchemaSnapshot(
        project_id="proj_mgk10_crswnp",
        journey_revision=4,
        study_definition_revision=3,
        study_definition_sha256="d" * 64,
        study_schema=schema,
        presentation=presentation,
        formal_render_allowed=True,
        svg_sha256=hashlib.sha256(svg.encode("utf-8")).hexdigest(),
        svg=svg,
    )
    source_block = {
        "block_id": "heading_1_2",
        "block_type": "heading",
        "text": "1.2 试验示意图",
        "body_order": 10,
    }
    section = ProtocolSection(
        section_id="section_1_2",
        document_id="doc_schema",
        heading="试验示意图",
        section_number="1.2",
        node_kind="study_schema",
        interaction_types=["study_schema_editor"],
        content_blocks=[source_block],
    )
    document = ProtocolDocument(
        document_id="doc_schema",
        project_id="proj_mgk10_crswnp",
        protocol_id="CMS-SCHEMA",
        version="V0.1",
        sections=[section],
    )
    working_copy = MedicalWritingWorkingCopy(
        working_copy_id="working_copy_schema",
        project_id="proj_mgk10_crswnp",
        document_id="doc_schema",
        section_id="section_1_2",
        source_document_version="V0.1",
        revision=0,
        content_blocks=[source_block],
        approval_state=ApprovalState.AI_DRAFT,
        created_by="source_import",
        updated_by="source_import",
        created_at=now,
        updated_at=now,
    )
    return (
        _AuthoringService(snapshot),
        _DocumentService(section),
        _RuntimeRepository(document, working_copy),
    )


def test_projection_endpoint_inserts_then_updates_one_server_governed_figure(
    projection_runtime,
):
    authoring, document_service, repository = projection_runtime
    client = TestClient(app_main.app)
    route = (
        "/api/projects/proj_mgk10_crswnp/medical-writing/working-copies/"
        "section_1_2/study-schema-figure"
    )
    with (
        _patch_plan_gate(),
        patch.object(app_main, "medical_writing_authoring_journey_service", authoring),
        patch.object(app_main, "medical_writing_document_service", document_service),
        patch.object(app_main, "medical_writing_runtime_repository", repository),
    ):
        first = client.post(route, json=_payload(working_copy_revision=0, key="insert"))
        assert first.status_code == 200, first.text
        assert first.json()["projection_action"] == "inserted"
        figure = first.json()["figure_block"]
        assert figure["block_type"] == "figure"
        assert figure["editable"] is False
        assert figure["svg_sha256"] == authoring.snapshot.svg_sha256
        assert figure["protocol_assembly_plan"]["plan_id"] == "plan_test_schema"
        assert len(repository.current.content_blocks) == 2

        second = client.post(route, json=_payload(working_copy_revision=1, key="update"))
        assert second.status_code == 200, second.text
        assert second.json()["projection_action"] == "updated"
        assert len(repository.current.content_blocks) == 2


def test_projection_endpoint_rejects_stale_working_copy(projection_runtime):
    authoring, document_service, repository = projection_runtime
    client = TestClient(app_main.app)
    route = (
        "/api/projects/proj_mgk10_crswnp/medical-writing/working-copies/"
        "section_1_2/study-schema-figure"
    )
    with (
        _patch_plan_gate(),
        patch.object(app_main, "medical_writing_authoring_journey_service", authoring),
        patch.object(app_main, "medical_writing_document_service", document_service),
        patch.object(app_main, "medical_writing_runtime_repository", repository),
    ):
        response = client.post(route, json=_payload(working_copy_revision=2, key="stale"))
    assert response.status_code == 409
    assert "working copy changed" in response.json()["detail"]


def test_client_cannot_add_or_tamper_with_study_schema_figure(projection_runtime):
    _, _, repository = projection_runtime
    source = repository.document.sections[0].content_blocks
    forged = {
        "block_id": "mwgenerated_figure_forged",
        "block_type": "figure",
        "figure_kind": "study_schema",
    }
    with pytest.raises(ValueError, match="provenance|missing"):
        MedicalWritingRuntimeRepository._validate_working_copy_blocks(
            source,
            [*source, forged],
            existing_blocks=source,
        )


def test_client_cannot_silently_remove_server_projected_study_schema_figure(
    projection_runtime,
):
    authoring, document_service, repository = projection_runtime
    client = TestClient(app_main.app)
    route = (
        "/api/projects/proj_mgk10_crswnp/medical-writing/working-copies/"
        "section_1_2/study-schema-figure"
    )
    with (
        _patch_plan_gate(),
        patch.object(app_main, "medical_writing_authoring_journey_service", authoring),
        patch.object(app_main, "medical_writing_document_service", document_service),
        patch.object(app_main, "medical_writing_runtime_repository", repository),
    ):
        projected = client.post(
            route,
            json=_payload(working_copy_revision=0, key="insert-before-removal-test"),
        )
    assert projected.status_code == 200, projected.text

    source = repository.document.sections[0].content_blocks
    with pytest.raises(ValueError, match="preserve every server-projected"):
        MedicalWritingRuntimeRepository._validate_working_copy_blocks(
            source,
            source,
            existing_blocks=repository.current.content_blocks,
        )


def _payload(*, working_copy_revision: int, key: str):
    return {
        "expected_journey_revision": 4,
        "expected_schema_revision": 1,
        "expected_layout_revision": 0,
        "expected_working_copy_revision": working_copy_revision,
        "actor": "medical_manager_test",
        "reason": "医学经理确认将当前研究流程图插入方案第1.2节。",
        "idempotency_key": key,
    }
