from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.api.app.ai_runtime_settings import AiProviderProfile
from services.api.app.medical_writing_corpus_analysis_ai import (
    CORPUS_ANALYSIS_PROMPT_VERSION,
    CORPUS_ANALYSIS_RESPONSE_REPAIR_POLICY_VERSION,
    CORPUS_ANALYSIS_SCHEMA_VERSION,
    INDICATION_ALIGNMENT_POLICY_VERSION,
    CorpusAnalysisAiError,
    MedicalWritingCorpusAnalysisAiService,
    _candidate_indication_relation,
    _semantic_project_condition_terms,
)
from services.api.app.medical_writing_research_pipeline import (
    MedicalWritingResearchPipelineService,
    ResearchPipelineError,
    ResearchPipelineState,
)
from services.api.app.writing_reference_repository import TENANT_ID


def test_registry_study_id_is_not_an_indication_semantic_term():
    terms = _semantic_project_condition_terms(
        {
            "indication": "系统性硬化症",
            "clinicaltrials_condition_term": "NCT02663895",
        }
    )

    assert terms == ["系统性硬化症"]
    relation = _candidate_indication_relation(
        terms,
        ["Systemic Sclerosis", "Calcinosis"],
    )
    assert relation["relation"] == "unresolved_cross_language"


def test_condition_query_remains_available_as_an_indication_semantic_term():
    terms = _semantic_project_condition_terms(
        {
            "indication": "系统性硬化症",
            "clinicaltrials_condition_term": "Systemic Sclerosis",
        }
    )

    assert terms == ["系统性硬化症", "Systemic Sclerosis"]
    relation = _candidate_indication_relation(
        terms,
        ["Systemic Sclerosis", "Calcinosis"],
    )
    assert relation["relation"] == "same"


class _ProfileStore:
    def __init__(self, profile: AiProviderProfile):
        self.current = profile

    def active_profile(self):
        return self.current

    def profile(self, profile_id: str):
        if self.current.profile_id != profile_id:
            raise KeyError(profile_id)
        return self.current

    def profile_env(self, profile, base_env=None):
        return dict(base_env or {})


class _Provider:
    def __init__(self, output_factory):
        self.provider_name = "alibaba_token_plan"
        self.model_name = "qwen3.8-max-preview"
        self.base_url = (
            "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        )
        self.transport_name = "openai_compatible"
        self.expected_response_model = self.model_name
        self.response_model = ""
        self.output_factory = output_factory
        self.calls = 0

    def run(self, envelope):
        self.calls += 1
        self.response_model = self.model_name
        return self.output_factory(envelope)


class _Repository:
    def __init__(
        self,
        db_path: Path,
        *,
        sponsor_count: int = 2,
        candidate_condition: str = "Rheumatoid Arthritis",
    ):
        self.db_path = db_path
        self._candidates = []
        self._artifacts = []
        self._spans = {}
        for index in range(sponsor_count):
            nct_id = f"NCT0000000{index + 1}"
            artifact_id = f"artifact_{index + 1}"
            span_id = f"span_{index + 1}"
            self._candidates.append(
                SimpleNamespace(
                    nct_id=nct_id,
                    conditions=[candidate_condition],
                    phases=["PHASE2"],
                    lead_sponsor=f"Sponsor {index + 1}",
                    interventions=[
                        {"name": f"Drug {index + 1}", "intervention_type": "DRUG"}
                    ],
                    design_allocation="RANDOMIZED",
                    design_intervention_model="PARALLEL",
                    design_masking="DOUBLE",
                    model_dump=lambda mode="json", nct_id=nct_id, index=index: {
                        "nct_id": nct_id,
                        "conditions": [candidate_condition],
                        "phases": ["PHASE2"],
                        "lead_sponsor": f"Sponsor {index + 1}",
                        "interventions": [
                            {
                                "name": f"Drug {index + 1}",
                                "intervention_type": "DRUG",
                            }
                        ],
                        "design_allocation": "RANDOMIZED",
                        "design_intervention_model": "PARALLEL",
                        "design_masking": "DOUBLE",
                    },
                )
            )
            self._artifacts.append(
                SimpleNamespace(
                    artifact_id=artifact_id,
                    nct_id=nct_id,
                    source_current=True,
                    document_type="protocol",
                    filename=f"protocol_{index + 1}.pdf",
                    content_sha256=(str(index + 1) * 64)[:64],
                )
            )
            self._spans[artifact_id] = [
                SimpleNamespace(
                    span_id=span_id,
                    source_text=(
                        f"{candidate_condition}. PHASE2 proof-of-concept and "
                        "dose escalation. JAK1 small_molecule tablet oral. "
                        "RANDOMIZED PLACEBO PARALLEL DOUBLE. "
                        "The dosing interval was 12 weeks."
                    ),
                    source_text_sha256=(str(index + 3) * 64)[:64],
                    source_locator=f"page:{index + 5}",
                    physical_page=index + 5,
                    block_index=1,
                    section_heading="Study intervention",
                    ich_m11_anchor="intervention",
                )
            ]
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS writing_reference_audit_chain (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, sequence_no)
                )
                """
            )

    def search_snapshot(self, project_id, snapshot_id):
        return SimpleNamespace(candidates=self._candidates)

    def translations(self, project_id):
        return []

    def document_artifacts(self, project_id, snapshot_id=None):
        return list(self._artifacts)

    def latest_extraction_revision(self, project_id, artifact_id):
        return "extract_r1"

    def source_spans(
        self, project_id, artifact_id, extraction_revision=None
    ):
        return list(self._spans[artifact_id])


class _SplitEvidenceRepository(_Repository):
    """Repository variant where each sponsor has distinct evidence text.

    Used to prove that composite facts scattered across separate bindings
    cannot reach high confidence within a single coherent source.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        span_texts: list[str],
        candidate_condition: str = "Rheumatoid Arthritis",
    ):
        super().__init__(
            db_path,
            sponsor_count=len(span_texts),
            candidate_condition=candidate_condition,
        )
        for index, text in enumerate(span_texts):
            artifact_id = f"artifact_{index + 1}"
            span_id = f"span_{index + 1}"
            self._spans[artifact_id] = [
                SimpleNamespace(
                    span_id=span_id,
                    source_text=text,
                    source_text_sha256=(str(index + 3) * 64)[:64],
                    source_locator=f"page:{index + 5}",
                    physical_page=index + 5,
                    block_index=1,
                    section_heading="Study intervention",
                    ich_m11_anchor="intervention",
                )
            ]


