from __future__ import annotations

from datetime import datetime, timezone
import inspect

import pytest

from packages.contracts.workbench_contracts.models import (
    RiskSeverity,
    RiskStatus,
)
from services.api.app.monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiClaim,
    MonitoringAiClaimKind,
    MonitoringAiEvidence,
    MonitoringAiTaskType,
)
from services.api.app.monitoring_ai_risk_bridge import (
    MonitoringAiRiskBridge,
    MonitoringAiRiskBridgeError,
)
from services.api.app.medical_risk_repository import MedicalRiskRepository


NOW = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
INPUT_HASH = "a" * 64
SOURCE_HASH_AE = "b" * 64
SOURCE_HASH_CM = "c" * 64
SOURCE_HASH_EX = "d" * 64


def _evidence(
    evidence_id: str,
    domain: str,
    *,
    source_hash: str,
    row: int,
    subject_id: str = "S001",
    site_id: str = "010",
    extra_fields: tuple[tuple[str, object], ...] = (),
) -> MonitoringAiEvidence:
    fields = [
        {"field": "DOMAIN", "value": domain},
        {"field": "SUBJID", "value": subject_id},
        {"field": "SITEID", "value": site_id},
        *({"field": key, "value": value} for key, value in extra_fields),
    ]
    return MonitoringAiEvidence(
        evidence_id=evidence_id,
        source_entry_id=f"listing-{domain.lower()}",
        source_content_sha256=source_hash,
        locator=f"listing:source:sheet:{domain}:row:{row}",
        quote=f"{domain} 原始记录",
        raw_fields={
            "evidence_kind": "original_data",
            "fields": fields,
        },
        input_revision_sha256=INPUT_HASH,
    )


def _candidate(
    *,
    status: MonitoringAiCandidateStatus = MonitoringAiCandidateStatus.PROPOSED,
    candidate_id: str = "candidate-001",
    job_id: str = "job-001",
    title: str = "AE与合并用药时间关系复核线索",
    text: str = "两类原始记录的日期接近，需结合完整上下文复核。",
    subject_id: str = "S001",
    domains: tuple[str, ...] = ("AE", "CM"),
    risk_category_code: str = "",
    evidence: tuple[MonitoringAiEvidence, ...] | None = None,
    evidence_ids: tuple[str, ...] = ("ev-ae", "ev-cm"),
    claims: tuple[MonitoringAiClaim, ...] | None = None,
) -> MonitoringAiCandidate:
    resolved_evidence = evidence or (
        _evidence(
            "ev-ae",
            "AE",
            source_hash=SOURCE_HASH_AE,
            row=12,
            extra_fields=(
                ("AETERM", "头痛"),
                ("AESTDAT", "2026-07-20"),
            ),
        ),
        _evidence(
            "ev-cm",
            "CM",
            source_hash=SOURCE_HASH_CM,
            row=7,
            extra_fields=(
                ("CMTRT", "布洛芬"),
                ("CMSTDAT", "2026-07-20"),
            ),
        ),
    )
    resolved_claims = claims or (
        MonitoringAiClaim(
            claim_id="claim-fact",
            kind=MonitoringAiClaimKind.FACT,
            text="AE开始日期与合并用药开始日期均记录为2026-07-20。",
            confidence=0.92,
            evidence_ids=("ev-ae", "ev-cm"),
        ),
        MonitoringAiClaim(
            claim_id="claim-inference",
            kind=MonitoringAiClaimKind.INFERENCE,
            text="时间接近可能值得结合访视上下文复核。",
            confidence=0.72,
            uncertainty="时间先后不能单独支持因果判断。",
            evidence_ids=("ev-ae", "ev-cm"),
        ),
        MonitoringAiClaim(
            claim_id="claim-action",
            kind=MonitoringAiClaimKind.RECOMMENDATION,
            text="建议核对AE、CM及相关访视记录。",
            confidence=0.80,
            uncertainty="尚未获得完整受试者上下文。",
            user_action="请医学经理复核原始记录。",
            evidence_ids=("ev-ae", "ev-cm"),
        ),
    )
    return MonitoringAiCandidate(
        candidate_id=candidate_id,
        job_id=job_id,
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS,
        candidate_type="cross_table_clue",
        title=title,
        text=text,
        structured_payload={
            "subject_id": subject_id,
            "domains": list(domains),
            "observations": ["AE与CM记录日期接近"],
            "temporal_relationships": ["时间相关但不代表因果"],
            "data_gaps": ["缺少相关访视的研究者解释"],
            "recommended_review": "核对AE、CM和访视原始记录。",
            "evidence_ids": list(evidence_ids),
            **(
                {"risk_category_code": risk_category_code}
                if risk_category_code
                else {}
            ),
        },
        claims=resolved_claims,
        evidence=resolved_evidence,
        status=status,
        input_revision_sha256=INPUT_HASH,
        prompt_version="monitoring-cross-table-clue-synthesis-v3",
        created_at=NOW,
    )


