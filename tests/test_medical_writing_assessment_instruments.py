from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.contracts.workbench_contracts import (
    MedicalWritingAssessmentInstrumentUse,
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingInstrumentRightsState,
    MedicalWritingInstrumentSourceBinding,
    MedicalWritingInstrumentTranslationState,
    MedicalWritingPicosDefinition,
    MedicalWritingStudyFraming,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)


def _framing() -> MedicalWritingStudyFraming:
    return MedicalWritingStudyFraming(
        protocol_id="RUX-03-002",
        version="V1.3",
        document_title="磷酸芦可替尼乳膏治疗特应性皮炎的III期临床研究方案",
        indication="特应性皮炎",
        clinicaltrials_condition_term="Atopic Dermatitis",
        study_phase="III期",
        intrinsic_objectives=["确证性研究"],
        investigational_product="磷酸芦可替尼乳膏",
        target_mechanism="JAK1/JAK2抑制剂",
        design_pattern="随机、双盲、安慰剂对照研究",
        population_intent="12周岁及以上轻中度特应性皮炎参与者",
    )


def _instrument() -> MedicalWritingAssessmentInstrumentUse:
    confirmed_at = datetime(2026, 7, 17, tzinfo=timezone.utc)
    return MedicalWritingAssessmentInstrumentUse(
        instrument_id="instrument_dlqi_rux_v1",
        canonical_name_zh="皮肤病生活质量指数",
        canonical_name_en="Dermatology Life Quality Index",
        acronym="DLQI",
        version_label="成人10题版",
        instrument_kind="patient_reported",
        respondent="试验参与者",
        recall_period="过去7天",
        scoring_range="0-30",
        scoring_direction="分值越高表示生活质量受影响程度越大",
        study_purpose="评价生活质量较基线的变化",
        endpoint_paths=["picos.other_secondary_endpoints"],
        visit_labels=["基线（D1）", "第8周（D57±3天）"],
        appendix_locator="附录4",
        evidence_span_ids=["rux_dlqi_method_001"],
        source_bindings=[
            MedicalWritingInstrumentSourceBinding(
                source_kind="project_protocol",
                source_id="rux_protocol_v1_3",
                title="RUX-03-002 V1.3研究方案",
                locator="docx:paragraph:744;appendix:4",
            )
        ],
        rights=MedicalWritingInstrumentRightsState(
            status="permission_required",
            full_text_policy="metadata_only",
            owner="Cardiff University",
            evidence_url="https://www.cardiff.ac.uk/medicine/resources/quality-of-life-questionnaires/dermatology-life-quality-index",
        ),
        translation=MedicalWritingInstrumentTranslationState(
            source_language="英语",
            target_language="简体中文",
            status="official_available",
            version_label="Chinese versions available; exact study version pending confirmation",
            source_url="https://www.cardiff.ac.uk/medicine/resources/quality-of-life-questionnaires/dermatology-life-quality-index",
        ),
        confirmation_status="confirmed",
        confirmed_by="medical_manager_test",
        confirmed_at=confirmed_at,
    )


def test_assessment_instrument_evidence_span_ids_must_be_unique():
    with pytest.raises(ValidationError, match="evidence_span_ids must be unique"):
        MedicalWritingAssessmentInstrumentUse(
            instrument_id="instrument_duplicate_evidence",
            canonical_name_zh="皮肤病生活质量指数",
            evidence_span_ids=["span_001", "span_001"],
        )


def _picos(*, instruments=None) -> MedicalWritingPicosDefinition:
    return MedicalWritingPicosDefinition(
        design_archetype="randomized_confirmatory",
        population_summary="12周岁及以上轻中度特应性皮炎参与者。",
        inclusion_modules=["IGA评分2-3分"],
        exclusion_modules=["活动性感染"],
        intervention_summary="磷酸芦可替尼乳膏每日两次外用。",
        intervention_dose_regimen="每日两次，间隔至少8小时。",
        comparator_summary="匹配安慰剂每日两次外用。",
        primary_endpoint="第8周达到IGA-TS的参与者比例。",
        other_secondary_endpoints=["第8周DLQI较基线的变化值。"],
        safety_endpoints=["TEAE和SAE发生率。"],
        assessment_instruments=instruments or [],
        study_epochs=["筛选期", "双盲治疗期", "开放治疗期"],
        visit_strategy="筛选、基线及第2、4、8、12、16、20、24周访视。",
        estimand_strategy="评价治疗策略下第8周IGA-TS应答差异。",
        sample_size_strategy="依据主要终点应答率差异估算。",
        statistical_strategy="主要终点采用分层方法比较。",
    )


