from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.api.app.monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiClaim,
    MonitoringAiClaimKind,
    MonitoringAiEvidence,
    MonitoringAiInputRevision,
    MonitoringAiJobCreate,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
)
from services.api.app.monitoring_ai_repository import MonitoringAiRepository
from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
    RulePackRevisionConflictError,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_protocol_rules import ProtocolFact
from services.api.app.monitoring_rule_authoring_service import (
    MonitoringRuleAuthoringError,
    MonitoringRuleAuthoringService,
)
from services.api.app.monitoring_rule_lifecycle_service import (
    MonitoringRuleLifecycleService,
)
from tests.test_monitoring_rule_templates import _symbolic_template
from tests.test_monitoring_protocol_rules import _store_p7c_release_evidence


PROJECT = "project-alpha"
OTHER_PROJECT = "project-beta"
PROTOCOL_ENTRY = "source-protocol"
LISTING_ENTRY = "source-listing"
PROTOCOL_HASH = "b" * 64
LISTING_HASH = "a" * 64


class FakeSourceRegistry:
    def __init__(self):
        self.entries = {
            PROJECT: [
                SimpleNamespace(
                    entry_id=PROTOCOL_ENTRY,
                    project_id=PROJECT,
                    module="medical_monitoring",
                    source_kind="protocol_docx",
                    public_title="项目研究方案 V1.0",
                    content_hash=PROTOCOL_HASH,
                    parser_status="parsed",
                ),
                SimpleNamespace(
                    entry_id=LISTING_ENTRY,
                    project_id=PROJECT,
                    module="medical_monitoring",
                    source_kind="edc_data_listing",
                    public_title="EDC Data Listing",
                    content_hash=LISTING_HASH,
                    parser_status="parsed",
                ),
            ],
            OTHER_PROJECT: [],
        }

    def list_entries(self, project_id: str):
        return list(self.entries.get(project_id, ()))

    def current_content_validation(self, project_id: str, source_entry_id: str):
        entry = next(
            (
                item
                for item in self.entries.get(project_id, ())
                if item.entry_id == source_entry_id
            ),
            None,
        )
        if entry is None:
            return None
        return SimpleNamespace(
            technical_status="ready",
            use_status="allowed",
            file_sha256=entry.content_hash,
        )