def _bridge(candidate: MonitoringAiCandidate):
    return MonitoringAiRiskBridge.convert(
        candidate,
        batch_id="batch-001",
        source_revision="source-revision-001",
        rule_pack_revision="rule-pack-001",
        engine_version="monitoring-engine-v1",
        created_at=NOW,
    )


def test_public_convert_interface_is_explicit_and_stable() -> None:
    signature = inspect.signature(MonitoringAiRiskBridge.convert)

    assert list(signature.parameters) == [
        "candidate",
        "batch_id",
        "source_revision",
        "rule_pack_revision",
        "engine_version",
        "created_at",
    ]
    for name in (
        "batch_id",
        "source_revision",
        "rule_pack_revision",
        "engine_version",
        "created_at",
    ):
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.return_annotation == "tuple[RiskCase, ...]"


@pytest.mark.parametrize(
    "status",
    (
        MonitoringAiCandidateStatus.PROPOSED,
        MonitoringAiCandidateStatus.ACCEPTED,
    ),
)
def test_proposed_and_accepted_candidates_enter_review_only_ledger(
    status: MonitoringAiCandidateStatus,
) -> None:
    risk = _bridge(_candidate(status=status))[0]

    assert risk.status is RiskStatus.IN_REVIEW
    assert risk.severity is RiskSeverity.MEDIUM
    assert risk.confidence == 0.65
    assert risk.project_id == "project-alpha"
    assert risk.subject_id == "S001"
    assert risk.site_id == "010"
    assert risk.source_batch_id == "batch-001"
    assert risk.source_revision == "source-revision-001"
    assert risk.rule_profile_revision == "rule-pack-001"
    assert risk.engine_version == "monitoring-engine-v1"
    assert risk.rule_id == "monitoring_ai.cross_table_clue_synthesis"
    assert risk.risk_type == "AI跨域医学复核线索"
    assert risk.primary_category == "other_medical_review"
    assert risk.evidence_span_ids == [
        "listing:source:sheet:AE:row:12",
        "listing:source:sheet:CM:row:7",
    ]
    assert "non_study_concomitant_medication" in risk.tags
    assert "study_treatment_record" not in risk.tags

    assert risk.rationale.startswith("原始数据：DOMAIN=AE")
    assert risk.rationale.index("原始数据：") < risk.rationale.index("事实：")
    assert risk.rationale.index("事实：") < risk.rationale.index(
        "推断（待医学复核）："
    )
    assert "不代表已确认漏报、方案违背、因果关系或需发出 Query" in risk.rationale
    assert risk.recommended_action.startswith("建议复核：")
    assert "系统不自动形成 Query 或确定性结论" in risk.recommended_action

    fragment = risk.evidence_snapshots[0].fragment
    assert fragment["candidate_status"] == status.value
    assert fragment["batch_id"] == "batch-001"
    assert fragment["input_revision_sha256"] == INPUT_HASH
    assert fragment["medical_review_candidate_only"] is True
    assert [item["locator"] for item in fragment["evidence"]] == (
        risk.evidence_span_ids
    )


@pytest.mark.parametrize(
    "status",
    (
        MonitoringAiCandidateStatus.REJECTED,
        MonitoringAiCandidateStatus.SUPERSEDED,
    ),
)
def test_rejected_and_superseded_candidates_are_not_converted(
    status: MonitoringAiCandidateStatus,
) -> None:
    assert _bridge(_candidate(status=status)) == ()


def test_risk_key_ignores_model_wording_candidate_and_job_identity() -> None:
    first = _bridge(_candidate())[0]
    changed_wording = _bridge(
        _candidate(
            candidate_id="candidate-999",
            job_id="job-999",
            title="另一种表述",
            text="请复核两张原始表中的相关记录。",
        )
    )[0]

    assert first.risk_key == changed_wording.risk_key
    assert first.risk_instance_id != changed_wording.risk_instance_id


def test_risk_key_changes_when_stable_source_locator_identity_changes() -> None:
    changed_evidence = (
        _evidence(
            "ev-ae",
            "AE",
            source_hash=SOURCE_HASH_AE,
            row=13,
            extra_fields=(("AETERM", "头痛"),),
        ),
        _evidence(
            "ev-cm",
            "CM",
            source_hash=SOURCE_HASH_CM,
            row=7,
            extra_fields=(("CMTRT", "布洛芬"),),
        ),
    )

    assert _bridge(_candidate())[0].risk_key != _bridge(
        _candidate(evidence=changed_evidence)
    )[0].risk_key