def _profile(*, revision: int = 1) -> AiProviderProfile:
    return AiProviderProfile(
        profile_id="alibaba_qwen38",
        provider="alibaba_token_plan",
        label="Alibaba Qwen",
        base_url=(
            "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        ),
        model="qwen3.8-max-preview",
        expected_response_model="qwen3.8-max-preview",
        deployment_profile="local_private_clinical",
        revision=revision,
    )


def _journey():
    return SimpleNamespace(
        framing=SimpleNamespace(
            indication="类风湿关节炎",
            clinicaltrials_condition_term="Rheumatoid Arthritis",
            study_phase="II期",
            intrinsic_objectives=["概念验证", "剂量探索"],
            investigational_product="CMS-RA01",
            target_mechanism="JAK1",
            product_profile=SimpleNamespace(
                technology_type="small_molecule",
                technology_description="选择性JAK1抑制剂",
                dosage_forms=["片剂"],
                administration_routes=["口服"],
            ),
            structured_design=SimpleNamespace(
                model_dump=lambda mode="json": {
                    "randomization": "randomized",
                    "control": "placebo",
                }
            ),
        )
    )


def _pnh_journey(*, clinicaltrials_condition_term: str = ""):
    journey = _journey()
    journey.framing.indication = "阵发性睡眠性血红蛋白尿症"
    journey.framing.clinicaltrials_condition_term = (
        clinicaltrials_condition_term
    )
    return journey


def _ad_journey():
    journey = _journey()
    journey.framing.indication = "Atopic Dermatitis"
    journey.framing.clinicaltrials_condition_term = "Atopic Dermatitis"
    return journey


def _valid_output(
    envelope,
    *,
    finding_statement="两份方案均采用12周给药间隔。",
    pattern_kind="clinical_design_requirement",
):
    evidence = envelope.payload["evidence_catalog"]
    bindings = [
        {"evidence_id": item["evidence_id"]}
        for item in evidence
    ]
    return {
        "schema_version": CORPUS_ANALYSIS_SCHEMA_VERSION,
        "analysis_id": envelope.payload["analysis_id"],
        "project_context_hash": envelope.payload["project_context_hash"],
        "findings": [
            {
                "finding_id": "mwca_finding_intervention_001",
                "module": "intervention",
                "pattern_kind": pattern_kind,
                "statement_zh": finding_statement,
                "transfer_scope": "same_indication",
                "layer": {
                    "indications": list(
                        dict.fromkeys(
                            condition
                            for item in evidence
                            for condition in item["conditions"]
                        )
                    ),
                    "phases": ["PHASE2"],
                    "research_purposes": [
                        "proof-of-concept",
                        "dose escalation",
                    ],
                    "mechanisms": ["JAK1"],
                    "technology_types": ["small_molecule"],
                    "dosage_forms": ["tablet"],
                    "administration_routes": ["oral"],
                    "design_modules": [
                        "RANDOMIZED",
                        "PLACEBO",
                        "PARALLEL",
                        "DOUBLE",
                    ],
                },
                "evidence_bindings": bindings,
                "conflicts": [],
                "unresolved_gaps": ["来源未报告作用机制。"],
            }
        ],
        "evidence_gaps": ["未形成可比的剂量强度结论。"],
        "global_conflicts": [],
    }


def _service(tmp_path, repository, provider):
    store = _ProfileStore(_profile())
    service = MedicalWritingCorpusAnalysisAiService(
        repository,
        runtime_settings_store=store,
        profile_provider_factory=lambda profile: provider,
    )
    return service, store


def test_role_binding_profile_overrides_stale_legacy_active_profile(tmp_path):
    repository = _Repository(tmp_path / "writing_reference.sqlite3")
    active_profile = _profile()
    role_profile = AiProviderProfile(
        profile_id="independent_ai__deepseek_v4_pro",
        provider="deepseek",
        label="DeepSeek role route",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        expected_response_model="deepseek-v4-pro",
        deployment_profile="local_private_clinical",
        revision=3,
    )
    store = _ProfileStore(active_profile)
    provider = SimpleNamespace(
        provider_name=role_profile.provider,
        model_name=role_profile.model,
        base_url=role_profile.base_url,
        transport_name=role_profile.transport,
        expected_response_model=role_profile.expected_response_model,
    )
    service = MedicalWritingCorpusAnalysisAiService(
        repository,
        runtime_settings_store=store,
        profile_provider_factory=lambda profile: provider,
        active_profile_resolver=lambda: role_profile,
    )

    route = service.freeze_active_route()

    assert route["profile_id"] == role_profile.profile_id
    assert route["profile_revision"] == role_profile.revision
    assert route["model"] == role_profile.model
    assert store.active_profile().profile_id == active_profile.profile_id


def test_frozen_route_audits_effective_thinking_and_reasoning_effort(tmp_path):
    repository = _Repository(tmp_path / "writing_reference.sqlite3")
    provider = _Provider(_valid_output)
    provider.default_thinking = "enabled"
    provider.default_reasoning_effort = "max"
    service, _store = _service(tmp_path, repository, provider)

    route = service.freeze_active_route()

    assert route["thinking"] == "enabled"
    assert route["reasoning_effort"] == "max"
    assert route["identity_hash"]
    replay = service.analyze(
        project_id="proj_route_options",
        pipeline_id="mwpipe_route_options",
        snapshot_id="snapshot_route_options",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=route,
    )
    assert replay["ai_route"]["reasoning_effort"] == "max"


def test_round1_analysis_uses_frozen_product_ai_and_persists_high_confidence(
    tmp_path,
):
    repository = _Repository(tmp_path / "writing_reference.sqlite3")
    provider = _Provider(_valid_output)
    service, _store = _service(tmp_path, repository, provider)
    route = service.freeze_active_route()

    result = service.analyze(
        project_id="proj_ra",
        pipeline_id="mwpipe_ra",
        snapshot_id="snapshot_ra",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=route,
    )

    assert provider.calls == 1
    assert result["status"] == "completed"
    assert result["ai_route"]["profile_id"] == "alibaba_qwen38"
    assert result["response_model"] == "qwen3.8-max-preview"
    assert result["evidence_summary_ids"] == [
        "mwca_finding_intervention_001"
    ]
    finding = result["analysis"]["findings"][0]
    assert finding["confidence"] == "high"
    assert finding["support"]["source_count"] == 2
    assert finding["support"]["sponsor_count"] == 2
    assert finding["support"]["high_confidence_eligible"] is True
    assert finding["pattern_kind"] == "clinical_design_requirement"
    assert finding["content_role"] == "project_fact_reference"
    assert finding["evidence_tier"] == "tier1_same_indication_layered"
    assert finding["reuse_decision"] == "project_fact_reference_only"
    assert finding["support"]["pattern_kind"] == (
        "clinical_design_requirement"
    )
    assert finding["support"]["generalization_scope"] == (
        "same_indication_layered_only"
    )
    assert finding["support"]["generalization_scope"] != "legacy_untyped"
    assert all(
        profile["source_id"].startswith("artifact_")
        and profile["source_file"].startswith("protocol_")
        and profile["document_sha256"]
        and profile["sponsor"]
        and set(profile["layer"]) == {
            "indication",
            "phase",
            "research_purpose",
            "mechanism",
            "technology_type",
            "dosage_form",
            "administration_route",
            "design_module",
        }
        for profile in finding["support"]["evidence_profiles"]
    )
    assert {
        item["lead_sponsor"] for item in finding["evidence_bindings"]
    } == {"Sponsor 1", "Sponsor 2"}

    replay = service.analyze(
        project_id="proj_ra",
        pipeline_id="mwpipe_ra",
        snapshot_id="snapshot_ra",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=route,
    )
    assert replay["analysis_id"] == result["analysis_id"]
    assert provider.calls == 1


def test_single_source_and_sponsor_can_never_be_high_confidence(tmp_path):
    repository = _Repository(
        tmp_path / "writing_reference.sqlite3", sponsor_count=1
    )
    provider = _Provider(
        lambda envelope: _valid_output(
            envelope,
            finding_statement="该来源报告12周给药间隔。",
        )
    )
    service, _store = _service(tmp_path, repository, provider)

    result = service.analyze(
        project_id="proj_ra",
        pipeline_id="mwpipe_ra",
        snapshot_id="snapshot_ra",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=service.freeze_active_route(),
    )

    finding = result["analysis"]["findings"][0]
    assert finding["confidence"] == "low"
    assert finding["support"]["high_confidence_eligible"] is False
    assert "fewer_than_two_independent_sources" in finding["support"]["reasons"]
    assert "fewer_than_two_sponsors" in finding["support"]["reasons"]
    assert finding["reuse_decision"] == (
        "insufficient_support_do_not_generalize"
    )
    assert any(
        "独立来源不足" in gap for gap in finding["unresolved_gaps"]
    )
    assert any(
        "独立申办方不足" in gap for gap in finding["unresolved_gaps"]
    )


def test_single_source_cannot_claim_multiple_protocols(tmp_path):
    repository = _Repository(
        tmp_path / "writing_reference.sqlite3", sponsor_count=1
    )
    provider = _Provider(_valid_output)
    service, _store = _service(tmp_path, repository, provider)

    with pytest.raises(
        CorpusAnalysisAiError,
        match="claims multiple sources",
    ):
        service.analyze(
            project_id="proj_ra_overclaim",
            pipeline_id="mwpipe_ra_overclaim",
            snapshot_id="snapshot_ra_overclaim",
            journey=_journey(),
            actor="medical_manager",
            frozen_route=service.freeze_active_route(),
        )


def test_sparse_evidence_cannot_use_generalized_usage_wording(tmp_path):
    repository = _Repository(
        tmp_path / "writing_reference.sqlite3", sponsor_count=1
    )
    provider = _Provider(
        lambda envelope: _valid_output(
            envelope,
            finding_statement="同适应症方案通常采用12周给药间隔。",
        )
    )
    service, _store = _service(tmp_path, repository, provider)

    with pytest.raises(
        CorpusAnalysisAiError,
        match="generalized usage wording",
    ):
        service.analyze(
            project_id="proj_ra_usage_overclaim",
            pipeline_id="mwpipe_ra_usage_overclaim",
            snapshot_id="snapshot_ra_usage_overclaim",
            journey=_journey(),
            actor="medical_manager",
            frozen_route=service.freeze_active_route(),
        )


def test_server_derives_sparse_support_gaps_when_model_omits_them(tmp_path):
    repository = _Repository(
        tmp_path / "writing_reference.sqlite3", sponsor_count=1
    )

    def output(envelope):
        payload = _valid_output(
            envelope,
            finding_statement="该来源报告12周给药间隔。",
        )
        payload["findings"][0]["unresolved_gaps"] = []
        return payload

    provider = _Provider(output)
    service, _store = _service(tmp_path, repository, provider)
    result = service.analyze(
        project_id="proj_ra_sparse_gaps",
        pipeline_id="mwpipe_ra_sparse_gaps",
        snapshot_id="snapshot_ra_sparse_gaps",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=service.freeze_active_route(),
    )

    gaps = result["analysis"]["findings"][0]["unresolved_gaps"]
    assert any("独立来源不足" in item for item in gaps)
    assert any("独立申办方不足" in item for item in gaps)


def test_ad_same_indication_wording_generalizes_only_with_multi_source_support(
    tmp_path,
):
    repository = _Repository(
        tmp_path / "writing_reference.sqlite3",
        candidate_condition="Atopic Dermatitis",
    )
    provider = _Provider(
        lambda envelope: _valid_output(
            envelope,
            pattern_kind="wording_convention",
        )
    )
    service, _store = _service(tmp_path, repository, provider)

    result = service.analyze(
        project_id="proj_ad",
        pipeline_id="mwpipe_ad",
        snapshot_id="snapshot_ad",
        journey=_ad_journey(),
        actor="medical_manager",
        frozen_route=service.freeze_active_route(),
    )

    finding = result["analysis"]["findings"][0]
    assert finding["confidence"] == "high"
    assert finding["content_role"] == "indication_specific_wording"
    assert finding["evidence_tier"] == "tier1_same_indication_layered"
    assert finding["reuse_decision"] == "evidence_supported_candidate"
    assert finding["support"]["source_count"] == 2
    assert finding["support"]["sponsor_count"] == 2


def test_conflicting_sources_are_preserved_and_never_auto_selected(tmp_path):
    common = (
        "Rheumatoid Arthritis. PHASE2 proof-of-concept and dose escalation. "
        "JAK1 small_molecule tablet oral. RANDOMIZED PLACEBO PARALLEL DOUBLE. "
        "The dosing interval was 12 weeks. "
    )
    repository = _SplitEvidenceRepository(
        tmp_path / "writing_reference.sqlite3",
        span_texts=[
            common + "推荐表达甲。",
            common + "推荐表达乙。",
        ],
    )

    def output(envelope):
        payload = _valid_output(envelope)
        evidence = envelope.payload["evidence_catalog"]
        payload["findings"][0]["conflicts"] = [
            {
                "claim_value_zh": "推荐表达甲。",
                "evidence_bindings": [
                    {"evidence_id": evidence[0]["evidence_id"]}
                ],
            },
            {
                "claim_value_zh": "推荐表达乙。",
                "evidence_bindings": [
                    {"evidence_id": evidence[1]["evidence_id"]}
                ],
            },
        ]
        return payload

    provider = _Provider(output)
    service, _store = _service(tmp_path, repository, provider)
    result = service.analyze(
        project_id="proj_ra_conflict",
        pipeline_id="mwpipe_ra_conflict",
        snapshot_id="snapshot_ra_conflict",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=service.freeze_active_route(),
    )

    finding = result["analysis"]["findings"][0]
    assert finding["confidence"] == "requires_medical_review"
    assert finding["reuse_decision"] == "conflict_preserved_do_not_select"
    assert finding["support"]["conflicting_values"]
    assert len(finding["conflicts"]) == 2


def test_numeric_claim_not_present_in_bound_evidence_fails_closed(tmp_path):
    repository = _Repository(tmp_path / "writing_reference.sqlite3")
    provider = _Provider(
        lambda envelope: _valid_output(
            envelope, finding_statement="两份方案均采用16周给药间隔。"
        )
    )
    service, _store = _service(tmp_path, repository, provider)

    with pytest.raises(CorpusAnalysisAiError, match="numeric corpus claim"):
        service.analyze(
            project_id="proj_ra",
            pipeline_id="mwpipe_ra",
            snapshot_id="snapshot_ra",
            journey=_journey(),
            actor="medical_manager",
            frozen_route=service.freeze_active_route(),
        )


def test_unknown_source_binding_is_rejected_without_discarding_valid_findings(
    tmp_path,
):
    repository = _Repository(tmp_path / "writing_reference.sqlite3")

    def output(envelope):
        payload = _valid_output(envelope)
        invalid = copy.deepcopy(payload["findings"][0])
        invalid["finding_id"] = "mwca_finding_unknown_source"
        invalid["evidence_bindings"][0]["evidence_id"] = "cae_model_invented"
        payload["findings"].append(invalid)
        return payload

    provider = _Provider(output)
    service, _store = _service(tmp_path, repository, provider)
    result = service.analyze(
        project_id="proj_ra",
        pipeline_id="mwpipe_ra",
        snapshot_id="snapshot_ra",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=service.freeze_active_route(),
    )

    assert result["status"] == "completed"
    assert result["validation_rejection_count"] == 1
    assert result["evidence_summary_ids"] == [
        "mwca_finding_intervention_001"
    ]
    rejection = result["analysis"]["validation_rejections"][0]
    assert rejection["item_id"] == "mwca_finding_unknown_source"
    assert "unknown corpus evidence_id" in rejection["reason"]


def test_unsupported_pattern_kind_is_rejected_by_server(tmp_path):
    repository = _Repository(tmp_path / "writing_reference.sqlite3")

    def output(envelope):
        payload = _valid_output(envelope)
        payload["findings"][0]["pattern_kind"] = "model_invented_kind"
        return payload

    provider = _Provider(output)
    service, _store = _service(tmp_path, repository, provider)

    with pytest.raises(
        CorpusAnalysisAiError,
        match="unsupported corpus pattern_kind: model_invented_kind",
    ):
        service.analyze(
            project_id="proj_ra",
            pipeline_id="mwpipe_ra",
            snapshot_id="snapshot_ra",
            journey=_journey(),
            actor="medical_manager",
            frozen_route=service.freeze_active_route(),
        )


def test_unbound_layer_value_is_removed_and_audited(tmp_path):
    repository = _Repository(tmp_path / "writing_reference.sqlite3")

    def output(envelope):
        payload = _valid_output(envelope)
        payload["findings"][0]["layer"]["mechanisms"] = [
            "模型臆造的JAK3机制"
        ]
        return payload

    provider = _Provider(output)
    service, _store = _service(tmp_path, repository, provider)
    result = service.analyze(
        project_id="proj_ra",
        pipeline_id="mwpipe_ra",
        snapshot_id="snapshot_ra",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=service.freeze_active_route(),
    )

    finding = result["analysis"]["findings"][0]
    assert finding["layer"]["mechanisms"] == []
    assert finding["layer_rejections"] == [
        "mechanisms:模型臆造的JAK3机制"
    ]


def test_cross_indication_clinical_logic_cannot_transfer(tmp_path):
    repository = _Repository(
        tmp_path / "writing_reference.sqlite3",
        candidate_condition="Atopic Dermatitis",
    )

    def output(envelope):
        payload = _valid_output(envelope)
        finding = payload["findings"][0]
        finding["module"] = "structure"
        finding["pattern_kind"] = "regulatory_common_structure"
        finding["transfer_scope"] = "cross_indication_structure_only"
        finding["statement_zh"] = "入选标准要求疾病活动度评分达到12分。"
        finding["layer"]["indications"] = ["Atopic Dermatitis"]
        return payload

    provider = _Provider(output)
    service, _store = _service(tmp_path, repository, provider)

    with pytest.raises(
        CorpusAnalysisAiError,
        match="cross-indication finding contains non-transferable",
    ):
        service.analyze(
            project_id="proj_ra",
            pipeline_id="mwpipe_ra",
            snapshot_id="snapshot_ra",
            journey=_journey(),
            actor="medical_manager",
            frozen_route=service.freeze_active_route(),
        )


def test_cross_indication_wording_convention_is_rejected_in_production_path(
    tmp_path,
):
    repository = _Repository(
        tmp_path / "writing_reference.sqlite3",
        candidate_condition="Atopic Dermatitis",
    )

    def output(envelope):
        payload = _valid_output(
            envelope, pattern_kind="wording_convention"
        )
        finding = payload["findings"][0]
        finding["transfer_scope"] = "cross_indication_structure_only"
        finding["layer"]["indications"] = ["Atopic Dermatitis"]
        return payload

    provider = _Provider(output)
    service, _store = _service(tmp_path, repository, provider)

    with pytest.raises(
        CorpusAnalysisAiError,
        match="cross-indication transfer requires "
        "regulatory_common_structure",
    ):
        service.analyze(
            project_id="proj_ra",
            pipeline_id="mwpipe_ra",
            snapshot_id="snapshot_ra",
            journey=_journey(),
            actor="medical_manager",
            frozen_route=service.freeze_active_route(),
        )


def test_incomplete_project_target_layer_requires_medical_confirmation(
    tmp_path,
):
    journey = _journey()
    journey.framing.target_mechanism = ""
    repository = _Repository(tmp_path / "writing_reference.sqlite3")
    provider = _Provider(_valid_output)
    service, _store = _service(tmp_path, repository, provider)

    result = service.analyze(
        project_id="proj_ra_incomplete",
        pipeline_id="mwpipe_ra_incomplete",
        snapshot_id="snapshot_ra_incomplete",
        journey=journey,
        actor="medical_manager",
        frozen_route=service.freeze_active_route(),
    )

    finding = result["analysis"]["findings"][0]
    assert finding["confidence"] == "requires_medical_review"
    assert finding["support"]["high_confidence_eligible"] is False
    assert finding["support"]["pattern_kind"] == (
        "clinical_design_requirement"
    )
    assert any(
        reason.startswith("target_layer_incomplete:mechanism")
        for reason in finding["support"]["reasons"]
    )
    assert service._project_target_layer(
        service._project_context(journey)
    )["mechanism"] == []


def test_cross_indication_regulatory_structure_has_limited_transfer_scope(
    tmp_path,
):
    repository = _Repository(
        tmp_path / "writing_reference.sqlite3",
        candidate_condition="Atopic Dermatitis",
    )

    def output(envelope):
        payload = _valid_output(
            envelope,
            finding_statement=(
                "受试者签署知情同意书前，不得实施任何试验相关程序。"
            ),
            pattern_kind="regulatory_common_structure",
        )
        finding = payload["findings"][0]
        finding["module"] = "regulatory_commonality"
        finding["transfer_scope"] = "cross_indication_structure_only"
        finding["layer"]["indications"] = ["Atopic Dermatitis"]
        return payload

    provider = _Provider(output)
    service, _store = _service(tmp_path, repository, provider)
    result = service.analyze(
        project_id="proj_ra_regulatory",
        pipeline_id="mwpipe_ra_regulatory",
        snapshot_id="snapshot_ra_regulatory",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=service.freeze_active_route(),
    )

    finding = result["analysis"]["findings"][0]
    assert finding["pattern_kind"] == "regulatory_common_structure"
    assert finding["confidence"] == "high"
    assert finding["support"]["generalization_scope"] == (
        "cross_indication_structure_or_regulatory_common_only"
    )
    assert finding["support"]["generalization_scope"] != "legacy_untyped"
    assert finding["content_role"] == "regulatory_fixed_wording"
    assert finding["evidence_tier"] == (
        "tier2_related_domain_or_design_structure_reference"
    )
    assert finding["reuse_decision"] == "evidence_supported_candidate"


@pytest.mark.parametrize(
    "source_condition",
    [
        "Paroxysmal Nocturnal Hemoglobinuria (PNH)",
        "Paroxysmal Nocturnal Haemoglobinuria",
        "PNH",
    ],
)
def test_pnh_chinese_english_and_acronym_use_controlled_alignment(
    source_condition,
):
    alignment = _candidate_indication_relation(
        ["阵发性睡眠性血红蛋白尿症"],
        [source_condition],
    )

    assert alignment["relation"] == "same_controlled_alias"
    assert alignment["status"] == "verified_controlled_alias"
    assert alignment["concept_id"] == "pnh"
    assert alignment["policy_version"] == INDICATION_ALIGNMENT_POLICY_VERSION
    assert alignment["source_conditions"] == [source_condition]


def test_pnh_same_indication_finding_accepts_controlled_translation_proof(
    tmp_path,
):
    repository = _Repository(
        tmp_path / "writing_reference.sqlite3",
        candidate_condition="Paroxysmal Nocturnal Hemoglobinuria (PNH)",
    )
    provider = _Provider(_valid_output)
    service, _store = _service(tmp_path, repository, provider)

    result = service.analyze(
        project_id="proj_pnh",
        pipeline_id="mwpipe_pnh",
        snapshot_id="snapshot_pnh",
        journey=_pnh_journey(),
        actor="medical_manager",
        frozen_route=service.freeze_active_route(),
    )

    finding = result["analysis"]["findings"][0]
    assert finding["transfer_scope"] == "same_indication"
    assert finding["indication_alignment_status"] == (
        "verified_controlled_alias"
    )
    assert finding["confidence"] == "high"
    proof = finding["indication_alignment_proofs"][0]
    assert proof["proof_type"] == "controlled_translation_or_acronym"
    assert proof["source_conditions"] == [
        "Paroxysmal Nocturnal Hemoglobinuria (PNH)"
    ]
    assert finding["evidence_bindings"][0]["indication_relation"] == (
        "same_controlled_alias"
    )


def test_unresolved_cross_language_same_indication_requires_medical_confirmation(
    tmp_path,
):
    repository = _Repository(
        tmp_path / "writing_reference.sqlite3",
        candidate_condition="Unmapped English Disease Name",
    )
    provider = _Provider(_valid_output)
    service, _store = _service(tmp_path, repository, provider)

    result = service.analyze(
        project_id="proj_unmapped",
        pipeline_id="mwpipe_unmapped",
        snapshot_id="snapshot_unmapped",
        journey=_pnh_journey(),
        actor="medical_manager",
        frozen_route=service.freeze_active_route(),
    )

    finding = result["analysis"]["findings"][0]
    assert finding["transfer_scope"] == "same_indication"
    assert finding["indication_alignment_status"] == (
        "pending_medical_confirmation"
    )
    assert finding["confidence"] == "requires_medical_review"
    assert finding["support"]["high_confidence_eligible"] is False
    assert "same_indication_cross_language_alignment_pending" in finding[
        "support"
    ]["reasons"]
    proof = finding["indication_alignment_proofs"][0]
    assert proof["relation"] == "unresolved_cross_language"
    assert proof["project_terms"] == ["阵发性睡眠性血红蛋白尿症"]
    assert proof["source_conditions"] == ["Unmapped English Disease Name"]


def test_same_language_lexical_mismatch_cannot_claim_same_indication(tmp_path):
    repository = _Repository(
        tmp_path / "writing_reference.sqlite3",
        candidate_condition="Atopic Dermatitis",
    )
    provider = _Provider(_valid_output)
    service, _store = _service(tmp_path, repository, provider)

    with pytest.raises(
        CorpusAnalysisAiError,
        match="no evidence-bound corpus findings",
    ):
        service.analyze(
            project_id="proj_ra",
            pipeline_id="mwpipe_ra",
            snapshot_id="snapshot_ra",
            journey=_journey(),
            actor="medical_manager",
            frozen_route=service.freeze_active_route(),
        )


def test_changed_profile_revision_cannot_redirect_frozen_analysis(tmp_path):
    repository = _Repository(tmp_path / "writing_reference.sqlite3")
    provider = _Provider(_valid_output)
    service, store = _service(tmp_path, repository, provider)
    route = service.freeze_active_route()
    store.current = _profile(revision=2)

    with pytest.raises(CorpusAnalysisAiError, match="profile revision changed"):
        service.analyze(
            project_id="proj_ra",
            pipeline_id="mwpipe_ra",
            snapshot_id="snapshot_ra",
            journey=_journey(),
            actor="medical_manager",
            frozen_route=route,
        )
    assert provider.calls == 0


def test_legacy_persisted_v6_analysis_remains_readable_without_mutation(
    tmp_path,
):
    repository = _Repository(tmp_path / "writing_reference.sqlite3")
    provider = _Provider(_valid_output)
    service, _store = _service(tmp_path, repository, provider)
    legacy_result = {
        "analysis_id": "mwca_legacy_v6",
        "project_id": "proj_legacy",
        "prompt_version": "competitor_protocol_corpus_analysis_v6",
        "schema_version": "competitor_protocol_corpus_analysis_v2",
        "analysis": {
            "findings": [
                {
                    "finding_id": "legacy_finding",
                    "support": {
                        "generalization_scope": "legacy_untyped",
                    },
                }
            ]
        },
    }
    serialized = json.dumps(
        legacy_result, ensure_ascii=False, sort_keys=True
    )
    with service._connect() as connection:
        connection.execute(
            """
            INSERT INTO writing_reference_corpus_analysis_runs(
                tenant_id, project_id, analysis_id, pipeline_id,
                snapshot_id, status, prompt_version, schema_version,
                input_hash, output_hash, route_identity_hash, route_json,
                input_payload_json, result_json, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_ID,
                "proj_legacy",
                "mwca_legacy_v6",
                "mwpipe_legacy",
                "snapshot_legacy",
                "completed",
                "competitor_protocol_corpus_analysis_v6",
                "competitor_protocol_corpus_analysis_v2",
                "1" * 64,
                "2" * 64,
                "3" * 64,
                "{}",
                "{}",
                serialized,
                "medical_manager",
                "2026-07-26T00:00:00+00:00",
            ),
        )

    loaded = service.get_analysis("proj_legacy", "mwca_legacy_v6")

    assert loaded == legacy_result
    with service._connect() as connection:
        stored = connection.execute(
            """
            SELECT result_json
            FROM writing_reference_corpus_analysis_runs
            WHERE tenant_id=? AND project_id=? AND analysis_id=?
            """,
            (TENANT_ID, "proj_legacy", "mwca_legacy_v6"),
        ).fetchone()
    assert str(stored["result_json"]) == serialized


def test_research_pipeline_round1_consumes_real_analysis_artifact():
    class _AnalysisService:
        def analyze(self, **kwargs):
            assert kwargs["frozen_route"]["profile_id"] == "alibaba_qwen38"
            return {
                "status": "completed",
                "analysis_id": "mwca_real_analysis",
                "output_hash": "a" * 64,
                "evidence_summary_ids": ["mwca_finding_001"],
            }

    pipeline = object.__new__(MedicalWritingResearchPipelineService)
    pipeline.corpus_analysis_ai_service = _AnalysisService()
    pipeline.journey_service = SimpleNamespace(get=lambda project_id: _journey())
    state = ResearchPipelineState(
        pipeline_id="mwpipe_ra",
        project_id="proj_ra",
        snapshot_id="snapshot_ra",
        round1_ai_route={"profile_id": "alibaba_qwen38"},
    )

    brief_ids = pipeline._run_round1_analysis(
        "proj_ra", "medical_manager", state
    )

    assert brief_ids == ["mwca_finding_001"]
    assert state.round1_analysis_id == "mwca_real_analysis"
    assert state.round1_analysis_output_hash == "a" * 64
    assert "已持久化" in state.detail


def test_research_pipeline_round1_has_no_marker_fallback():
    pipeline = object.__new__(MedicalWritingResearchPipelineService)
    pipeline.corpus_analysis_ai_service = SimpleNamespace()
    pipeline.journey_service = SimpleNamespace(get=lambda project_id: _journey())
    state = ResearchPipelineState(
        pipeline_id="mwpipe_ra",
        project_id="proj_ra",
        snapshot_id="snapshot_ra",
        round1_ai_route={},
    )

    with pytest.raises(ResearchPipelineError, match="缺少冻结"):
        pipeline._run_round1_analysis("proj_ra", "medical_manager", state)


def test_prompt_contract_is_structured_and_forbids_override(tmp_path):
    repository = _Repository(tmp_path / "writing_reference.sqlite3")
    provider = _Provider(_valid_output)
    service, _store = _service(tmp_path, repository, provider)
    prompt = service._system_prompt()
    contract = service._output_contract()

    assert CORPUS_ANALYSIS_PROMPT_VERSION == (
        "competitor_protocol_corpus_analysis_v12"
    )
    assert CORPUS_ANALYSIS_SCHEMA_VERSION == (
        "competitor_protocol_corpus_analysis_v4"
    )
    assert contract["finding"]["pattern_kind"] == [
        "clinical_design_requirement",
        "regulatory_common_structure",
        "wording_convention",
    ]
    assert "pattern_kind" in contract["finding"]["keys"]
    assert contract["finding"]["server_derived_fields"]["content_role"] == [
        "structure_template",
        "regulatory_fixed_wording",
        "indication_specific_wording",
        "project_fact_reference",
    ]
    for required in (
        "严格JSON",
        "evidence_id",
        "数字",
        "wording_convention",
        "clinical_design_requirement",
        "regulatory_common_structure",
        "module=structure或module=regulatory_commonality",
        "该字段不可省略、不可留空、不可由服务器猜测",
        "不同适应症的表达措辞惯例和临床设计",
        "跨适应症",
        "同疾病领域或相近研究设计",
        "章节结构模板",
        "适应症特异措辞",
        "至少两个独立文档",
        "常用",
        "独立来源、申办方和分层证据",
        "均采用",
        "申办方",
        "placeholder",
        "corpus override",
        "最外层必须是完整的analysis envelope",
    ):
        assert required in prompt
    assert "message.content" in prompt
    assert "reasoning_content" in prompt
    assert "schema_version" in prompt


def test_rejected_finding_diagnostics_preserve_only_safe_contract_details(tmp_path):
    repository = _Repository(tmp_path / "writing_reference.sqlite3")

    def output(envelope):
        payload = _valid_output(envelope, pattern_kind="wording_convention")
        payload["findings"][0]["module"] = "structure"
        return payload

    provider = _Provider(output)
    service, _store = _service(tmp_path, repository, provider)
    with pytest.raises(CorpusAnalysisAiError) as exc_info:
        service.analyze(
            project_id="proj_rejected_structure",
            pipeline_id="mwpipe_rejected_structure",
            snapshot_id="snapshot_rejected_structure",
            journey=_journey(),
            actor="medical_manager",
            frozen_route=service.freeze_active_route(),
        )

    diagnostics = exc_info.value.diagnostics
    assert diagnostics["failure_code"] == "corpus_findings_rejected"
    assert diagnostics["validated_finding_count"] == 0
    assert diagnostics["validation_rejection_count"] == 1
    assert "regulatory_common_structure pattern_kind" in diagnostics[
        "validation_rejections"
    ][0]["reason"]
    assert len(diagnostics["raw_output_sha256"]) == 64
    assert "statement_zh" not in str(diagnostics)


def test_single_finding_root_is_repaired_only_with_auditable_shape(tmp_path):
    repository = _Repository(tmp_path / "writing_reference.sqlite3")

    def singleton_output(envelope):
        return _valid_output(envelope)["findings"][0]

    provider = _Provider(singleton_output)
    service, _store = _service(tmp_path, repository, provider)

    result = service.analyze(
        project_id="proj_singleton",
        pipeline_id="pipe_singleton",
        snapshot_id="snapshot_singleton",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=service.freeze_active_route(),
    )

    assert provider.calls == 1
    assert result["status"] == "completed"
    assert result["response_normalization"]["policy_version"] == (
        CORPUS_ANALYSIS_RESPONSE_REPAIR_POLICY_VERSION
    )
    assert result["response_normalization"]["status"] == (
        "single_finding_root_repaired"
    )
    assert set(result["raw_model_output"]) == {
        "finding_id",
        "module",
        "pattern_kind",
        "statement_zh",
        "transfer_scope",
        "layer",
        "evidence_bindings",
        "conflicts",
        "unresolved_gaps",
    }
    assert len(result["analysis"]["findings"]) == 1


def test_partial_root_is_not_repaired(tmp_path):
    repository = _Repository(tmp_path / "writing_reference.sqlite3")

    def partial_output(_envelope):
        return {"findings": []}

    provider = _Provider(partial_output)
    service, _store = _service(tmp_path, repository, provider)

    with pytest.raises(CorpusAnalysisAiError, match="root keys"):
        service.analyze(
            project_id="proj_partial",
            pipeline_id="pipe_partial",
            snapshot_id="snapshot_partial",
            journey=_journey(),
            actor="medical_manager",
            frozen_route=service.freeze_active_route(),
        )


# ---------------------------------------------------------------------------
# Cluster A negative tests (G1/G2/G7) — single-binding co-observability guard
# ---------------------------------------------------------------------------


def _split_output_factory(
    *,
    statement: str,
    route_value: str,
    route_axis: str = "administration_routes",
    layer_overrides: dict[str, list[str]] | None = None,
):
    """Build an AI output where the composite statement binds evidence from
    two sponsors whose individual texts only contain *part* of the claim."""

    def output(envelope):
        evidence = envelope.payload["evidence_catalog"]
        bindings = [
            {"evidence_id": item["evidence_id"]} for item in evidence
        ]
        layer: dict[str, list[str]] = {
            "indications": list(
                dict.fromkeys(
                    condition
                    for item in evidence
                    for condition in item["conditions"]
                )
            ),
            "phases": ["PHASE2"],
            "research_purposes": ["proof-of-concept", "dose escalation"],
            "mechanisms": ["JAK1"],
            "technology_types": ["small_molecule"],
            "dosage_forms": ["tablet"],
            "administration_routes": ["oral"],
            "design_modules": [
                "RANDOMIZED",
                "PLACEBO",
                "PARALLEL",
                "DOUBLE",
            ],
        }
        if layer_overrides:
            layer.update(layer_overrides)
        return {
            "schema_version": CORPUS_ANALYSIS_SCHEMA_VERSION,
            "analysis_id": envelope.payload["analysis_id"],
            "project_context_hash": envelope.payload[
                "project_context_hash"
            ],
            "findings": [
                {
                    "finding_id": "mwca_finding_cluster_a",
                    "module": "intervention",
                    "pattern_kind": "clinical_design_requirement",
                    "statement_zh": statement,
                    "transfer_scope": "same_indication",
                    "layer": layer,
                    "evidence_bindings": bindings,
                    "conflicts": [],
                    "unresolved_gaps": [],
                }
            ],
            "evidence_gaps": [],
            "global_conflicts": [],
        }

    return output


def test_composite_claim_must_exist_in_one_binding_or_fail_closed(tmp_path):
    """G1: numeric/route/frequency split across separate bindings cannot
    produce a high-confidence composite finding."""
    repository = _SplitEvidenceRepository(
        tmp_path / "writing_reference.sqlite3",
        span_texts=[
            "Rheumatoid Arthritis. PHASE2 proof-of-concept. "
            "JAK1 small_molecule tablet oral. RANDOMIZED PLACEBO PARALLEL "
            "DOUBLE. 100 mg.",
            "Rheumatoid Arthritis. PHASE2 dose escalation. "
            "JAK1 small_molecule tablet oral. RANDOMIZED PLACEBO PARALLEL "
            "DOUBLE. Subcutaneous injection every 4 weeks.",
        ],
    )
    provider = _Provider(
        _split_output_factory(
            statement=(
                "两份方案均采用100 mg皮下注射，每4周给药一次。"
            ),
            route_value="subcutaneous",
        )
    )
    service, _store = _service(tmp_path, repository, provider)

    result = service.analyze(
        project_id="proj_g1",
        pipeline_id="mwpipe_g1",
        snapshot_id="snapshot_g1",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=service.freeze_active_route(),
    )

    finding = result["analysis"]["findings"][0]
    assert finding["confidence"] != "high", (
        "G1: composite fact spread across separate bindings must not reach "
        "high confidence"
    )
    assert finding["support"]["high_confidence_eligible"] is False


def test_nonnumeric_route_modality_claim_must_match_bound_evidence(
    tmp_path, monkeypatch
):
    """G2: a nonnumeric dosage-form claim must require medical review when
    no single binding contains both forms.

    Strengthened: sponsor 1's evidence mentions ``tablet`` but not
    ``片剂``.  Sponsor 2 mentions ``片剂`` but not ``tablet``.  Both
    values individually survive sanitization and map to the same concept
    group ``tablet``, so neither binding is a counterexample and
    the pre-guard path reaches high confidence.  The single-binding
    co-observability guard is the only thing that blocks it.
    """
    repository = _SplitEvidenceRepository(
        tmp_path / "writing_reference.sqlite3",
        span_texts=[
            "Rheumatoid Arthritis. PHASE2 proof-of-concept and "
            "dose escalation. JAK1 small_molecule tablet oral. "
            "RANDOMIZED PLACEBO PARALLEL DOUBLE. "
            "The dosing interval was 12 weeks.",
            "Rheumatoid Arthritis. PHASE2 proof-of-concept and "
            "dose escalation. JAK1 small_molecule 片剂 oral. "
            "RANDOMIZED PLACEBO PARALLEL DOUBLE. "
            "The dosing interval was 12 weeks.",
        ],
    )

    def output(envelope):
        evidence = envelope.payload["evidence_catalog"]
        bindings = [
            {"evidence_id": item["evidence_id"]} for item in evidence
        ]
        return {
            "schema_version": CORPUS_ANALYSIS_SCHEMA_VERSION,
            "analysis_id": envelope.payload["analysis_id"],
            "project_context_hash": envelope.payload[
                "project_context_hash"
            ],
            "findings": [
                {
                    "finding_id": "mwca_finding_g2",
                    "module": "intervention",
                    "pattern_kind": "clinical_design_requirement",
                    "statement_zh": "两份方案均采用片剂。",
                    "transfer_scope": "same_indication",
                    "layer": {
                        "indications": list(
                            dict.fromkeys(
                                condition
                                for item in evidence
                                for condition in item["conditions"]
                            )
                        ),
                        "phases": ["PHASE2"],
                        "research_purposes": [
                            "proof-of-concept",
                            "dose escalation",
                        ],
                        "mechanisms": ["JAK1"],
                        "technology_types": ["small_molecule"],
                        "dosage_forms": ["tablet", "片剂"],
                        "administration_routes": ["oral"],
                        "design_modules": [
                            "RANDOMIZED",
                            "PLACEBO",
                            "PARALLEL",
                            "DOUBLE",
                        ],
                    },
                    "evidence_bindings": bindings,
                    "conflicts": [],
                    "unresolved_gaps": [],
                }
            ],
            "evidence_gaps": [],
            "global_conflicts": [],
        }

    provider = _Provider(output)
    service, _store = _service(tmp_path, repository, provider)

    frozen_route = service.freeze_active_route()

    # --- Counterfactual: bypass the guard and prove the pre-guard path
    # reaches high confidence. ---
    monkeypatch.setattr(
        MedicalWritingCorpusAnalysisAiService,
        "_single_binding_substantiates",
        staticmethod(lambda *a, **kw: True),
    )
    counter_result = service.analyze(
        project_id="proj_g2_counter",
        pipeline_id="mwpipe_g2",
        snapshot_id="snapshot_g2",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=frozen_route,
    )
    counter_finding = counter_result["analysis"]["findings"][0]
    assert counter_finding["confidence"] == "high", (
        "G2 counterfactual: with guard bypassed, the split-fact composite "
        "must reach high confidence to prove the test exercises the guard"
    )
    assert counter_finding["support"]["high_confidence_eligible"] is True

    # --- Real guard: undo the monkeypatch and prove it blocks high. ---
    monkeypatch.undo()
    result = service.analyze(
        project_id="proj_g2",
        pipeline_id="mwpipe_g2",
        snapshot_id="snapshot_g2",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=frozen_route,
    )
    finding = result["analysis"]["findings"][0]
    assert finding["confidence"] != "high", (
        "G2: dosage-form composite split across bindings must not reach "
        "high confidence"
    )
    assert finding["support"]["high_confidence_eligible"] is False
    assert (
        "single_binding_co_observability_not_met"
        in finding["support"]["reasons"]
    )
    # Sanity: sanitization did NOT strip the contested values.
    assert finding["layer"]["dosage_forms"] == ["tablet", "片剂"]
    assert finding["layer_rejections"] == []


def test_flat_layer_cannot_create_unobserved_axis_tuple(
    tmp_path, monkeypatch
):
    """G7: independently observed axis values cannot create an unobserved
    multi-axis tuple that no single binding supports.

    Strengthened: sponsor 1's evidence has ``tablet`` (dosage form) and
    ``proof-of-concept`` (research purpose), but not ``片剂`` or
    ``dose escalation``.  Sponsor 2 has ``片剂`` and
    ``dose escalation``, but not ``tablet`` or ``proof-of-concept``.
    All four values survive sanitization and each maps to a concept that
    intersects the target layer, so neither binding is a counterexample
    and the pre-guard path reaches high confidence.  But no single binding
    contains all four values, so the co-observability guard blocks high.
    """
    repository = _SplitEvidenceRepository(
        tmp_path / "writing_reference.sqlite3",
        span_texts=[
            "Rheumatoid Arthritis. PHASE2 proof-of-concept. "
            "JAK1 small_molecule tablet oral. "
            "RANDOMIZED PLACEBO PARALLEL DOUBLE. "
            "The dosing interval was 12 weeks.",
            "Rheumatoid Arthritis. PHASE2 dose escalation. "
            "JAK1 small_molecule 片剂 oral. "
            "RANDOMIZED PLACEBO PARALLEL DOUBLE. "
            "The dosing interval was 12 weeks.",
        ],
    )

    def output(envelope):
        evidence = envelope.payload["evidence_catalog"]
        bindings = [
            {"evidence_id": item["evidence_id"]} for item in evidence
        ]
        return {
            "schema_version": CORPUS_ANALYSIS_SCHEMA_VERSION,
            "analysis_id": envelope.payload["analysis_id"],
            "project_context_hash": envelope.payload[
                "project_context_hash"
            ],
            "findings": [
                {
                    "finding_id": "mwca_finding_g7",
                    "module": "intervention",
                    "pattern_kind": "clinical_design_requirement",
                    "statement_zh": "两份方案均采用片剂。",
                    "transfer_scope": "same_indication",
                    "layer": {
                        "indications": list(
                            dict.fromkeys(
                                condition
                                for item in evidence
                                for condition in item["conditions"]
                            )
                        ),
                        "phases": ["PHASE2"],
                        "research_purposes": [
                            "proof-of-concept",
                            "dose escalation",
                        ],
                        "mechanisms": ["JAK1"],
                        "technology_types": ["small_molecule"],
                        "dosage_forms": ["tablet", "片剂"],
                        "administration_routes": ["oral"],
                        "design_modules": [
                            "RANDOMIZED",
                            "PLACEBO",
                            "PARALLEL",
                            "DOUBLE",
                        ],
                    },
                    "evidence_bindings": bindings,
                    "conflicts": [],
                    "unresolved_gaps": [],
                }
            ],
            "evidence_gaps": [],
            "global_conflicts": [],
        }

    provider = _Provider(output)
    service, _store = _service(tmp_path, repository, provider)

    frozen_route = service.freeze_active_route()

    # --- Counterfactual: bypass the guard and prove the pre-guard path
    # reaches high confidence. ---
    monkeypatch.setattr(
        MedicalWritingCorpusAnalysisAiService,
        "_single_binding_substantiates",
        staticmethod(lambda *a, **kw: True),
    )
    counter_result = service.analyze(
        project_id="proj_g7_counter",
        pipeline_id="mwpipe_g7",
        snapshot_id="snapshot_g7",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=frozen_route,
    )
    counter_finding = counter_result["analysis"]["findings"][0]
    assert counter_finding["confidence"] == "high", (
        "G7 counterfactual: with guard bypassed, the cross-axis composite "
        "must reach high confidence to prove the test exercises the guard"
    )
    assert counter_finding["support"]["high_confidence_eligible"] is True

    # --- Real guard: undo the monkeypatch and prove it blocks high. ---
    monkeypatch.undo()
    result = service.analyze(
        project_id="proj_g7",
        pipeline_id="mwpipe_g7",
        snapshot_id="snapshot_g7",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=frozen_route,
    )
    finding = result["analysis"]["findings"][0]
    assert finding["confidence"] != "high", (
        "G7: cross-axis composite with no single-binding co-observability "
        "must not reach high confidence"
    )
    assert finding["support"]["high_confidence_eligible"] is False
    assert (
        "single_binding_co_observability_not_met"
        in finding["support"]["reasons"]
    )
    # Sanity: sanitization did NOT strip the contested values.
    assert finding["layer"]["dosage_forms"] == ["tablet", "片剂"]
    assert finding["layer"]["research_purposes"] == [
        "proof-of-concept",
        "dose escalation",
    ]
    assert finding["layer_rejections"] == []


# ---------------------------------------------------------------------------
# Cluster C negative tests (G8/G9) — indication alignment integrity
# ---------------------------------------------------------------------------


def _basket_output_factory(*, source_conditions: list[str], project_term: str):
    """Build AI output for a multi-condition (basket) artifact where the
    candidate-level conditions include the target indication but the
    individual evidence spans only support a different indication."""

    def output(envelope):
        evidence = envelope.payload["evidence_catalog"]
        bindings = [
            {"evidence_id": item["evidence_id"]} for item in evidence
        ]
        layer = {
            "indications": list(source_conditions),
            "phases": ["PHASE2"],
            "research_purposes": [
                "proof-of-concept",
                "dose escalation",
            ],
            "mechanisms": ["JAK1"],
            "technology_types": ["small_molecule"],
            "dosage_forms": ["tablet"],
            "administration_routes": ["oral"],
            "design_modules": [
                "RANDOMIZED",
                "PLACEBO",
                "PARALLEL",
                "DOUBLE",
            ],
        }
        return {
            "schema_version": CORPUS_ANALYSIS_SCHEMA_VERSION,
            "analysis_id": envelope.payload["analysis_id"],
            "project_context_hash": envelope.payload[
                "project_context_hash"
            ],
            "findings": [
                {
                    "finding_id": "mwca_finding_g8",
                    "module": "intervention",
                    "pattern_kind": "clinical_design_requirement",
                    "statement_zh": (
                        "两份方案均采用12周给药间隔。"
                    ),
                    "transfer_scope": "same_indication",
                    "layer": layer,
                    "evidence_bindings": bindings,
                    "conflicts": [],
                    "unresolved_gaps": [],
                }
            ],
            "evidence_gaps": [],
            "global_conflicts": [],
        }

    return output


class _BasketRepository(_Repository):
    """Repository where the candidate (artifact-level) conditions list
    multiple indications, but each sponsor's evidence text only describes
    a *different* indication than the target."""

    def __init__(
        self,
        db_path: Path,
        *,
        artifact_conditions: list[str],
        span_texts: list[str],
    ):
        super().__init__(
            db_path,
            sponsor_count=len(span_texts),
            candidate_condition="; ".join(artifact_conditions),
        )
        # Override candidate conditions to be the basket list.
        for index, candidate in enumerate(self._candidates):
            candidate.conditions = list(artifact_conditions)
            original_dump = candidate.model_dump

            def make_dump(conditions, index):
                def dump(mode="json"):
                    base = original_dump(mode) if callable(original_dump) else {}
                    base["conditions"] = list(conditions)
                    base["nct_id"] = f"NCT0000000{index + 1}"
                    base["phases"] = ["PHASE2"]
                    base["lead_sponsor"] = f"Sponsor {index + 1}"
                    return base
                return dump

            candidate.model_dump = make_dump(artifact_conditions, index)
            candidate_payload = {
                "nct_id": f"NCT0000000{index + 1}",
                "conditions": list(artifact_conditions),
                "phases": ["PHASE2"],
                "lead_sponsor": f"Sponsor {index + 1}",
                "interventions": [
                    {
                        "name": f"Drug {index + 1}",
                        "intervention_type": "DRUG",
                    }
                ],
                "design_allocation": "RANDOMIZED",
                "design_intervention_model": "PARALLEL",
                "design_masking": "DOUBLE",
            }
        # Override spans.
        for index, text in enumerate(span_texts):
            artifact_id = f"artifact_{index + 1}"
            span_id = f"span_{index + 1}"
            self._spans[artifact_id] = [
                SimpleNamespace(
                    span_id=span_id,
                    source_text=text,
                    source_text_sha256=(str(index + 3) * 64)[:64],
                    source_locator=f"page:{index + 5}",
                    physical_page=index + 5,
                    block_index=1,
                    section_heading="Study intervention",
                    ich_m11_anchor="intervention",
                )
            ]


def test_multicondition_basket_span_cannot_borrow_target_condition(
    tmp_path, monkeypatch
):
    """G8: a multi-condition/basket artifact's conditions must not lend the
    target indication to a span or cohort whose bound text only supports
    a different indication.

    Setup: project target is Rheumatoid Arthritis.  The artifact-level
    candidate conditions include both 'Rheumatoid Arthritis' and
    'Atopic Dermatitis' (basket trial).  But each sponsor's actual evidence
    text only mentions Atopic Dermatitis.

    Counterfactual: with the Cluster A co-observability guard bypassed
    (monkeypatched to True), the finding reaches high confidence in the
    pre-G8-fix code because ``_source_layer_for_evidence`` copies
    artifact-level ``evidence["conditions"]`` (which include RA) into the
    span's source layer, so the indication axis matches the target.  The
    G8 fix prevents this artifact-level condition leaking.
    """
    repository = _BasketRepository(
        tmp_path / "writing_reference.sqlite3",
        artifact_conditions=[
            "Rheumatoid Arthritis",
            "Atopic Dermatitis",
        ],
        span_texts=[
            "Atopic Dermatitis. PHASE2 proof-of-concept and "
            "dose escalation. JAK1 small_molecule tablet oral. "
            "RANDOMIZED PLACEBO PARALLEL DOUBLE. "
            "The dosing interval was 12 weeks.",
            "Atopic Dermatitis. PHASE2 proof-of-concept and "
            "dose escalation. JAK1 small_molecule tablet oral. "
            "RANDOMIZED PLACEBO PARALLEL DOUBLE. "
            "The dosing interval was 12 weeks.",
        ],
    )
    provider = _Provider(
        _basket_output_factory(
            source_conditions=[
                "Rheumatoid Arthritis",
                "Atopic Dermatitis",
            ],
            project_term="Rheumatoid Arthritis",
        )
    )
    service, _store = _service(tmp_path, repository, provider)
    frozen_route = service.freeze_active_route()

    # --- Counterfactual: bypass the Cluster A co-observability guard and
    # prove the pre-G8-fix code reaches high confidence because the
    # artifact-level RA condition leaks into the span source layer. ---
    monkeypatch.setattr(
        MedicalWritingCorpusAnalysisAiService,
        "_single_binding_substantiates",
        staticmethod(lambda *a, **kw: True),
    )
    counter_result = service.analyze(
        project_id="proj_g8_counter",
        pipeline_id="mwpipe_g8",
        snapshot_id="snapshot_g8",
        journey=_journey(),
        actor="medical_manager",
        frozen_route=frozen_route,
    )
    counter_finding = counter_result["analysis"]["findings"][0]
    # The span text only mentions "Atopic Dermatitis" — the project target
    # is RA.  After the G8 fix, the source layer should NOT include RA,
    # so the indication axis mismatches and this should NOT be high.
    # Pre-fix: it IS high (the bug).
    # Post-fix: it is NOT high (the fix prevents condition leaking).
    assert counter_finding["confidence"] != "high", (
        "G8: basket artifact must not lend an unrelated condition to a span "
        "whose bound evidence only supports a different indication"
    )
    assert counter_finding["support"]["high_confidence_eligible"] is False

    monkeypatch.undo()


@pytest.mark.parametrize(
    "source_condition,target_condition",
    [
        # 慢性鼻窦炎 (chronic rhinosinusitis) vs 慢性鼻窦炎伴鼻息肉 (CRSwNP)
        ("慢性鼻窦炎", "慢性鼻窦炎伴鼻息肉"),
        ("慢性鼻窦炎伴鼻息肉", "慢性鼻窦炎"),
        # asthma vs severe eosinophilic asthma
        ("asthma", "severe eosinophilic asthma"),
        ("severe eosinophilic asthma", "asthma"),
    ],
)
def test_broader_and_narrower_indications_require_confirmation(
    source_condition, target_condition
):
    """G9 (AI locus): ``_candidate_indication_relation`` must NOT verify
    'same' merely because one indication name is a substring of the other.
    Broader/narrower disease names must fall through to unresolved /
    pending_medical_confirmation, not verified_same.
    """
    alignment = _candidate_indication_relation(
        [target_condition],
        [source_condition],
    )
    assert alignment["status"] != "verified_same", (
        f"G9 AI: '{source_condition}' vs '{target_condition}' must not be "
        f"verified_same by substring containment alone"
    )
    assert alignment["relation"] != "same", (
        f"G9 AI: '{source_condition}' vs '{target_condition}' must not "
        f"establish 'same' relation by substring containment alone"
    )
    assert alignment["status"] in (
        "pending_medical_confirmation",
        "verified_controlled_alias",
    ), (
        f"G9 AI: '{source_condition}' vs '{target_condition}' must resolve "
        f"to pending_medical_confirmation or verified_controlled_alias, "
        f"got {alignment['status']}"
    )


@pytest.mark.parametrize(
    "source_indication,target_indication",
    [
        # 慢性鼻窦炎 (broader) vs 慢性鼻窦炎伴鼻息肉 (narrower)
        ("慢性鼻窦炎", "慢性鼻窦炎伴鼻息肉"),
        ("慢性鼻窦炎伴鼻息肉", "慢性鼻窦炎"),
        # asthma (broader) vs severe eosinophilic asthma (narrower)
        ("asthma", "severe eosinophilic asthma"),
        ("severe eosinophilic asthma", "asthma"),
    ],
)
def test_policy_side_substring_gate_closes_independently_of_ai_relation(
    source_indication, target_indication
):
    """G9 (policy locus): ``_layer_mismatches`` indication axis must NOT
    treat source/target indications as matching merely because one is a
    substring of the other.

    This test is specifically designed to fail if only the AI-side
    ``_candidate_indication_relation`` is fixed — it exercises the
    policy-side ``_layer_mismatches`` gate independently.
    """
    from services.api.app.medical_writing_corpus_policy import (
        _layer_mismatches,
    )

    profile_layer = {"indication": (source_indication,)}
    target_layer = {"indication": (target_indication,)}
    mismatches, _missing = _layer_mismatches(profile_layer, target_layer)
    assert "indication" in mismatches, (
        f"G9 policy: '{source_indication}' must NOT match "
        f"'{target_indication}' in _layer_mismatches by substring "
        f"containment alone"
    )


def test_span_alias_expansion_requires_acronym_token_boundary():
    """Cluster C: letters embedded in another token cannot prove PNH."""
    source_layer = MedicalWritingCorpusAnalysisAiService._source_layer_for_evidence(
        {"indications": ["阵发性睡眠性血红蛋白尿症"]},
        {
            "evidence_text": (
                "The exploratory marker XPNHY was measured in an asthma cohort."
            ),
            "conditions": [
                "Paroxysmal Nocturnal Hemoglobinuria",
                "Asthma",
            ],
            "phases": ["PHASE2"],
            "interventions": [],
            "design": {},
        },
    )

    assert "pnh" not in {
        value.casefold() for value in source_layer["indications"]
    }
    assert "阵发性睡眠性血红蛋白尿症" not in source_layer["indications"]


@pytest.mark.parametrize(
    "source_condition",
    [
        "Rheumatoid Arthritis",
        "RA",
    ],
)
def test_ra_uses_versioned_controlled_cross_language_alias(source_condition):
    """G10: a registered non-PNH disease may prove name equivalence."""
    alignment = _candidate_indication_relation(
        ["类风湿关节炎"],
        [source_condition],
    )

    assert INDICATION_ALIGNMENT_POLICY_VERSION == (
        "controlled_indication_aliases_v2"
    )
    assert alignment["relation"] == "same_controlled_alias"
    assert alignment["status"] == "verified_controlled_alias"
    assert alignment["concept_id"] == "rheumatoid_arthritis"
    assert alignment["policy_version"] == INDICATION_ALIGNMENT_POLICY_VERSION


@pytest.mark.parametrize(
    "project_indication,source_condition",
    [
        ("特应性皮炎", "Atopic Dermatitis"),
        (
            "慢性鼻窦炎伴鼻息肉",
            "Chronic Rhinosinusitis with Nasal Polyps",
        ),
        ("慢性自发性荨麻疹", "Chronic Spontaneous Urticaria"),
    ],
)
def test_unregistered_cross_language_alias_remains_pending(
    project_indication,
    source_condition,
):
    """G10: model translation cannot silently expand the controlled registry."""
    alignment = _candidate_indication_relation(
        [project_indication],
        [source_condition],
    )

    assert alignment["relation"] == "unresolved_cross_language"
    assert alignment["status"] == "pending_medical_confirmation"
    assert alignment["proof_type"].startswith("cross_language_")
    assert "concept_id" not in alignment


def test_controlled_alias_does_not_prove_phase_route_or_design_equivalence():
    """G10: disease-name proof leaves all other transfer axes independent."""
    from services.api.app.medical_writing_corpus_policy import (
        assess_corpus_support,
    )

    source_layer = (
        MedicalWritingCorpusAnalysisAiService._source_layer_for_evidence(
            {
                "indications": ["类风湿关节炎"],
                "phases": ["PHASE3"],
                "research_purposes": ["confirmatory"],
                "mechanisms": ["JAK inhibition"],
                "technology_types": ["small molecule"],
                "dosage_forms": ["injection"],
                "administration_routes": ["intravenous"],
                "design_modules": ["open-label"],
            },
            {
                "evidence_text": (
                    "Rheumatoid Arthritis Phase III confirmatory JAK "
                    "inhibition small molecule injection intravenous "
                    "open-label study."
                ),
                "conditions": ["Rheumatoid Arthritis"],
                "phases": ["PHASE3"],
                "interventions": [
                    {
                        "name": "small molecule injection",
                        "route": "intravenous",
                    }
                ],
                "design": {"masking": "open-label"},
            },
        )
    )
    assessment = assess_corpus_support(
        [
            {
                "source_id": "ra_phase3_iv_open",
                "source_file": "ra_phase3_iv_open.docx",
                "lead_sponsor": "Sponsor A",
                "pattern_kind": "clinical_design_requirement",
                "claim_value": "The study uses an open-label intravenous design.",
                "layer": source_layer,
            }
        ],
        pattern_kind="clinical_design_requirement",
        target_layer={
            "indication": "类风湿关节炎",
            "phase": "II期",
            "research_purpose": "概念验证",
            "mechanism": "JAK inhibition",
            "technology_type": "small molecule",
            "dosage_form": "tablet",
            "administration_route": "oral",
            "design_module": "randomized double-blind placebo-controlled",
        },
    )

    assert assessment.counterexamples
    reason = assessment.counterexamples[0]["reason"]
    assert "indication" not in reason
    assert "phase" in reason
    assert "dosage_form" in reason
    assert "administration_route" in reason
    assert "design_module" in reason


def test_controlled_acronym_requires_matching_artifact_condition():
    """G10: a standalone RA token cannot relabel an unrelated condition."""
    source_layer = MedicalWritingCorpusAnalysisAiService._source_layer_for_evidence(
        {"indications": ["RA", "类风湿关节炎"]},
        {
            "evidence_text": (
                "RA was used as an internal randomization abbreviation."
            ),
            "conditions": ["Asthma"],
            "phases": ["PHASE2"],
            "interventions": [],
            "design": {},
        },
    )

    assert "类风湿关节炎" not in source_layer["indications"]
    assert "rheumatoid arthritis" not in {
        value.casefold() for value in source_layer["indications"]
    }
    assert "ra" not in {
        value.casefold() for value in source_layer["indications"]
    }
    assert all(
        "generator object" not in value
        for value in source_layer["indications"]
    )


def test_combined_study_phase_is_not_inherited_without_span_part_binding():
    """G6: artifact phases do not establish a span's Part membership."""
    source_layer = MedicalWritingCorpusAnalysisAiService._source_layer_for_evidence(
        {"phases": ["PHASE2"]},
        {
            "evidence_text": "The primary objective is to assess efficacy.",
            "conditions": ["Rheumatoid Arthritis"],
            "phases": ["PHASE1", "PHASE2"],
            "interventions": [],
            "design": {},
        },
    )

    assert source_layer["phases"] == []


def test_combined_study_phase_uses_only_phase_explicitly_bound_to_span():
    """G6 positive: an explicit Phase II span may support the Phase II Part."""
    source_layer = MedicalWritingCorpusAnalysisAiService._source_layer_for_evidence(
        {"phases": ["PHASE2"]},
        {
            "evidence_text": (
                "In the Phase II Part, the primary objective is to assess "
                "efficacy."
            ),
            "conditions": ["Rheumatoid Arthritis"],
            "phases": ["PHASE1", "PHASE2"],
            "interventions": [],
            "design": {},
        },
    )

    assert source_layer["phases"] == ["PHASE2"]


def test_combined_phase_span_preserves_combined_framework_not_single_part():
    """G6: an explicit Phase I/II span remains a combined-phase binding."""
    source_layer = MedicalWritingCorpusAnalysisAiService._source_layer_for_evidence(
        {"phases": ["Phase I/II"]},
        {
            "evidence_text": (
                "This Phase I/II study includes dose escalation and "
                "proof-of-concept Parts."
            ),
            "conditions": ["Rheumatoid Arthritis"],
            "phases": ["PHASE1", "PHASE2"],
            "interventions": [],
            "design": {},
        },
    )

    assert source_layer["phases"] == ["PHASE1/2"]
