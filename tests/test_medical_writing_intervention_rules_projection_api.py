from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts import (
    ApprovalState,
    MedicalWritingWorkingCopy,
    ProtocolDocument,
    ProtocolSection,
)
from services.api.app import main as app_main
from services.api.app.medical_writing_intervention_rules_projection import (
    intervention_rules_sha256,
)
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app.sqlite_runtime_store import RuntimeStoreError
from tests.test_medical_writing_intervention_rules_projection import (
    _d001_like_rules,
    _pnh_like_rules,
)


class _AuthoringService:
    def __init__(self, rules, revision=4):
        self.state = SimpleNamespace(
            journey_id="journey_intervention_rules",
            revision=revision,
            picos=SimpleNamespace(intervention_rules=rules),
        )

    def get(self, project_id):
        assert project_id == "proj_mgk10_crswnp"
        return self.state


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
        self.replays = {}

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
        replay = self.replays.get(request.idempotency_key)
        if replay is not None:
            return replay
        if request.expected_revision != self.current.revision:
            raise RuntimeStoreError(
                "working copy revision conflict: "
                f"expected {request.expected_revision}, current {self.current.revision}"
            )
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
        self.replays[request.idempotency_key] = self.current
        return self.current


def _runtime(section_number, rules):
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    interaction_by_section = {
        "6.4": "dose_modification_rule_builder",
        "6.9": "non_investigational_intervention_builder",
        "6.10": "concomitant_therapy_rule_builder",
    }
    source_block = {
        "block_id": f"heading_{section_number.replace('.', '_')}",
        "block_type": "heading",
        "text": f"{section_number} 测试章节",
        "body_order": 10,
    }
    section = ProtocolSection(
        section_id=f"section_{section_number.replace('.', '_')}",
        document_id="doc_intervention_rules",
        heading="测试章节",
        section_number=section_number,
        interaction_types=[interaction_by_section.get(section_number, "rich_text")],
        content_blocks=[source_block],
    )
    document = ProtocolDocument(
        document_id="doc_intervention_rules",
        project_id="proj_mgk10_crswnp",
        protocol_id="CMS-IR",
        version="V0.1",
        sections=[section],
    )
    working_copy = MedicalWritingWorkingCopy(
        working_copy_id=f"wc_{section.section_id}",
        project_id="proj_mgk10_crswnp",
        document_id=document.document_id,
        section_id=section.section_id,
        source_document_version=document.version,
        revision=0,
        content_blocks=[source_block],
        approval_state=ApprovalState.AI_DRAFT,
        created_by="source_import",
        updated_by="source_import",
        created_at=now,
        updated_at=now,
    )
    return (
        _AuthoringService(rules),
        _DocumentService(section),
        _RuntimeRepository(document, working_copy),
    )


def _payload(rules, *, working_revision=0, key="project", overwrite=False):
    return {
        "expected_journey_revision": 4,
        "expected_intervention_rules_sha256": intervention_rules_sha256(rules),
        "expected_working_copy_revision": working_revision,
        "overwrite_medical_edits": overwrite,
        "actor": "medical_manager_test",
        "reason": "医学经理确认将结构化干预规则应用到当前方案章节。",
        "idempotency_key": key,
    }


def _post(runtime, payload):
    authoring, document_service, repository = runtime
    section_id = document_service.current_section.section_id
    route = (
        "/api/projects/proj_mgk10_crswnp/medical-writing/working-copies/"
        f"{section_id}/intervention-rules-projection"
    )
    with (
        patch.object(app_main, "medical_writing_authoring_journey_service", authoring),
        patch.object(app_main, "medical_writing_document_service", document_service),
        patch.object(app_main, "medical_writing_runtime_repository", repository),
    ):
        return TestClient(app_main.app).post(route, json=payload)


def test_pnh_projection_endpoint_keeps_no_planned_adjustment_and_safety_actions():
    rules = _pnh_like_rules()
    runtime = _runtime("6.4", rules)
    response = _post(runtime, _payload(rules))
    assert response.status_code == 200, response.text
    text = response.json()["projection_block"]["text"]
    assert "没有计划调整剂量" in text
    assert "永久停药" in text
    assert "停药前递减" in text
    assert "停药后随访" in text


@pytest.mark.parametrize(
    ("section_number", "included", "excluded"),
    [
        ("6.4", "立即暂停试验用药品", "1 mg/日"),
        ("6.9", "全身系统性糖皮质激素", "叶酸"),
        ("6.10", "叶酸", "全身系统性糖皮质激素"),
    ],
)
def test_d001_projection_endpoint_preserves_section_boundaries(
    section_number, included, excluded
):
    rules = _d001_like_rules()
    runtime = _runtime(section_number, rules)
    response = _post(runtime, _payload(rules, key=f"project-{section_number}"))
    assert response.status_code == 200, response.text
    text = response.json()["projection_block"]["text"]
    assert included in text
    assert excluded not in text


def test_projection_endpoint_rejects_stale_journey_rules_hash_and_working_copy():
    rules = _pnh_like_rules()

    stale_journey = _payload(rules)
    stale_journey["expected_journey_revision"] = 3
    response = _post(_runtime("6.4", rules), stale_journey)
    assert response.status_code == 409
    assert "authoring journey changed" in response.json()["detail"]

    stale_hash = _payload(rules)
    stale_hash["expected_intervention_rules_sha256"] = "a" * 64
    response = _post(_runtime("6.4", rules), stale_hash)
    assert response.status_code == 409
    assert "intervention rules changed" in response.json()["detail"]

    stale_working_copy = _payload(rules, working_revision=2)
    response = _post(_runtime("6.4", rules), stale_working_copy)
    assert response.status_code == 409
    assert "working copy revision conflict" in response.json()["detail"]


def test_medical_edits_require_explicit_overwrite_and_idempotent_replay_is_safe():
    rules = _pnh_like_rules()
    runtime = _runtime("6.4", rules)
    first_payload = _payload(rules, key="initial-projection")
    first = _post(runtime, first_payload)
    assert first.status_code == 200, first.text

    replay = _post(runtime, first_payload)
    assert replay.status_code == 200, replay.text
    assert len(runtime[2].current.content_blocks) == 2

    edited_blocks = [dict(block) for block in runtime[2].current.content_blocks]
    projected = edited_blocks[-1]
    projected["text"] += " 医学经理补充判断。"
    projected["rich_text"] = {
        "type": "paragraph",
        "attrs": {"stylePreset": "body"},
        "content": [{"type": "text", "text": projected["text"]}],
    }
    runtime[2].current = runtime[2].current.model_copy(
        update={"revision": 2, "content_blocks": edited_blocks},
        deep=True,
    )

    blocked = _post(
        runtime,
        _payload(rules, working_revision=2, key="blocked-reprojection"),
    )
    assert blocked.status_code == 409
    assert "medical edits" in blocked.json()["detail"]

    overwritten = _post(
        runtime,
        _payload(
            rules,
            working_revision=2,
            key="confirmed-reprojection",
            overwrite=True,
        ),
    )
    assert overwritten.status_code == 200, overwritten.text
    assert "医学经理补充判断" not in overwritten.json()["projection_block"]["text"]


def test_projection_endpoint_rejects_unrelated_section():
    rules = _pnh_like_rules()
    response = _post(_runtime("7.1", rules), _payload(rules))
    assert response.status_code == 422
    assert "sections 6.4, 6.9, or 6.10" in response.json()["detail"]