def test_all_candidate_evidence_locators_are_retained() -> None:
    extra = _evidence(
        "ev-lb",
        "LB",
        source_hash="e" * 64,
        row=4,
        extra_fields=(("LBTEST", "ALT"), ("LBORRES", "88")),
    )
    candidate = _candidate(evidence=(*_candidate().evidence, extra))

    risk = _bridge(candidate)[0]

    assert risk.evidence_span_ids == [
        "listing:source:sheet:AE:row:12",
        "listing:source:sheet:CM:row:7",
        "listing:source:sheet:LB:row:4",
    ]
    assert len(risk.evidence_snapshots[0].fragment["evidence"]) == 3


def test_bridged_risk_is_accepted_by_unified_medical_risk_ledger(
    tmp_path,
) -> None:
    risk = _bridge(_candidate())[0]
    repository = MedicalRiskRepository(tmp_path / "medical-risks.sqlite3")

    snapshot = repository.save_snapshot(
        project_id="project-alpha",
        source_batch_id="batch-001",
        source_revision="source-revision-001",
        rule_profile_revision="rule-pack-001",
        engine_version="monitoring-engine-v1",
        evaluated_subject_count=1,
        risks=(risk,),
        resolution_complete=False,
    )
    stored = repository.list_risks(
        "project-alpha",
        snapshot_id=snapshot.snapshot_id,
    )

    assert snapshot.risk_count == 1
    assert stored[0].risk_key == risk.risk_key
    assert stored[0].risk_instance_id == risk.risk_instance_id
    assert stored[0].status is RiskStatus.IN_REVIEW


def test_cm_and_study_treatment_domains_are_not_conflated() -> None:
    ex_evidence = _evidence(
        "ev-ex",
        "EX",
        source_hash=SOURCE_HASH_EX,
        row=2,
        extra_fields=(("EXDOSE", "100"), ("EXDOSU", "mg")),
    )
    ae_evidence = _candidate().evidence[0]
    risk = _bridge(
        _candidate(
            domains=("AE", "EX"),
            evidence=(ae_evidence, ex_evidence),
            evidence_ids=("ev-ae", "ev-ex"),
            claims=(
                MonitoringAiClaim(
                    claim_id="claim-fact",
                    kind=MonitoringAiClaimKind.FACT,
                    text="AE与试验药物给药记录需要联合复核。",
                    confidence=0.8,
                    evidence_ids=("ev-ae", "ev-ex"),
                ),
            ),
        )
    )[0]

    assert risk.primary_category == "other_medical_review"
    assert "study_treatment_record" in risk.tags
    assert "non_study_concomitant_medication" not in risk.tags

    mixed = _bridge(
        _candidate(
            domains=("AE", "CM", "EX"),
            evidence=(*_candidate().evidence, ex_evidence),
            evidence_ids=("ev-ae", "ev-cm", "ev-ex"),
            claims=(
                MonitoringAiClaim(
                    claim_id="claim-fact",
                    kind=MonitoringAiClaimKind.FACT,
                    text="三类记录需要联合复核。",
                    confidence=0.8,
                    evidence_ids=("ev-ae", "ev-cm", "ev-ex"),
                ),
            ),
        )
    )[0]
    assert mixed.primary_category == "other_medical_review"
    assert "non_study_concomitant_medication" in mixed.tags
    assert "study_treatment_record" in mixed.tags


def test_explicit_ai_category_is_validated_against_original_data_domains() -> None:
    cm_risk = _bridge(
        _candidate(
            risk_category_code="prohibited_concomitant_medication_pd",
        )
    )[0]
    assert (
        cm_risk.primary_category
        == "prohibited_concomitant_medication_pd"
    )

    ex_evidence = _evidence(
        "ev-ex",
        "EX",
        source_hash=SOURCE_HASH_EX,
        row=2,
    )
    ae_evidence = _candidate().evidence[0]
    ex_risk = _bridge(
        _candidate(
            domains=("AE", "EX"),
            risk_category_code="study_treatment_adherence",
            evidence=(ae_evidence, ex_evidence),
            evidence_ids=("ev-ae", "ev-ex"),
            claims=(
                MonitoringAiClaim(
                    claim_id="claim-fact",
                    kind=MonitoringAiClaimKind.FACT,
                    text="AE与试验药物原始记录需要联合复核。",
                    confidence=0.8,
                    evidence_ids=("ev-ae", "ev-ex"),
                ),
            ),
        )
    )[0]
    assert ex_risk.primary_category == "study_treatment_adherence"

    with pytest.raises(
        MonitoringAiRiskBridgeError,
        match="prohibit EX/EC/DA/IP",
    ):
        _bridge(
            _candidate(
                domains=("AE", "CM", "EX"),
                risk_category_code="prohibited_concomitant_medication_pd",
                evidence=(*_candidate().evidence, ex_evidence),
                evidence_ids=("ev-ae", "ev-cm", "ev-ex"),
                claims=(
                    MonitoringAiClaim(
                        claim_id="claim-fact",
                        kind=MonitoringAiClaimKind.FACT,
                        text="三类原始记录需要联合复核。",
                        confidence=0.8,
                        evidence_ids=("ev-ae", "ev-cm", "ev-ex"),
                    ),
                ),
            )
        )