def _accepted_candidate(
    repository: MonitoringAiRepository,
    *,
    project_id: str = PROJECT,
    accepted: bool = True,
) -> MonitoringAiCandidate:
    revision = MonitoringAiInputRevision(
        project_id=project_id,
        protocol_version="protocol-v1",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id=PROTOCOL_ENTRY,
                source_content_sha256=PROTOCOL_HASH,
            ),
        ),
    )
    request = MonitoringAiJobCreate(
        project_id=project_id,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=revision,
        input_payload={"source_ids": [PROTOCOL_ENTRY]},
        prompt_version="monitoring-protocol-clause-v1",
        profile_id="independent-ai-test",
        provider="test-provider",
        requested_model="test-model",
        business_key="protocol-clause-001",
    )
    repository.create_or_get(request)
    job = repository.claim_next("worker")
    assert job is not None
    unrelated_evidence = MonitoringAiEvidence(
        evidence_id="evidence-protocol-unrelated",
        source_entry_id=PROTOCOL_ENTRY,
        source_content_sha256=PROTOCOL_HASH,
        locator="docx:paragraph:20",
        quote="本段为与当前条款无关的方案背景。",
        input_revision_sha256=job.input_revision_sha256,
    )
    evidence = MonitoringAiEvidence(
        evidence_id="evidence-protocol-001",
        source_entry_id=PROTOCOL_ENTRY,
        source_content_sha256=PROTOCOL_HASH,
        locator="docx:paragraph:120",
        quote="受试者每次访视均应完成规定的数据完整性核对。",
        input_revision_sha256=job.input_revision_sha256,
    )
    candidate = MonitoringAiCandidate(
        candidate_id=f"candidate-{project_id}",
        job_id=job.job_id,
        project_id=project_id,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        candidate_type="protocol_clause",
        title="访视数据完整性条款",
        text="结构化候选仅供医学经理确认。",
        structured_payload={
            "clause_id": "12.1",
            "evidence_ids": [evidence.evidence_id],
        },
        claims=(
            MonitoringAiClaim(
                claim_id="claim-001",
                kind=MonitoringAiClaimKind.FACT,
                text="方案规定每次访视进行数据完整性核对。",
                confidence=0.95,
                evidence_ids=(evidence.evidence_id,),
            ),
        ),
        evidence=(unrelated_evidence, evidence),
        input_revision_sha256=job.input_revision_sha256,
        prompt_version=job.prompt_version,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    repository.record_attempt(
        job,
        owner="worker",
        request_payload={"task": "protocol clause"},
        response_payload={"candidates": [candidate.model_dump(mode="json")]},
        response_model="test-model",
        outcome="success",
    )
    repository.complete(
        job,
        owner="worker",
        response_model="test-model",
        raw_output={"candidates": [candidate.model_dump(mode="json")]},
        candidates=(candidate,),
    )
    if accepted:
        return repository.decide_candidate(
            project_id,
            candidate.candidate_id,
            decision=MonitoringAiCandidateStatus.ACCEPTED,
            actor="medical_manager",
            reason="原文与结构化候选一致。",
            current_input_revision_sha256=job.input_revision_sha256,
        )
    return repository.candidates(project_id, job.job_id)[0]


@pytest.fixture()
def authoring(tmp_path: Path):
    rule_repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    rule_repository.bind_gold_case_authority(lambda _case, _rule: None)
    ai_repository = MonitoringAiRepository(tmp_path / "ai.sqlite3")
    protocol_service = MonitoringProtocolRuleService(rule_repository)
    service = MonitoringRuleAuthoringService(
        repository=rule_repository,
        lifecycle_service=MonitoringRuleLifecycleService(
            rule_repository,
            clock=lambda: "2026-07-29T10:00:00+00:00",
        ),
        protocol_rule_service=protocol_service,
        ai_repository=ai_repository,
        source_registry=FakeSourceRegistry(),
    )
    return service, rule_repository, ai_repository


def _version(service: MonitoringRuleAuthoringService):
    return service.register_protocol_version(
        project_id=PROJECT,
        source_entry_id=PROTOCOL_ENTRY,
        protocol_code="PROTO-001",
        version_label="V1.0",
        version_date="2026-07-01",
        applicability_status="project_effective_confirmed",
        operational_effective_from="2026-07-15",
    )[0]


def _template():
    template = _symbolic_template(
        family="data_quality",
        rule_key="visit_data_completeness",
        executor="field_predicate",
        required_domains=("LB",),
        fields={"review_flag": ("REVIEW_FLAG", "LB")},
        trigger={"eq": {"field_role": "review_flag", "value": "CHECK"}},
        title="访视数据完整性核对",
    )
    template["immutable_identity"] = {
        "mapping_revision": "mapping-v1",
        "mapping_content_sha256": "2" * 64,
        "capability_manifest_sha256": "5" * 64,
        "effective_capabilities_sha256": "6" * 64,
        "recommendation_candidate_id": "candidate-001",
    }
    return template


def _confirmed_fact(
    service: MonitoringRuleAuthoringService,
    ai_repository: MonitoringAiRepository,
):
    version = _version(service)
    candidate = _accepted_candidate(ai_repository)
    adopted, _ = service.adopt_ai_candidate(
        project_id=PROJECT,
        protocol_version_id=version.protocol_version_id,
        candidate_id=candidate.candidate_id,
        fact_key="visit_data_completeness",
        proposed_fact_type="data_quality",
    )
    fact, rule = service.confirm_fact_and_compile(
        project_id=PROJECT,
        fact_revision_id=adopted.fact_revision_id,
        expected_state_version=adopted.state_version,
        fact_type="data_quality",
        deterministic_template=_template(),
        confirmed_by="medical_manager",
    )
    return version, fact, rule


def test_rejects_cross_project_and_unaccepted_candidates(authoring) -> None:
    service, _rule_repository, ai_repository = authoring
    version = _version(service)
    accepted = _accepted_candidate(ai_repository)

    with pytest.raises(
        MonitoringRuleAuthoringError,
        match="当前项目未找到该方案版本",
    ):
        service.adopt_ai_candidate(
            project_id=OTHER_PROJECT,
            protocol_version_id=version.protocol_version_id,
            candidate_id=accepted.candidate_id,
            fact_key="cross-project",
            proposed_fact_type="data_quality",
        )

    other_repository = MonitoringAiRepository(
        ai_repository.path.parent / "unaccepted.sqlite3"
    )
    proposed = _accepted_candidate(other_repository, accepted=False)
    other_service = MonitoringRuleAuthoringService(
        repository=service.repository,
        lifecycle_service=service.lifecycle_service,
        protocol_rule_service=service.protocol_rule_service,
        ai_repository=other_repository,
        source_registry=service.source_registry,
    )
    with pytest.raises(
        MonitoringRuleAuthoringError,
        match="仅已接受且已完成",
    ):
        other_service.adopt_ai_candidate(
            project_id=PROJECT,
            protocol_version_id=version.protocol_version_id,
            candidate_id=proposed.candidate_id,
            fact_key="unaccepted",
            proposed_fact_type="data_quality",
        )


def test_duplicate_adoption_reuses_and_stale_confirmation_fails(authoring) -> None:
    service, repository, ai_repository = authoring
    version = _version(service)
    candidate = _accepted_candidate(ai_repository)
    first, reused = service.adopt_ai_candidate(
        project_id=PROJECT,
        protocol_version_id=version.protocol_version_id,
        candidate_id=candidate.candidate_id,
        fact_key="visit_data_completeness",
        proposed_fact_type="data_quality",
    )
    second, reused_second = service.adopt_ai_candidate(
        project_id=PROJECT,
        protocol_version_id=version.protocol_version_id,
        candidate_id=candidate.candidate_id,
        fact_key="visit_data_completeness",
        proposed_fact_type="data_quality",
    )
    assert reused is False
    assert reused_second is True
    assert first.fact_revision_id == second.fact_revision_id
    assert len(repository.facts_for_version(version.protocol_version_id)) == 1
    assert first.source_locator == "docx:paragraph:120"
    assert first.source_text == (
        "受试者每次访视均应完成规定的数据完整性核对。"
    )

    with pytest.raises(MonitoringRuleAuthoringError, match="已被其他操作更新"):
        service.confirm_fact_and_compile(
            project_id=PROJECT,
            fact_revision_id=first.fact_revision_id,
            expected_state_version=99,
            fact_type="data_quality",
            deterministic_template=_template(),
            confirmed_by="medical_manager",
        )
    assert len(repository.facts_for_version(version.protocol_version_id)) == 1


def test_adoption_repairs_legacy_wrong_primary_evidence(authoring) -> None:
    service, repository, ai_repository = authoring
    version = _version(service)
    candidate = _accepted_candidate(ai_repository)
    legacy = ProtocolFact.create(
        project_id=PROJECT,
        protocol_version_id=version.protocol_version_id,
        fact_key="visit_data_completeness",
        fact_type="data_quality",
        status="ai_candidate",
        title="访视数据完整性条款",
        normalized_payload={
            "ai_candidate": candidate.model_dump(mode="json"),
        },
        source_entry_id=PROTOCOL_ENTRY,
        source_locator="docx:paragraph:20",
        source_text="本段为与当前条款无关的方案背景。",
    )
    legacy = repository.store_fact(legacy)

    corrected, reused = service.adopt_ai_candidate(
        project_id=PROJECT,
        protocol_version_id=version.protocol_version_id,
        candidate_id=candidate.candidate_id,
        fact_key="visit_data_completeness",
        proposed_fact_type="data_quality",
    )

    assert reused is False
    assert corrected.supersedes_fact_revision_id == legacy.fact_revision_id
    assert corrected.source_locator == "docx:paragraph:120"
    assert corrected.source_text == (
        "受试者每次访视均应完成规定的数据完整性核对。"
    )
    legacy_after = next(
        item
        for item in repository.facts_for_version(version.protocol_version_id)
        if item.fact_revision_id == legacy.fact_revision_id
    )
    assert legacy_after.status == "superseded"


def test_direct_publish_and_shadow_without_gold_cases_fail(authoring) -> None:
    service, _repository, ai_repository = authoring
    version, fact, _ = _confirmed_fact(service, ai_repository)
    draft = service.create_draft(
        project_id=PROJECT,
        protocol_version_id=version.protocol_version_id,
        fact_revision_ids=[fact.fact_revision_id],
        created_by="medical_manager",
    )
    with pytest.raises(MonitoringRuleAuthoringError, match="状态不允许"):
        service.publish(
            project_id=PROJECT,
            rule_pack_id=draft.rule_pack_id,
            published_by="medical_manager",
        )
    shadow = service.start_shadow(
        project_id=PROJECT,
        rule_pack_id=draft.rule_pack_id,
        started_by="medical_manager",
    )
    with pytest.raises(ValueError, match="requires gold standard cases"):
        service.run_shadow(
            project_id=PROJECT,
            rule_pack_id=shadow.rule_pack_id,
            batch_id="shadow-batch",
        )


def test_complete_strict_lifecycle_succeeds(authoring) -> None:
    service, repository, ai_repository = authoring
    version, fact, _ = _confirmed_fact(service, ai_repository)
    with pytest.raises(
        MonitoringRuleAuthoringError,
        match="已经完成确认",
    ):
        service.adopt_ai_candidate(
            project_id=PROJECT,
            protocol_version_id=version.protocol_version_id,
            candidate_id=f"candidate-{PROJECT}",
            fact_key="visit_data_completeness",
            proposed_fact_type="data_quality",
        )
    draft = service.create_draft(
        project_id=PROJECT,
        protocol_version_id=version.protocol_version_id,
        fact_revision_ids=[fact.fact_revision_id],
        created_by="medical_manager",
    )
    _, rules = repository.rule_pack(draft.rule_pack_id)
    rule = rules[0]
    assert rule.status == "confirmed"
    shadow = service.start_shadow(
        project_id=PROJECT,
        rule_pack_id=draft.rule_pack_id,
        started_by="medical_manager",
    )
    locator = f"listing:{LISTING_HASH}:sheet:LB:row:2"
    case = service.register_gold_case(
        project_id=PROJECT,
        rule_pack_id=shadow.rule_pack_id,
        rule_revision_id=rule.rule_revision_id,
        source_entry_id=LISTING_ENTRY,
        source_revision="source-revision-1",
        batch_revision="batch-revision-1",
        case_label="访视数据完整性阳性核对案例",
        input_record={
            "SUBJID": "001",
            "REVIEW_FLAG": "CHECK",
            "__source_locator__": locator,
        },
        observed_domains=["LB"],
        expected_match=True,
        medical_rationale="真实 listing 行满足确定性条件。",
        evidence_locators=[locator],
        source_row_bindings=[
            {
                "business_key": "SUBJID=001|LB|row=2",
                "domain": "LB",
                "source_locator": locator,
                "row_fingerprint": "c" * 64,
                "record_roles": ["current"],
                "field_bindings": [
                    {
                        "record_role": "current",
                        "record_field": "SUBJID",
                        "source_field": "SUBJID",
                    },
                    {
                        "record_role": "current",
                        "record_field": "REVIEW_FLAG",
                        "source_field": "REVIEW_FLAG",
                    },
                ],
            }
        ],
    )
    assert case.rule_revision_id == rule.rule_revision_id
    _store_p7c_release_evidence(repository, [rule])
    run = service.run_shadow(
        project_id=PROJECT,
        rule_pack_id=shadow.rule_pack_id,
        batch_id="shadow-batch",
    )
    assert run.failed_count == 0
    confirmed_pack = service.confirm_shadow(
        project_id=PROJECT,
        rule_pack_id=shadow.rule_pack_id,
        shadow_run_id=run.shadow_run_id,
        confirmed_by="medical_manager",
    ).pack
    published = service.publish(
        project_id=PROJECT,
        rule_pack_id=confirmed_pack.rule_pack_id,
        published_by="medical_manager",
    )
    assert published.status == "published"
    current, current_rules = repository.current_published_pack(
        PROJECT,
        as_of="2026-07-29",
    )
    assert current.rule_pack_id == published.rule_pack_id
    assert current_rules[0].status == "enabled"


def test_applicability_authoring_requires_traceable_interval_and_is_project_isolated(
    authoring,
) -> None:
    service, repository, _ai_repository = authoring
    version = service.register_protocol_version(
        project_id=PROJECT,
        source_entry_id=PROTOCOL_ENTRY,
        protocol_code="PROTO-001",
        version_label="V2.0",
        version_date="2026-07-20",
        applicability_status="site_specific",
        operational_effective_from="",
    )[0]

    with pytest.raises(ValueError, match="operational_effective_to is required"):
        service.create_applicability_assignment(
            project_id=PROJECT,
            protocol_version_id=version.protocol_version_id,
            centre_id="001",
            subject_id="0007",
            operational_effective_from="2026-07-21",
            operational_effective_to="",
            evidence_text="中心确认方案已投入执行。",
            evidence_source_entry_id=PROTOCOL_ENTRY,
            evidence_locator="docx:paragraph:150",
            created_by="medical_manager",
        )
    with pytest.raises(ValueError, match="evidence_text is required"):
        service.create_applicability_assignment(
            project_id=PROJECT,
            protocol_version_id=version.protocol_version_id,
            centre_id="001",
            subject_id="0007",
            operational_effective_from="2026-07-21",
            operational_effective_to="2026-12-31",
            evidence_text="",
            evidence_source_entry_id=PROTOCOL_ENTRY,
            evidence_locator="docx:paragraph:150",
            created_by="medical_manager",
        )

    candidate, reused = service.create_applicability_assignment(
        project_id=PROJECT,
        protocol_version_id=version.protocol_version_id,
        centre_id="001",
        subject_id="0007",
        operational_effective_from="2026-07-21",
        operational_effective_to="2026-12-31",
        evidence_text="中心确认方案已投入执行。",
        evidence_source_entry_id=PROTOCOL_ENTRY,
        evidence_locator="docx:paragraph:150",
        created_by="medical_manager",
    )
    assert reused is False
    assert candidate.centre_id == "001"
    assert candidate.subject_id == "0007"
    confirmed = service.confirm_applicability_assignment(
        project_id=PROJECT,
        assignment_id=candidate.assignment_id,
        expected_state_version=1,
        confirmed_by="medical_manager",
    )
    assert confirmed.status == "confirmed"
    assert repository.resolve_protocol_applicability(
        PROJECT,
        centre_id="001",
        subject_id="0007",
        event_date="2026-07-22",
    ).protocol_version_id == version.protocol_version_id
    with pytest.raises(
        MonitoringRuleAuthoringError,
        match="当前项目未找到该方案版本",
    ):
        service.create_applicability_assignment(
            project_id=OTHER_PROJECT,
            protocol_version_id=version.protocol_version_id,
            centre_id="001",
            operational_effective_from="2026-07-21",
            operational_effective_to="2026-12-31",
            evidence_text="不得跨项目写入。",
            evidence_source_entry_id=PROTOCOL_ENTRY,
            evidence_locator="docx:paragraph:150",
            created_by="medical_manager",
        )


def test_legacy_confirmation_without_identity_fails_closed(authoring) -> None:
    service, _repository, ai_repository = authoring
    version = _version(service)
    candidate = _accepted_candidate(ai_repository)
    adopted, _ = service.adopt_ai_candidate(
        project_id=PROJECT,
        protocol_version_id=version.protocol_version_id,
        candidate_id=candidate.candidate_id,
        fact_key="visit_data_completeness",
        proposed_fact_type="data_quality",
    )
    template = _template()
    del template["immutable_identity"]

    with pytest.raises(MonitoringRuleAuthoringError) as excinfo:
        service.confirm_fact_and_compile(
            project_id=PROJECT,
            fact_revision_id=adopted.fact_revision_id,
            expected_state_version=adopted.state_version,
            fact_type="data_quality",
            deterministic_template=template,
            confirmed_by="medical_manager",
        )
    assert excinfo.value.code == "monitoring_rule_identity_required"
    assert excinfo.value.http_status == 409

    template["immutable_identity"] = {
        "mapping_revision": "mapping-v1",
        "mapping_content_sha256": "2" * 64,
        "capability_manifest_sha256": "5" * 64,
    }
    with pytest.raises(MonitoringRuleAuthoringError) as partial:
        service.confirm_fact_and_compile(
            project_id=PROJECT,
            fact_revision_id=adopted.fact_revision_id,
            expected_state_version=adopted.state_version,
            fact_type="data_quality",
            deterministic_template=template,
            confirmed_by="medical_manager",
        )
    assert partial.value.code == "monitoring_rule_identity_required"


def test_identity_confirmation_yields_confirmed_rule_without_second_approval(
    authoring,
) -> None:
    service, repository, ai_repository = authoring
    version = _version(service)
    candidate = _accepted_candidate(ai_repository)
    adopted, _ = service.adopt_ai_candidate(
        project_id=PROJECT,
        protocol_version_id=version.protocol_version_id,
        candidate_id=candidate.candidate_id,
        fact_key="visit_data_completeness",
        proposed_fact_type="data_quality",
    )
    template = _template()
    template["immutable_identity"] = {
        "mapping_revision": "mapping-revision-001",
        "mapping_content_sha256": "a" * 64,
        "capability_manifest_sha256": "b" * 64,
        "effective_capabilities_sha256": "c" * 64,
        "recommendation_candidate_id": candidate.candidate_id,
    }
    fact, rule = service.confirm_fact_and_compile(
        project_id=PROJECT,
        fact_revision_id=adopted.fact_revision_id,
        expected_state_version=adopted.state_version,
        fact_type="data_quality",
        deterministic_template=template,
        confirmed_by="medical_manager",
    )
    assert rule.status == "confirmed"
    assert rule.state_version == 1
    assert rule.mapping_revision == "mapping-revision-001"
    assert rule.mapping_content_sha256 == "a" * 64
    assert rule.capability_manifest_sha256 == "b" * 64
    assert rule.effective_capabilities_sha256 == "c" * 64
    assert rule.recommendation_candidate_id == candidate.candidate_id

    draft = service.create_draft(
        project_id=PROJECT,
        protocol_version_id=version.protocol_version_id,
        fact_revision_ids=[fact.fact_revision_id],
        created_by="medical_manager",
    )
    _, draft_rules = repository.rule_pack(draft.rule_pack_id)
    assert draft_rules[0].status == "confirmed"
    assert draft_rules[0].rule_revision_id == rule.rule_revision_id
    assert draft_rules[0].mapping_content_sha256 == "a" * 64

    shadow = service.start_shadow(
        project_id=PROJECT,
        rule_pack_id=draft.rule_pack_id,
        started_by="medical_manager",
    )
    assert shadow.status == "shadow"


def test_draft_and_stage_replays_pass_through_authoring_service(authoring) -> None:
    service, repository, ai_repository = authoring
    version, fact, _ = _confirmed_fact(service, ai_repository)
    draft = service.create_draft(
        project_id=PROJECT,
        protocol_version_id=version.protocol_version_id,
        fact_revision_ids=[fact.fact_revision_id],
        created_by="medical_manager",
    )
    replayed_draft = service.create_draft(
        project_id=PROJECT,
        protocol_version_id=version.protocol_version_id,
        fact_revision_ids=[fact.fact_revision_id],
        created_by="medical_manager",
    )
    assert replayed_draft.rule_pack_id == draft.rule_pack_id
    assert len(repository.list_rule_packs(PROJECT)) == 1

    with pytest.raises(
        RulePackRevisionConflictError,
        match="expected pack revision",
    ):
        service.create_draft(
            project_id=PROJECT,
            protocol_version_id=version.protocol_version_id,
            fact_revision_ids=[fact.fact_revision_id],
            created_by="medical_manager",
            expected_pack_revision=99,
        )

    _, draft_rules = repository.rule_pack(draft.rule_pack_id)
    assert draft_rules[0].status == "confirmed"
    shadow = service.start_shadow(
        project_id=PROJECT,
        rule_pack_id=draft.rule_pack_id,
        started_by="medical_manager",
        expected_pack_revision=draft.pack_revision,
    )
    replayed_shadow = service.start_shadow(
        project_id=PROJECT,
        rule_pack_id=draft.rule_pack_id,
        started_by="medical_manager",
        expected_pack_revision=draft.pack_revision,
    )
    assert replayed_shadow.rule_pack_id == shadow.rule_pack_id
    assert len(repository.list_rule_packs(PROJECT)) == 2

    with pytest.raises(
        RulePackRevisionConflictError,
        match="expected pack revision",
    ):
        service.start_shadow(
            project_id=PROJECT,
            rule_pack_id=draft.rule_pack_id,
            started_by="medical_manager",
            expected_pack_revision=99,
        )
    assert len(repository.list_rule_packs(PROJECT)) == 2