def test_instrument_contract_keeps_rights_translation_and_project_use_separate():
    item = _instrument()
    assert item.rights.status == "permission_required"
    assert item.rights.full_text_policy == "metadata_only"
    assert item.translation.status == "official_available"
    assert item.endpoint_paths == ["picos.other_secondary_endpoints"]
    assert item.confirmation_status == "confirmed"


def test_full_text_policy_fails_closed_without_permissive_rights():
    with pytest.raises(ValidationError, match="full-text use requires"):
        MedicalWritingInstrumentRightsState(
            status="unknown",
            full_text_policy="open_copy_allowed",
        )


def test_duplicate_ids_and_unsupported_bindings_are_rejected():
    item = _instrument()
    with pytest.raises(ValidationError, match="instrument ids must be unique"):
        _picos(instruments=[item, item])
    with pytest.raises(ValidationError, match="unsupported assessment instrument binding"):
        MedicalWritingAssessmentInstrumentUse(
            instrument_id="bad_binding",
            canonical_name_zh="测试量表",
            endpoint_paths=["picos.unknown_endpoint"],
        )


def test_authoring_journey_persists_instrument_and_reports_all_dependents():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = MedicalWritingAuthoringJourneyService(Path(tmpdir) / "journey.sqlite3")
        created = service.create(
            "proj_rux_instrument_test",
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_framing(),
                actor="medical_manager_test",
                idempotency_key="create-rux-instrument-test",
            ),
        )
        proposed = _picos(instruments=[_instrument()])
        preview = service.impact_preview(
            "proj_rux_instrument_test",
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=created.revision,
                stage="picos",
                picos=proposed,
                actor="medical_manager_test",
                idempotency_key="preview-shape-only",
            ),
        )
        assert "picos.assessment_instruments" in preview.changed_fields
        assert set(
            [
                "objectives_endpoints",
                "eligibility_sections",
                "schedule_of_activities",
                "instrument_appendices",
            ]
        ).issubset(preview.affected_dependents)
        committed = service.commit_stage(
            "proj_rux_instrument_test",
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=created.revision,
                stage="picos",
                picos=proposed,
                impact_preview_id=preview.preview_id,
                actor="medical_manager_test",
                idempotency_key="commit-rux-instrument-test",
            ),
        )
        assert committed.picos.assessment_instruments[0].acronym == "DLQI"
        assert committed.study_definition.field_states["picos.assessment_instruments"].status == "confirmed"
        assert committed.study_definition.picos.assessment_instruments[0].instrument_id == "instrument_dlqi_rux_v1"
        reloaded = service.get("proj_rux_instrument_test")
        assert reloaded.picos.assessment_instruments == committed.picos.assessment_instruments


def test_unconfirmed_instrument_does_not_become_confirmed_study_fact():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = MedicalWritingAuthoringJourneyService(Path(tmpdir) / "journey.sqlite3")
        created = service.create(
            "proj_rux_unconfirmed_instrument",
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_framing(),
                actor="medical_manager_test",
                idempotency_key="create-rux-unconfirmed-instrument",
            ),
        )
        candidate = _instrument().model_copy(
            update={
                "confirmation_status": "needs_review",
                "confirmed_by": "",
                "confirmed_at": None,
            },
            deep=True,
        )
        proposed = _picos(instruments=[candidate])
        preview = service.impact_preview(
            "proj_rux_unconfirmed_instrument",
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=created.revision,
                stage="picos",
                picos=proposed,
                actor="medical_manager_test",
                idempotency_key="preview-rux-unconfirmed-instrument",
            ),
        )
        committed = service.commit_stage(
            "proj_rux_unconfirmed_instrument",
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=created.revision,
                stage="picos",
                picos=proposed,
                impact_preview_id=preview.preview_id,
                actor="medical_manager_test",
                idempotency_key="commit-rux-unconfirmed-instrument",
            ),
        )
        state = committed.study_definition.field_states["picos.assessment_instruments"]
        assert state.status == "manual_candidate"
        assert "picos.assessment_instruments" in committed.study_definition.unresolved_paths