def test_ai_title_and_narrative_do_not_refine_category() -> None:
    baseline = _bridge(_candidate())[0]
    rewritten = _bridge(
        _candidate(
            title="禁用合并用药且永久停药",
            text="标题和自然语言即使包含医学类别，也仅作为展示文本。",
        )
    )[0]

    assert baseline.primary_category == "other_medical_review"
    assert rewritten.primary_category == baseline.primary_category


@pytest.mark.parametrize(
    ("candidate", "message"),
    (
        (
            _candidate(subject_id="<current-subject>"),
            "subject_id placeholder",
        ),
        (
            _candidate(domains=("AE", "medication_compliance")),
            "declared domains",
        ),
        (
            _candidate(evidence_ids=("ev-ae", "missing-evidence")),
            "missing evidence",
        ),
    ),
)
def test_incomplete_subject_domain_or_evidence_graph_fails_closed(
    candidate: MonitoringAiCandidate,
    message: str,
) -> None:
    with pytest.raises(MonitoringAiRiskBridgeError, match=message):
        _bridge(candidate)


def test_one_real_domain_plus_derived_concept_fails_closed() -> None:
    pseudo = MonitoringAiEvidence(
        evidence_id="ev-derived",
        source_entry_id="analysis-result",
        source_content_sha256="f" * 64,
        locator="analysis:medication_compliance",
        quote="派生的依从性主题",
        raw_fields={
            "evidence_kind": "derived_analysis",
            "domain": "medication_compliance",
        },
        input_revision_sha256=INPUT_HASH,
    )
    with pytest.raises(MonitoringAiRiskBridgeError, match="two real domains"):
        _bridge(
            _candidate(
                domains=("AE", "medication_compliance"),
                evidence=(_candidate().evidence[0], pseudo),
                evidence_ids=("ev-ae", "ev-derived"),
                claims=(
                    MonitoringAiClaim(
                        claim_id="claim-fact",
                        kind=MonitoringAiClaimKind.FACT,
                        text="需要联合复核。",
                        confidence=0.7,
                        evidence_ids=("ev-ae", "ev-derived"),
                    ),
                ),
            )
        )


def test_subject_conflict_in_original_data_fails_closed() -> None:
    conflicting = _evidence(
        "ev-cm",
        "CM",
        source_hash=SOURCE_HASH_CM,
        row=7,
        subject_id="S999",
    )
    with pytest.raises(MonitoringAiRiskBridgeError, match="subject_id conflicts"):
        _bridge(
            _candidate(
                evidence=(_candidate().evidence[0], conflicting),
            )
        )


@pytest.mark.parametrize(
    "text",
    (
        "确定为AE漏报，应立即处理。",
        "该情况构成方案违背。",
        "该用药导致了不良事件。",
        "建议立即发出 Query。",
    ),
)
def test_definitive_overreach_language_fails_closed(text: str) -> None:
    with pytest.raises(
        MonitoringAiRiskBridgeError,
        match="unauthorized definitive",
    ):
        _bridge(_candidate(text=text))


def test_explicit_negated_boundary_language_is_allowed() -> None:
    risk = _bridge(
        _candidate(
            text=(
                "时间关联不代表因果，也不能据此确认AE漏报、方案违背"
                "或需发出 Query。"
            )
        )
    )[0]

    assert risk.status is RiskStatus.IN_REVIEW


def test_negation_in_another_clause_does_not_hide_overreach() -> None:
    with pytest.raises(
        MonitoringAiRiskBridgeError,
        match="unauthorized definitive",
    ):
        _bridge(
            _candidate(
                text="不能仅凭日期确认因果，但确定为AE漏报。"
            )
        )


def test_wrong_task_type_and_naive_timestamp_fail_closed() -> None:
    wrong_task = _candidate().model_copy(
        update={"task_type": MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY}
    )
    with pytest.raises(MonitoringAiRiskBridgeError, match="only CROSS_TABLE"):
        _bridge(wrong_task)

    with pytest.raises(MonitoringAiRiskBridgeError, match="timezone"):
        MonitoringAiRiskBridge.convert(
            _candidate(),
            batch_id="batch-001",
            source_revision="source-revision-001",
            rule_pack_revision="rule-pack-001",
            engine_version="monitoring-engine-v1",
            created_at=datetime(2026, 7, 29, 8, 0),
        )
