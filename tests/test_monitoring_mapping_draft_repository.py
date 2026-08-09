from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.api.app.monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiClaim,
    MonitoringAiClaimKind,
    MonitoringAiEvidence,
    MonitoringAiInputRevision,
    MonitoringAiJobCreate,
    MonitoringAiJobStatus,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
    content_sha256,
)
from services.api.app.monitoring_ai_repository import MonitoringAiRepository
from services.api.app.monitoring_mapping_draft_repository import (
    MonitoringMappingDraftRepository,
    MonitoringMappingDraftStatus,
    MonitoringMappingNotFoundError,
    MonitoringMappingSourceStateError,
    MonitoringMappingStateConflictError,
)


SOURCE_HASH = "a" * 64
PROFILE_HASH = "b" * 64
INPUT_HASH = "c" * 64
NOW = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)


def _revision(
    project_id: str,
    *,
    suffix: str = "001",
) -> MonitoringAiInputRevision:
    return MonitoringAiInputRevision(
        project_id=project_id,
        batch_revision=f"batch-revision-{suffix}",
        mapping_revision=f"pre-mapping-{suffix}",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id="source-listing",
                source_content_sha256=SOURCE_HASH,
            ),
        ),
    )


def _mapping(
    domain: str,
    field: str,
    evidence_id: str,
) -> dict[str, object]:
    return {
        "domain": domain,
        "source_field": field,
        "recommended_role": (
            "concomitant_medication_term"
            if domain == "CM"
            else "adverse_event_observation"
        ),
        "field_kind": "source_collected",
        "confidence": 0.88,
        "uncertainty": "需结合数据字典确认字段语义。",
        "user_action": "请确认推荐角色。",
        "related_fields": [],
        "evidence_ids": [evidence_id],
        "standards_reference": None,
        "derivation_lineage": None,
    }


def _candidate(
    job,
    fields: tuple[str, ...],
    *,
    candidate_suffix: str = "1",
    evidence_raw_overrides: dict[str, dict[str, object]] | None = None,
    mapping_overrides: dict[str, dict[str, object]] | None = None,
) -> MonitoringAiCandidate:
    domain = job.input_payload_sha256  # only used to vary deterministic IDs
    del domain
    profile_domain = job.business_key.split(":")[2]
    evidence = tuple(
        MonitoringAiEvidence(
            evidence_id=f"ev-{candidate_suffix}-{index}",
            source_entry_id="source-listing",
            source_content_sha256=SOURCE_HASH,
            locator=f"profile://{profile_domain}/{field}",
            raw_fields={
                "domain": profile_domain,
                "field": field,
                "inferred_type": "string",
                **(evidence_raw_overrides or {}).get(field, {}),
            },
            input_revision_sha256=job.input_revision_sha256,
        )
        for index, field in enumerate(fields, start=1)
    )
    return MonitoringAiCandidate(
        candidate_id=f"candidate-{job.job_id}-{candidate_suffix}",
        job_id=job.job_id,
        project_id=job.project_id,
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        candidate_type="listing_field_mapping_set",
        title="字段映射建议",
        structured_payload={
            "field_mappings": [
                {
                    **_mapping(
                        profile_domain,
                        field,
                        evidence[index].evidence_id,
                    ),
                    **(mapping_overrides or {}).get(field, {}),
                }
                for index, field in enumerate(fields)
            ]
        },
        claims=(
            MonitoringAiClaim(
                claim_id=f"claim-{candidate_suffix}",
                kind=MonitoringAiClaimKind.RECOMMENDATION,
                text="建议按字段画像建立项目中立映射。",
                confidence=0.88,
                uncertainty="仍需用户确认。",
                user_action="审阅并决定是否接受。",
                evidence_ids=(evidence[0].evidence_id,),
            ),
        ),
        evidence=evidence,
        input_revision_sha256=job.input_revision_sha256,
        prompt_version=job.prompt_version,
        created_at=NOW,
    )


def _seed_chunk(
    ai_repository: MonitoringAiRepository,
    *,
    project_id: str = "project-alpha",
    batch_id: str = "batch-001",
    domain: str,
    chunk_index: int,
    chunk_total: int,
    fields: tuple[str, ...],
    domain_field_count: int,
    full_field_count: int = 3,
    expected_domains: tuple[str, ...] = ("AE", "CM"),
    revision_suffix: str = "001",
    prompt_version: str = "mapping-prompt-v1",
    accept: bool = True,
    candidate_count: int = 1,
    evidence_raw_overrides: dict[str, dict[str, object]] | None = None,
    mapping_overrides: dict[str, dict[str, object]] | None = None,
):
    revision = _revision(project_id, suffix=revision_suffix)
    profile_fields = [
        {
            "domain": domain,
            "field": field,
            "total_rows": 100,
            "non_empty_count": 90,
            "null_rate": 0.1,
            "inferred_type": "string",
            "unique_value_count": 20,
            "top_values": [],
            "representative_values": [],
            "anomaly_examples": [],
        }
        for field in fields
    ]
    payload = {
        "schema_version": "monitoring_ai_v1",
        "field_profile": {
            "schema_version": "monitoring_ai_field_profile_v1",
            "scope": "complete_profile_chunk",
            "project_id": project_id,
            "batch_id": batch_id,
            "batch_revision": 1,
            "expected_domains": list(expected_domains),
            "full_profile_sha256": PROFILE_HASH,
            "full_input_sha256": INPUT_HASH,
            "full_field_count": full_field_count,
            "domain": domain,
            "domain_field_count": domain_field_count,
            "chunk_index": chunk_index,
            "chunk_total": chunk_total,
            "chunk_size_limit": 1,
            "fields": profile_fields,
        },
    }
    request = MonitoringAiJobCreate(
        project_id=project_id,
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        input_revision=revision,
        input_payload=payload,
        prompt_version=prompt_version,
        profile_id="independent-ai-test",
        provider="test-provider",
        requested_model="test-model",
        max_attempts=2,
        business_key=(
            f"listing-field-mapping:{batch_id}:{domain}:"
            f"{chunk_index:04d}-of-{chunk_total:04d}"
        ),
    )
    created = ai_repository.create_or_get(request)
    running = ai_repository.claim_next(f"worker-{created.job_id}")
    assert running is not None and running.job_id == created.job_id
    candidates = tuple(
        _candidate(
            running,
            fields,
            candidate_suffix=str(index),
            evidence_raw_overrides=evidence_raw_overrides,
            mapping_overrides=mapping_overrides,
        )
        for index in range(1, candidate_count + 1)
    )
    ai_repository.complete(
        running,
        owner=f"worker-{created.job_id}",
        response_model="test-model",
        raw_output={"candidates": len(candidates)},
        candidates=candidates,
    )
    if accept:
        for candidate in candidates:
            ai_repository.decide_candidate(
                project_id,
                candidate.candidate_id,
                decision=MonitoringAiCandidateStatus.ACCEPTED,
                actor="medical-manager",
                reason="同意纳入字段映射草稿",
                current_input_revision_sha256=running.input_revision_sha256,
            )
    return running, candidates


def _seed_complete_source(
    ai_repository: MonitoringAiRepository,
    *,
    project_id: str = "project-alpha",
) -> tuple:
    ae_1 = _seed_chunk(
        ai_repository,
        project_id=project_id,
        domain="AE",
        chunk_index=1,
        chunk_total=2,
        fields=("AETERM",),
        domain_field_count=2,
    )
    ae_2 = _seed_chunk(
        ai_repository,
        project_id=project_id,
        domain="AE",
        chunk_index=2,
        chunk_total=2,
        fields=("AESTDAT",),
        domain_field_count=2,
    )
    cm_1 = _seed_chunk(
        ai_repository,
        project_id=project_id,
        domain="CM",
        chunk_index=1,
        chunk_total=1,
        fields=("CMTRT",),
        domain_field_count=1,
    )
    return ae_1, ae_2, cm_1


def _seed_meddra_source(
    ai_repository: MonitoringAiRepository,
    *,
    include_version: bool = True,
    include_reported_term: bool = True,
    coding_domain: str = "AE",
    standardized_coded: bool = True,
) -> None:
    field_specs: list[tuple[str, str, dict[str, object]]] = []
    if include_reported_term:
        field_specs.append(
            (
                "AE",
                "AETERM",
                {
                    "recommended_role": "ae_reported_term",
                    "field_kind": "source_collected",
                },
            )
        )
    field_specs.extend(
        [
            (
                coding_domain,
                "PTCODE",
                {
                    "recommended_role": "meddra_pt_code",
                    "field_kind": (
                        "standardized_coded"
                        if standardized_coded
                        else "source_collected"
                    ),
                    "derivation_lineage": (
                        {
                            "source_fields": ["PTTERM"],
                            "coding_system": "MedDRA",
                            "dictionary_version_field": "MDRAVER",
                            "coding_chain_id": "meddra-primary",
                        }
                        if standardized_coded
                        else None
                    ),
                },
            ),
            (
                coding_domain,
                "PTTERM",
                {
                    "recommended_role": "meddra_pt_term",
                    "field_kind": (
                        "standardized_coded"
                        if standardized_coded
                        else "source_collected"
                    ),
                    "derivation_lineage": (
                        {
                            "source_fields": ["PTCODE"],
                            "coding_system": "MedDRA",
                            "dictionary_version_field": "MDRAVER",
                            "coding_chain_id": "meddra-primary",
                        }
                        if standardized_coded
                        else None
                    ),
                },
            ),
        ]
    )
    if include_version:
        field_specs.append(
            (
                coding_domain,
                "MDRAVER",
                {
                    "recommended_role": "meddra_dictionary_version",
                    "field_kind": "source_metadata",
                },
            )
        )

    expected_domains = tuple(
        sorted({domain for domain, _, _ in field_specs})
    )
    full_field_count = len(field_specs)
    for domain in expected_domains:
        domain_specs = [
            spec for spec in field_specs if spec[0] == domain
        ]
        for chunk_index, (_, field, overrides) in enumerate(
            domain_specs,
            start=1,
        ):
            _seed_chunk(
                ai_repository,
                domain=domain,
                chunk_index=chunk_index,
                chunk_total=len(domain_specs),
                fields=(field,),
                domain_field_count=len(domain_specs),
                full_field_count=full_field_count,
                expected_domains=expected_domains,
                mapping_overrides={field: overrides},
            )


@pytest.fixture
def repositories(tmp_path: Path):
    path = tmp_path / "monitoring.sqlite3"
    ai_repository = MonitoringAiRepository(path)
    mapping_repository = MonitoringMappingDraftRepository(path)
    return path, ai_repository, mapping_repository


def test_assemble_requires_all_accepted_chunks_and_preserves_lineage(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    seeded = _seed_complete_source(ai_repository)

    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )

    assert draft.status == MonitoringMappingDraftStatus.DRAFT
    assert draft.version == 1
    assert [f"{item.domain}.{item.source_field}" for item in draft.fields] == [
        "AE.AESTDAT",
        "AE.AETERM",
        "CM.CMTRT",
    ]
    assert draft.confirmed_revision_id == ""
    assert set(draft.expected_job_ids) == {
        item[0].job_id for item in seeded
    }
    assert {
        (item.domain, item.source_field, item.job_id, item.candidate_id)
        for item in draft.field_sources
    } == {
        (
            candidate.structured_payload["field_mappings"][0]["domain"],
            candidate.structured_payload["field_mappings"][0]["source_field"],
            job.job_id,
            candidate.candidate_id,
        )
        for job, candidates in seeded
        for candidate in candidates
    }
    assert mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    ) == draft
    assert mapping_repository.find_draft_for_batch(
        "project-alpha",
        "batch-001",
    ) == draft
    assert mapping_repository.find_draft_for_batch(
        "project-alpha",
        "batch-001",
        full_profile_sha256=PROFILE_HASH,
    ) == draft
    assert mapping_repository.find_draft_for_batch(
        "project-alpha",
        "missing-batch",
    ) is None


def test_assemble_adds_partial_date_constraint_from_frozen_profile_evidence(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_chunk(
        ai_repository,
        domain="AE",
        chunk_index=1,
        chunk_total=2,
        fields=("AETERM",),
        domain_field_count=2,
    )
    _seed_chunk(
        ai_repository,
        domain="AE",
        chunk_index=2,
        chunk_total=2,
        fields=("AESTDAT",),
        domain_field_count=2,
        evidence_raw_overrides={
            "AESTDAT": {
                "inferred_type": "date",
                "representative_values": ["2025-06-12", "2024-10-UK"],
            }
        },
    )
    _seed_chunk(
        ai_repository,
        domain="CM",
        chunk_index=1,
        chunk_total=1,
        fields=("CMTRT",),
        domain_field_count=1,
    )

    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    date_field = next(
        item for item in draft.fields if item.source_field == "AESTDAT"
    )

    assert date_field.value_constraints == {
        "date_precision": "month",
        "supports_exact_date": False,
        "observed_precisions": ["month"],
        "basis": "frozen_field_profile_observation",
    }
    quality = mapping_repository.semantic_quality(
        "project-alpha",
        draft.draft_id,
    )
    assert {
        item.rule_id for item in quality.finding_groups
    }.issuperset({"G-DATE-001"})


def test_assemble_adds_auditable_cross_chunk_meddra_reported_term_anchor(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_meddra_source(ai_repository)

    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )

    coded = tuple(
        item
        for item in draft.fields
        if item.source_field in {"PTCODE", "PTTERM"}
    )
    assert len(coded) == 2
    for field in coded:
        assert field.field_kind.value == "standardized_coded"
        lineage = field.derivation_lineage or {}
        assert "AETERM" in lineage["source_fields"]
        assert lineage["dictionary_version_field"] == "MDRAVER"
        assert "dictionary_version" not in lineage
        assert lineage["source_anchor_contract"] == {
            "schema_version": "monitoring_meddra_source_anchor_v1",
            "anchor_type": "reported_term_to_standardized_meddra",
            "scope": "same_project_same_domain_complete_frozen_source_set",
            "domain": "AE",
            "reported_term_fields": ["AETERM"],
            "dictionary_version_field": "MDRAVER",
            "input_revision_sha256": draft.input_revision_sha256,
            "source_set_sha256": draft.source_set_sha256,
        }
    quality = mapping_repository.semantic_quality(
        "project-alpha",
        draft.draft_id,
    )
    assert "G-AEMH-001" not in {
        item.rule_id for item in quality.finding_groups
    }


def test_assemble_never_promotes_source_collected_meddra_fields(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_meddra_source(ai_repository, standardized_coded=False)

    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )

    coded_source_fields = tuple(
        item
        for item in draft.fields
        if item.source_field in {"PTCODE", "PTTERM"}
    )
    assert {
        item.field_kind.value for item in coded_source_fields
    } == {"source_collected"}
    assert all(
        item.derivation_lineage is None for item in coded_source_fields
    )


@pytest.mark.parametrize(
    (
        "include_version",
        "include_reported_term",
        "coding_domain",
        "expected_kind",
    ),
    [
        (False, True, "AE", "source_collected"),
        (True, False, "AE", "standardized_coded"),
        (True, True, "MH", "standardized_coded"),
    ],
    ids=[
        "missing-version-downgraded",
        "missing-reported-term",
        "cross-domain",
    ],
)
def test_assemble_does_not_anchor_incomplete_or_cross_domain_meddra_chain(
    repositories,
    include_version: bool,
    include_reported_term: bool,
    coding_domain: str,
    expected_kind: str,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_meddra_source(
        ai_repository,
        include_version=include_version,
        include_reported_term=include_reported_term,
        coding_domain=coding_domain,
    )

    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )

    coded = tuple(
        item
        for item in draft.fields
        if item.source_field in {"PTCODE", "PTTERM"}
    )
    assert len(coded) == 2
    # A chain without a verifiable version-support field is downgraded as one
    # fail-closed source-set operation; a complete chain without a reported
    # term stays standardized but is never anchored.
    assert {item.field_kind.value for item in coded} == {expected_kind}
    assert all(
        "source_anchor_contract" not in (item.derivation_lineage or {})
        and "AETERM"
        not in (item.derivation_lineage or {}).get("source_fields", [])
        for item in coded
    )
    quality = mapping_repository.semantic_quality(
        "project-alpha",
        draft.draft_id,
    )
    rule_ids = {item.rule_id for item in quality.finding_groups}
    if expected_kind == "source_collected":
        assert all(
            "incomplete_coding_downgraded_to_source_collected"
            in item.quality_gate_actions
            for item in coded
        )
        assert "G-AEMH-001" not in rule_ids
        assert "G-CODE-003" not in rule_ids
        assert "G-CODE-002" in rule_ids
    else:
        assert "G-AEMH-001" in rule_ids


@pytest.mark.parametrize(
    "status",
    [
        MonitoringAiJobStatus.QUEUED,
        MonitoringAiJobStatus.RUNNING,
        MonitoringAiJobStatus.FAILED,
        MonitoringAiJobStatus.BLOCKED,
        MonitoringAiJobStatus.STALE_INPUT,
        MonitoringAiJobStatus.CANCELLED,
    ],
)
def test_assemble_fails_closed_for_non_completed_chunk(
    repositories,
    status: MonitoringAiJobStatus,
) -> None:
    path, ai_repository, mapping_repository = repositories
    seeded = _seed_complete_source(ai_repository)
    target_job = seeded[0][0]
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_jobs SET status = ? WHERE job_id = ?",
            (status.value, target_job.job_id),
        )

    with pytest.raises(MonitoringMappingSourceStateError, match="not completed"):
        mapping_repository.assemble(
            "project-alpha",
            "batch-001",
            PROFILE_HASH,
        )


@pytest.mark.parametrize(
    "candidate_status",
    [
        MonitoringAiCandidateStatus.PROPOSED,
        MonitoringAiCandidateStatus.REJECTED,
        MonitoringAiCandidateStatus.SUPERSEDED,
    ],
)
def test_assemble_fails_closed_for_unaccepted_candidate(
    repositories,
    candidate_status: MonitoringAiCandidateStatus,
) -> None:
    path, ai_repository, mapping_repository = repositories
    seeded = _seed_complete_source(ai_repository)
    target_candidate = seeded[0][1][0]
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE monitoring_ai_candidates SET status = ?
            WHERE candidate_id = ?
            """,
            (candidate_status.value, target_candidate.candidate_id),
        )

    with pytest.raises(MonitoringMappingSourceStateError, match="not accepted"):
        mapping_repository.assemble(
            "project-alpha",
            "batch-001",
            PROFILE_HASH,
        )


def test_assemble_fails_closed_for_missing_chunk(repositories) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_chunk(
        ai_repository,
        domain="AE",
        chunk_index=1,
        chunk_total=2,
        fields=("AETERM",),
        domain_field_count=2,
    )
    _seed_chunk(
        ai_repository,
        domain="CM",
        chunk_index=1,
        chunk_total=1,
        fields=("CMTRT",),
        domain_field_count=1,
    )

    with pytest.raises(MonitoringMappingSourceStateError, match="chunk slots"):
        mapping_repository.assemble(
            "project-alpha",
            "batch-001",
            PROFILE_HASH,
        )


def test_assemble_fails_closed_for_entire_missing_domain(repositories) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_chunk(
        ai_repository,
        domain="AE",
        chunk_index=1,
        chunk_total=1,
        fields=("AETERM", "AESTDAT"),
        domain_field_count=2,
        full_field_count=2,
    )

    with pytest.raises(MonitoringMappingSourceStateError, match="domains are missing"):
        mapping_repository.assemble(
            "project-alpha",
            "batch-001",
            PROFILE_HASH,
        )


def test_assemble_fails_closed_for_duplicate_chunk_slot(repositories) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    _seed_chunk(
        ai_repository,
        domain="AE",
        chunk_index=1,
        chunk_total=2,
        fields=("AETERM",),
        domain_field_count=2,
        prompt_version="mapping-prompt-v2",
    )

    with pytest.raises(MonitoringMappingSourceStateError, match="duplicate chunk slot"):
        mapping_repository.assemble(
            "project-alpha",
            "batch-001",
            PROFILE_HASH,
        )


def test_assemble_fails_closed_for_duplicate_field_across_chunks(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_chunk(
        ai_repository,
        domain="AE",
        chunk_index=1,
        chunk_total=2,
        fields=("AETERM",),
        domain_field_count=2,
    )
    _seed_chunk(
        ai_repository,
        domain="AE",
        chunk_index=2,
        chunk_total=2,
        fields=("AETERM",),
        domain_field_count=2,
    )
    _seed_chunk(
        ai_repository,
        domain="CM",
        chunk_index=1,
        chunk_total=1,
        fields=("CMTRT",),
        domain_field_count=1,
    )

    with pytest.raises(
        MonitoringMappingSourceStateError,
        match="multiple chunks",
    ):
        mapping_repository.assemble(
            "project-alpha",
            "batch-001",
            PROFILE_HASH,
        )


def test_assemble_fails_closed_for_mixed_input_revisions(repositories) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_chunk(
        ai_repository,
        domain="AE",
        chunk_index=1,
        chunk_total=2,
        fields=("AETERM",),
        domain_field_count=2,
    )
    _seed_chunk(
        ai_repository,
        domain="AE",
        chunk_index=2,
        chunk_total=2,
        fields=("AESTDAT",),
        domain_field_count=2,
        revision_suffix="002",
    )
    _seed_chunk(
        ai_repository,
        domain="CM",
        chunk_index=1,
        chunk_total=1,
        fields=("CMTRT",),
        domain_field_count=1,
    )

    with pytest.raises(
        MonitoringMappingSourceStateError,
        match="one input revision",
    ):
        mapping_repository.assemble(
            "project-alpha",
            "batch-001",
            PROFILE_HASH,
        )


def test_assemble_fails_closed_for_missing_or_duplicate_candidate(
    repositories,
) -> None:
    path, ai_repository, mapping_repository = repositories
    seeded = _seed_complete_source(ai_repository)
    target_candidate = seeded[0][1][0]
    with sqlite3.connect(path) as connection:
        connection.execute(
            "DELETE FROM monitoring_ai_candidates WHERE candidate_id = ?",
            (target_candidate.candidate_id,),
        )
    with pytest.raises(
        MonitoringMappingSourceStateError,
        match="exactly one candidate",
    ):
        mapping_repository.assemble(
            "project-alpha",
            "batch-001",
            PROFILE_HASH,
        )

    path_2 = path.parent / "duplicate-candidate.sqlite3"
    ai_2 = MonitoringAiRepository(path_2)
    mapping_2 = MonitoringMappingDraftRepository(path_2)
    _seed_chunk(
        ai_2,
        domain="AE",
        chunk_index=1,
        chunk_total=1,
        fields=("AETERM", "AESTDAT"),
        domain_field_count=2,
        full_field_count=3,
        candidate_count=2,
    )
    _seed_chunk(
        ai_2,
        domain="CM",
        chunk_index=1,
        chunk_total=1,
        fields=("CMTRT",),
        domain_field_count=1,
    )
    with pytest.raises(
        MonitoringMappingSourceStateError,
        match="exactly one candidate",
    ):
        mapping_2.assemble("project-alpha", "batch-001", PROFILE_HASH)


def test_edit_is_field_scoped_idempotent_and_cas_protected(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    original_source = next(
        item
        for item in draft.field_sources
        if (item.domain, item.source_field) == ("AE", "AETERM")
    )

    edited = mapping_repository.edit_field(
        "project-alpha",
        draft.draft_id,
        domain="AE",
        source_field="AETERM",
        patch={
            "recommended_role": "adverse_event_verbatim_term",
            "confidence": 0.95,
        },
        expected_version=1,
        actor="medical-manager",
        idempotency_key="edit-aeterm-001",
    )
    assert edited.version == 2
    edited_field = next(
        item
        for item in edited.fields
        if (item.domain, item.source_field) == ("AE", "AETERM")
    )
    assert edited_field.recommended_role == "adverse_event_verbatim_term"
    assert edited_field.confidence == 0.95
    assert original_source in edited.field_sources

    repeated = mapping_repository.edit_field(
        "project-alpha",
        draft.draft_id,
        domain="AE",
        source_field="AETERM",
        patch={
            "recommended_role": "adverse_event_verbatim_term",
            "confidence": 0.95,
        },
        expected_version=1,
        actor="medical-manager",
        idempotency_key="edit-aeterm-001",
    )
    assert repeated.version == 2

    with pytest.raises(MonitoringMappingStateConflictError, match="CAS"):
        mapping_repository.edit_field(
            "project-alpha",
            draft.draft_id,
            domain="AE",
            source_field="AETERM",
            patch={"confidence": 0.96},
            expected_version=1,
            actor="medical-manager",
            idempotency_key="edit-aeterm-002",
        )
    with pytest.raises(ValueError, match="editable"):
        mapping_repository.edit_field(
            "project-alpha",
            draft.draft_id,
            domain="AE",
            source_field="AETERM",
            patch={"source_field": "AEDECOD"},
            expected_version=2,
            actor="medical-manager",
            idempotency_key="edit-aeterm-003",
        )


def test_field_edits_cannot_bypass_monitoring_semantic_boundaries(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )

    invalid_edits = (
        (
            "CM",
            "CMTRT",
            {"recommended_role": "ip_dose_adjustment"},
            "non-investigational",
        ),
        (
            "AE",
            "AETERM",
            {"recommended_role": "SDTM.AETERM"},
            "standards_reference",
        ),
        (
            "AE",
            "AETERM",
            {"field_kind": "standardized_coded"},
            "source_fields",
        ),
        (
            "AE",
            "AETERM",
            {
                "field_kind": "deterministic_derived",
                "derivation_lineage": {"source_fields": ["AETERM"]},
            },
            "formula",
        ),
        (
            "AE",
            "AETERM",
            {
                "field_kind": "standardized_coded",
                "derivation_lineage": {
                    "source_fields": ["AETERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            },
            "own lineage source",
        ),
        (
            "AE",
            "AETERM",
            {
                "field_kind": "standardized_coded",
                "derivation_lineage": {
                    "source_fields": ["AESTDAT"],
                    "coding_system": "unspecified coding system",
                    "dictionary_version_field": "MDRAVER",
                },
            },
            "explicit coding system",
        ),
        (
            "AE",
            "AETERM",
            {
                "field_kind": "standardized_coded",
                "derivation_lineage": {
                    "source_fields": ["AESTDAT"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "AESTDAT",
                },
            },
            "independent version field",
        ),
        (
            "AE",
            "AETERM",
            {
                "field_kind": "deterministic_derived",
                "derivation_lineage": {
                    "source_fields": ["AESTDAT"],
                    "formula": "normalize(AESTDAT)",
                },
            },
            "explicit user confirmation",
        ),
        (
            "AE",
            "AETERM",
            {
                "field_kind": "deterministic_derived",
                "derivation_lineage": {
                    "source_fields": ["AESTDAT"],
                    "formula": "待确认后基于 AESTDAT 计算",
                    "user_confirmed": True,
                },
            },
            "explicit formula",
        ),
    )
    for index, (domain, source_field, patch, error) in enumerate(
        invalid_edits,
        start=1,
    ):
        with pytest.raises(ValueError, match=error):
            mapping_repository.edit_field(
                "project-alpha",
                draft.draft_id,
                domain=domain,
                source_field=source_field,
                patch=patch,
                expected_version=1,
                actor="medical-manager",
                idempotency_key=f"invalid-edit-{index}",
            )


def test_user_can_explicitly_confirm_a_deterministic_mapping_formula(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )

    edited = mapping_repository.edit_field(
        "project-alpha",
        draft.draft_id,
        domain="AE",
        source_field="AESTDAT",
        patch={
            "field_kind": "deterministic_derived",
            "derivation_lineage": {
                "source_fields": ["AETERM"],
                "formula": "normalize_date(AETERM)",
                "user_confirmed": True,
            },
            "uncertainty": "医学经理已核对来源字段和固定公式。",
            "user_action": "后续版本变更时重新核对公式。",
        },
        expected_version=draft.version,
        actor="medical-manager",
        idempotency_key="confirm-derived-formula-edit",
    )

    field = next(
        item
        for item in edited.fields
        if (item.domain, item.source_field) == ("AE", "AESTDAT")
    )
    assert field.field_kind.value == "deterministic_derived"
    assert field.derivation_lineage == {
        "source_fields": ["AETERM"],
        "formula": "normalize_date(AETERM)",
        "user_confirmed": True,
    }


def test_confirmation_revalidates_persisted_field_semantics(
    repositories,
) -> None:
    path, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    with sqlite3.connect(path) as connection:
        fields = json.loads(
            connection.execute(
                """
                SELECT fields_json FROM monitoring_mapping_drafts
                WHERE draft_id = ?
                """,
                (draft.draft_id,),
            ).fetchone()[0]
        )
        fields[0]["recommended_role"] = "SDTM.AETERM"
        connection.execute(
            """
            UPDATE monitoring_mapping_drafts SET fields_json = ?
            WHERE draft_id = ?
            """,
            (json.dumps(fields), draft.draft_id),
        )

    with pytest.raises(ValueError, match="standards_reference"):
        mapping_repository.confirm(
            "project-alpha",
            draft.draft_id,
            expected_version=1,
            confirmed_by="medical-manager",
            confirmation_reason="确认",
            idempotency_key="confirm-tampered-fields",
        )
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM monitoring_mapping_revisions"
            ).fetchone()[0]
            == 0
        )


def test_explicit_confirmation_creates_immutable_revision_with_provenance(
    repositories,
) -> None:
    path, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    assert draft.status == MonitoringMappingDraftStatus.DRAFT

    revision = mapping_repository.confirm(
        "project-alpha",
        draft.draft_id,
        expected_version=1,
        confirmed_by="medical-manager",
        confirmation_reason="已逐字段核对并确认正式映射",
        idempotency_key="confirm-batch-001",
    )
    assert revision.mapping_revision.startswith("monmaprev_")
    assert revision.fields == draft.fields
    assert revision.field_sources == draft.field_sources
    semantic_quality = mapping_repository.semantic_quality(
        "project-alpha",
        draft.draft_id,
    )
    assert revision.semantic_quality_report == semantic_quality.as_payload()
    assert (
        revision.semantic_quality_report_sha256
        == semantic_quality.report_sha256
    )
    assert revision.semantic_quality_report["status"] in {
        "passed",
        "pass_with_warnings",
    }
    confirmed = mapping_repository.get_draft(
        "project-alpha",
        draft.draft_id,
    )
    assert confirmed.status == MonitoringMappingDraftStatus.CONFIRMED
    assert confirmed.confirmed_revision_id == revision.mapping_revision

    repeated = mapping_repository.confirm(
        "project-alpha",
        draft.draft_id,
        expected_version=1,
        confirmed_by="medical-manager",
        confirmation_reason="已逐字段核对并确认正式映射",
        idempotency_key="confirm-batch-001",
    )
    assert repeated == revision
    assert mapping_repository.get_revision(
        "project-alpha",
        revision.mapping_revision,
    ) == revision

    with pytest.raises(MonitoringMappingStateConflictError):
        mapping_repository.edit_field(
            "project-alpha",
            draft.draft_id,
            domain="AE",
            source_field="AETERM",
            patch={"confidence": 0.99},
            expected_version=1,
            actor="medical-manager",
            idempotency_key="edit-after-confirm",
        )
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                """
                UPDATE monitoring_mapping_revisions
                SET confirmation_reason = 'tampered'
                WHERE mapping_revision = ?
                """,
                (revision.mapping_revision,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="forbidden"):
            connection.execute(
                """
                DELETE FROM monitoring_mapping_drafts WHERE draft_id = ?
                """,
                (draft.draft_id,),
            )


def test_persisted_mapping_revision_content_tamper_is_rejected_on_read(
    repositories,
) -> None:
    path, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    revision = mapping_repository.confirm(
        "project-alpha",
        draft.draft_id,
        expected_version=draft.version,
        confirmed_by="medical-manager",
        confirmation_reason="已核对映射来源",
        idempotency_key="confirm-tamper-read",
    )
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER trg_mapping_revision_no_update")
        fields = json.loads(
            connection.execute(
                "SELECT fields_json FROM monitoring_mapping_revisions "
                "WHERE mapping_revision = ?",
                (revision.mapping_revision,),
            ).fetchone()[0]
        )
        fields[0]["confidence"] = 0.77
        connection.execute(
            "UPDATE monitoring_mapping_revisions SET fields_json = ? "
            "WHERE mapping_revision = ?",
            (json.dumps(fields), revision.mapping_revision),
        )

    reopened = MonitoringMappingDraftRepository(path)
    with pytest.raises(
        MonitoringMappingStateConflictError,
        match="mapping revision identity mismatch",
    ):
        reopened.get_revision("project-alpha", revision.mapping_revision)


@pytest.mark.parametrize("tamper", ("source_payload", "report_shape", "actor"))
def test_persisted_mapping_revision_read_shape_is_rejected(
    repositories,
    tamper: str,
) -> None:
    path, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    revision = mapping_repository.confirm(
        "project-alpha",
        draft.draft_id,
        expected_version=draft.version,
        confirmed_by="medical-manager",
        confirmation_reason="已核对映射来源",
        idempotency_key=f"confirm-revision-shape-{tamper}",
    )
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER trg_mapping_revision_no_update")
        if tamper == "source_payload":
            payload = json.loads(
                connection.execute(
                    "SELECT field_sources_json FROM monitoring_mapping_revisions "
                    "WHERE mapping_revision = ?",
                    (revision.mapping_revision,),
                ).fetchone()[0]
            )
            payload[0]["unexpected"] = True
            connection.execute(
                "UPDATE monitoring_mapping_revisions SET field_sources_json = ? "
                "WHERE mapping_revision = ?",
                (json.dumps(payload), revision.mapping_revision),
            )
        elif tamper == "report_shape":
            connection.execute(
                "UPDATE monitoring_mapping_revisions "
                "SET semantic_quality_report_json = ? "
                "WHERE mapping_revision = ?",
                (json.dumps([]), revision.mapping_revision),
            )
        else:
            connection.execute(
                "UPDATE monitoring_mapping_revisions SET confirmed_by = ? "
                "WHERE mapping_revision = ?",
                ("", revision.mapping_revision),
            )

    reopened = MonitoringMappingDraftRepository(path)
    with pytest.raises(
        MonitoringMappingStateConflictError,
        match="persisted mapping revision is invalid",
    ):
        reopened.get_revision("project-alpha", revision.mapping_revision)


def test_persisted_mapping_draft_input_revision_tamper_is_rejected_on_read(
    repositories,
) -> None:
    path, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT input_revision_json FROM monitoring_mapping_drafts "
            "WHERE draft_id = ?",
            (draft.draft_id,),
        ).fetchone()
        input_revision = json.loads(row[0])
        input_revision["mapping_revision"] = "tampered-mapping-revision"
        connection.execute(
            "UPDATE monitoring_mapping_drafts SET input_revision_json = ? "
            "WHERE draft_id = ?",
            (json.dumps(input_revision), draft.draft_id),
        )

    with pytest.raises(
        MonitoringMappingStateConflictError,
        match="input revision hash mismatch",
    ):
        mapping_repository.get_draft("project-alpha", draft.draft_id)


def test_persisted_mapping_draft_anchor_tamper_is_rejected_on_read(
    repositories,
) -> None:
    path, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_mapping_drafts SET full_profile_sha256 = ? "
            "WHERE draft_id = ?",
            ("d" * 64, draft.draft_id),
        )

    with pytest.raises(
        MonitoringMappingStateConflictError,
        match="anchor identity mismatch",
    ):
        mapping_repository.get_draft("project-alpha", draft.draft_id)


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("candidate_content_sha256", "A" * 64),
        ("prompt_version", ""),
        ("evidence_ids_json", json.dumps({"evidence": "ev-1-1"})),
    ),
)
def test_persisted_mapping_field_source_shape_is_rejected_on_read(
    repositories,
    column: str,
    value: str,
) -> None:
    path, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER trg_mapping_sources_no_update")
        connection.execute(
            f"UPDATE monitoring_mapping_field_sources SET {column} = ? "
            "WHERE project_id = ? AND draft_id = ?",
            (value, "project-alpha", draft.draft_id),
        )

    reopened = MonitoringMappingDraftRepository(path)
    with pytest.raises(
        MonitoringMappingStateConflictError,
        match="persisted mapping source lineage is invalid",
    ):
        reopened.get_draft("project-alpha", draft.draft_id)


def test_confirmation_rejects_blocked_semantic_quality(
    repositories,
) -> None:
    path, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    blocked = mapping_repository.edit_field(
        "project-alpha",
        draft.draft_id,
        domain="AE",
        source_field="AETERM",
        patch={
            "field_kind": "source_metadata",
            "recommended_role": "unclassified_metadata",
        },
        expected_version=draft.version,
        actor="medical-manager",
        idempotency_key="make-semantic-blocker",
    )

    quality = mapping_repository.semantic_quality(
        "project-alpha",
        blocked.draft_id,
    )
    assert quality.status.value == "blocked"
    assert any(
        item.rule_id == "G-ROLE-002"
        for item in quality.finding_groups
    )

    with pytest.raises(
        MonitoringMappingStateConflictError,
        match="semantic quality gate is blocked",
    ):
        mapping_repository.confirm(
            "project-alpha",
            blocked.draft_id,
            expected_version=blocked.version,
            confirmed_by="medical-manager",
            confirmation_reason="阻断项不得被确认。",
            idempotency_key="confirm-blocked-semantic-quality",
        )
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM monitoring_mapping_revisions"
            ).fetchone()[0]
            == 0
        )


def test_assembly_rejects_strong_scale_total_procedure_misclassification(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    field_roles = (
        ("SCALE1", "scale.item_score"),
        ("SCALE2", "scale.item_score"),
        ("SCALETOTAL", "study_procedure_number"),
    )
    for index, (field, role) in enumerate(field_roles, start=1):
        _seed_chunk(
            ai_repository,
            domain="SCALE_FORM",
            chunk_index=index,
            chunk_total=3,
            fields=(field,),
            domain_field_count=3,
            full_field_count=3,
            expected_domains=("SCALE_FORM",),
            mapping_overrides={
                field: {"recommended_role": role},
            },
        )

    with pytest.raises(
        MonitoringMappingSourceStateError,
        match="scale total or score",
    ):
        mapping_repository.assemble(
            "project-alpha",
            "batch-001",
            PROFILE_HASH,
        )


def test_assemble_quarantines_only_low_confidence_unresolved_source_role(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_chunk(
        ai_repository,
        domain="EX",
        chunk_index=1,
        chunk_total=1,
        fields=("EXPDOSE",),
        domain_field_count=1,
        full_field_count=1,
        expected_domains=("EX",),
        mapping_overrides={
            "EXPDOSE": {
                "recommended_role": (
                    "ip_planned_or_administered_dose_with_unit_text"
                ),
                "field_kind": "source_collected",
                "confidence": 0.62,
                "uncertainty": (
                    "无法仅凭字段画像区分计划剂量与实际给药剂量。"
                ),
                "user_action": "请结合数据字典确认具体剂量语义。",
                "related_fields": ["EXDOSE", "EXDOSEO"],
            }
        },
    )

    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )

    assert len(draft.fields) == 1
    mapped = draft.fields[0]
    assert mapped.field_kind.value == "unmapped"
    assert (
        mapped.recommended_role
        == "ip_planned_or_administered_dose_with_unit_text"
    )
    assert mapped.confidence == 0.62
    assert mapped.evidence_ids
    quality = mapping_repository.semantic_quality(
        "project-alpha",
        draft.draft_id,
    )
    assert quality.status.value == "pass_with_warnings"
    assert quality.activation_disposition.value == "activate_restricted"
    assert not any(
        item.rule_id == "G-ROLE-002"
        for item in quality.finding_groups
    )
    assert any(
        item.rule_id == "G-CMIP-003"
        for item in quality.finding_groups
    )


def test_assemble_normalizes_known_export_context_without_changing_candidate(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _, candidates = _seed_chunk(
        ai_repository,
        domain="LBCHEM",
        chunk_index=1,
        chunk_total=1,
        fields=("FORM", "PAGE", "LINE", "LBNAM"),
        domain_field_count=4,
        full_field_count=4,
        expected_domains=("LBCHEM",),
        mapping_overrides={
            "FORM": {
                "recommended_role": "edc_form_display_name",
                "field_kind": "source_metadata",
            },
            "PAGE": {
                "recommended_role": "form_page_identifier",
                "field_kind": "source_collected",
            },
            "LINE": {
                "recommended_role": "record_sequence_number",
                "field_kind": "source_metadata",
            },
            "LBNAM": {
                "recommended_role": "lab_panel_specimen_identifier_label",
                "field_kind": "source_collected",
                "confidence": 0.68,
            },
        },
    )

    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )

    mapped = {item.source_field: item for item in draft.fields}
    assert {
        key: (item.recommended_role, item.field_kind.value)
        for key, item in mapped.items()
    } == {
        "FORM": ("form_name", "source_metadata"),
        "PAGE": ("page_name", "source_metadata"),
        "LINE": ("record_line_number", "source_metadata"),
        "LBNAM": ("laboratory_configuration_name", "source_metadata"),
    }
    assert all(
        "原独立 AI 判断保留在候选审计记录中" in item.uncertainty
        for item in mapped.values()
    )
    original = {
        item["source_field"]: item
        for item in candidates[0].structured_payload["field_mappings"]
    }
    assert original["PAGE"]["field_kind"] == "source_collected"
    assert (
        original["LBNAM"]["recommended_role"]
        == "lab_panel_specimen_identifier_label"
    )


def test_assemble_normalizes_declared_coding_support_without_changing_candidate(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _, candidates = _seed_chunk(
        ai_repository,
        domain="AE",
        chunk_index=1,
        chunk_total=1,
        fields=("MDRAVER", "MDRALANG"),
        domain_field_count=2,
        full_field_count=2,
        expected_domains=("AE",),
        mapping_overrides={
            "MDRAVER": {
                "recommended_role": "meddra_dictionary_version",
                "field_kind": "source_collected",
            },
            "MDRALANG": {
                "recommended_role": "meddra_language",
                "field_kind": "source_collected",
            },
        },
    )

    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )

    mapped = {item.source_field: item for item in draft.fields}
    assert all(
        item.field_kind.value == "source_metadata"
        for item in mapped.values()
    )
    assert all(
        "coding_support_metadata_closed" in item.quality_gate_actions
        for item in mapped.values()
    )
    assert all(
        "原候选字段性质保留在候选审计记录中" in item.uncertainty
        for item in mapped.values()
    )
    original = {
        item["source_field"]: item
        for item in candidates[0].structured_payload["field_mappings"]
    }
    assert original["MDRAVER"]["field_kind"] == "source_collected"
    assert original["MDRALANG"]["field_kind"] == "source_collected"


def test_assemble_quarantines_multi_action_ip_role_without_changing_candidate(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _, candidates = _seed_chunk(
        ai_repository,
        domain="DAB",
        chunk_index=1,
        chunk_total=1,
        fields=("IPCOMP", "IPCOMP_UNIT"),
        domain_field_count=2,
        full_field_count=2,
        expected_domains=("DAB",),
        mapping_overrides={
            "IPCOMP": {
                "recommended_role": "drug_return_compliance_percent",
                "field_kind": "source_collected",
                "confidence": 0.9,
                "uncertainty": "字段语义需结合数据字典确认。",
                "user_action": "请确认。",
            },
            "IPCOMP_UNIT": {
                "recommended_role": "drug_return_compliance_percent_unit",
                "field_kind": "source_collected",
                "confidence": 0.9,
                "uncertainty": "字段语义需结合数据字典确认。",
                "user_action": "请确认。",
            },
        },
    )

    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )

    mapped = {item.source_field: item for item in draft.fields}
    assert set(mapped) == {"IPCOMP", "IPCOMP_UNIT"}
    for field in mapped.values():
        assert field.recommended_role == "clinical.source_other"
        assert field.field_kind.value == "source_collected"
        assert field.domain == "DAB"
        assert field.confidence == 0.9
        assert field.evidence_ids
        assert "multi_action_ip_quarantined" in field.quality_gate_actions
        assert "不得" in field.user_action
    # The immutable candidate keeps the original multi-action role and all
    # source/evidence identity byte-for-byte.
    persisted = ai_repository.candidates(
        "project-alpha",
        candidates[0].job_id,
    )
    assert persisted[0].structured_payload["field_mappings"] == (
        candidates[0].structured_payload["field_mappings"]
    )
    original = {
        item["source_field"]: item
        for item in candidates[0].structured_payload["field_mappings"]
    }
    assert (
        original["IPCOMP"]["recommended_role"]
        == "drug_return_compliance_percent"
    )
    quality = mapping_repository.semantic_quality(
        "project-alpha",
        draft.draft_id,
    )
    rule_ids = {item.rule_id for item in quality.finding_groups}
    assert quality.status.value == "passed"
    assert "G-CMIP-002" not in rule_ids
    assert "G-ROLE-002" not in rule_ids


def test_assemble_downgrades_unclosed_standardized_chain_to_source_values(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _, candidates = _seed_chunk(
        ai_repository,
        domain="PR",
        chunk_index=1,
        chunk_total=1,
        fields=("HLTCODE", "HLTTERM", "PTCODE", "MDRAVER"),
        domain_field_count=4,
        full_field_count=4,
        expected_domains=("PR",),
        mapping_overrides={
            "HLTCODE": {
                "recommended_role": "meddra_hlt_code",
                "field_kind": "standardized_coded",
                "derivation_lineage": {
                    "source_fields": ["HLTTERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            },
            "HLTTERM": {
                "recommended_role": "meddra_hlt_term",
                "field_kind": "standardized_coded",
                "derivation_lineage": {
                    "source_fields": ["HLTCODE"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            },
            "PTCODE": {
                "recommended_role": "meddra_pt_code",
                "field_kind": "source_collected",
                "derivation_lineage": None,
            },
            "MDRAVER": {
                # Marker-declared but not a closed support role: assembly must
                # not promote it, so the HLT claims fail the version contract
                # and are downgraded as one fail-closed source-set operation.
                "recommended_role": "dictionary_version",
                "field_kind": "source_collected",
            },
        },
    )

    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )

    by_field = {item.source_field: item for item in draft.fields}
    assert by_field["HLTCODE"].field_kind.value == "source_collected"
    assert by_field["HLTTERM"].field_kind.value == "source_collected"
    assert by_field["HLTCODE"].derivation_lineage is None
    assert (
        "incomplete_coding_downgraded_to_source_collected"
        in by_field["HLTCODE"].quality_gate_actions
    )
    assert by_field["PTCODE"].field_kind.value == "source_collected"
    assert by_field["MDRAVER"].field_kind.value == "source_collected"
    assert not any(
        item.field_kind.value == "standardized_coded" for item in draft.fields
    )
    persisted = ai_repository.candidates(
        "project-alpha",
        candidates[0].job_id,
    )
    assert persisted[0].structured_payload["field_mappings"] == (
        candidates[0].structured_payload["field_mappings"]
    )
    quality = mapping_repository.semantic_quality(
        "project-alpha",
        draft.draft_id,
    )
    rule_ids = {item.rule_id for item in quality.finding_groups}
    assert "G-CODE-003" not in rule_ids
    assert "G-CODE-001" not in rule_ids
    assert "G-CODE-002" in rule_ids
    assert quality.status.value == "pass_with_warnings"


def test_assemble_keeps_closed_meddra_chain_standardized_without_anchor(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_chunk(
        ai_repository,
        domain="AE",
        chunk_index=1,
        chunk_total=1,
        fields=("PTCODE", "PTTERM", "MDRAVER"),
        domain_field_count=3,
        full_field_count=3,
        expected_domains=("AE",),
        mapping_overrides={
            "PTCODE": {
                "recommended_role": "meddra_pt_code",
                "field_kind": "standardized_coded",
                "derivation_lineage": {
                    "source_fields": ["PTTERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            },
            "PTTERM": {
                "recommended_role": "meddra_pt_term",
                "field_kind": "standardized_coded",
                "derivation_lineage": {
                    "source_fields": ["PTCODE"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            },
            "MDRAVER": {
                "recommended_role": "meddra_dictionary_version",
                "field_kind": "source_metadata",
            },
        },
    )

    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )

    by_field = {item.source_field: item for item in draft.fields}
    assert by_field["PTCODE"].field_kind.value == "standardized_coded"
    assert by_field["PTTERM"].field_kind.value == "standardized_coded"
    assert (
        by_field["PTCODE"].derivation_lineage["dictionary_version_field"]
        == "MDRAVER"
    )
    quality = mapping_repository.semantic_quality(
        "project-alpha",
        draft.draft_id,
    )
    rule_ids = {item.rule_id for item in quality.finding_groups}
    assert "G-CODE-003" not in rule_ids
    assert "G-CODE-001" not in rule_ids


@pytest.mark.parametrize(
    ("confidence", "recommended_role"),
    [
        (0.70, "ip_project_specific_high_confidence_role"),
        (0.95, "ip_project_specific_high_confidence_role"),
    ],
)
def test_assemble_does_not_quarantine_material_unknown_role_conflicts(
    repositories,
    confidence: float,
    recommended_role: str,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_chunk(
        ai_repository,
        domain="EX",
        chunk_index=1,
        chunk_total=1,
        fields=("EXPDOSE",),
        domain_field_count=1,
        full_field_count=1,
        expected_domains=("EX",),
        mapping_overrides={
            "EXPDOSE": {
                "recommended_role": recommended_role,
                "field_kind": "source_collected",
                "confidence": confidence,
                "uncertainty": "仍需核对字段语义和动作边界。",
                "user_action": "请结合数据字典确认。",
            }
        },
    )

    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )

    assert draft.fields[0].field_kind.value == "source_collected"
    quality = mapping_repository.semantic_quality(
        "project-alpha",
        draft.draft_id,
    )
    assert quality.status.value == "blocked"
    assert any(
        item.rule_id == "G-ROLE-002"
        for item in quality.finding_groups
    )


def test_confirmation_requires_current_version_and_unique_idempotency_meaning(
    repositories,
) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    with pytest.raises(MonitoringMappingStateConflictError, match="CAS"):
        mapping_repository.confirm(
            "project-alpha",
            draft.draft_id,
            expected_version=2,
            confirmed_by="medical-manager",
            confirmation_reason="确认",
            idempotency_key="confirm-batch-001",
        )
    mapping_repository.confirm(
        "project-alpha",
        draft.draft_id,
        expected_version=1,
        confirmed_by="medical-manager",
        confirmation_reason="确认",
        idempotency_key="confirm-batch-001",
    )
    with pytest.raises(MonitoringMappingStateConflictError, match="reused"):
        mapping_repository.confirm(
            "project-alpha",
            draft.draft_id,
            expected_version=1,
            confirmed_by="another-user",
            confirmation_reason="另一含义",
            idempotency_key="confirm-batch-001",
        )


def test_confirmation_revalidates_source_after_draft_assembly(
    repositories,
) -> None:
    path, ai_repository, mapping_repository = repositories
    seeded = _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    target_candidate = seeded[0][1][0]
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE monitoring_ai_candidates SET status = ?
            WHERE candidate_id = ?
            """,
            (
                MonitoringAiCandidateStatus.SUPERSEDED.value,
                target_candidate.candidate_id,
            ),
        )

    with pytest.raises(
        MonitoringMappingSourceStateError,
        match="not accepted",
    ):
        mapping_repository.confirm(
            "project-alpha",
            draft.draft_id,
            expected_version=1,
            confirmed_by="medical-manager",
            confirmation_reason="不得确认已过期来源",
            idempotency_key="confirm-stale-source",
        )
    assert (
        mapping_repository.get_draft("project-alpha", draft.draft_id).status
        == MonitoringMappingDraftStatus.DRAFT
    )


def test_project_boundary_applies_to_read_edit_and_confirm(repositories) -> None:
    _, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository, project_id="project-alpha")
    _seed_complete_source(ai_repository, project_id="project-beta")
    alpha = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    beta = mapping_repository.assemble(
        "project-beta",
        "batch-001",
        PROFILE_HASH,
    )
    assert alpha.draft_id != beta.draft_id

    with pytest.raises(MonitoringMappingNotFoundError):
        mapping_repository.get_draft("project-beta", alpha.draft_id)
    with pytest.raises(MonitoringMappingNotFoundError):
        mapping_repository.edit_field(
            "project-beta",
            alpha.draft_id,
            domain="AE",
            source_field="AETERM",
            patch={"confidence": 0.99},
            expected_version=1,
            actor="medical-manager",
            idempotency_key="cross-project-edit",
        )
    with pytest.raises(MonitoringMappingNotFoundError):
        mapping_repository.confirm(
            "project-beta",
            alpha.draft_id,
            expected_version=1,
            confirmed_by="medical-manager",
            confirmation_reason="不得跨项目确认",
            idempotency_key="cross-project-confirm",
        )


def test_repository_without_ai_source_tables_fails_closed(tmp_path: Path) -> None:
    repository = MonitoringMappingDraftRepository(tmp_path / "mapping-only.sqlite3")
    with pytest.raises(
        MonitoringMappingSourceStateError,
        match="source tables",
    ):
        repository.assemble("project-alpha", "batch-001", PROFILE_HASH)


def test_source_payload_hash_and_candidate_identity_are_revalidated(
    repositories,
) -> None:
    path, ai_repository, mapping_repository = repositories
    seeded = _seed_complete_source(ai_repository)
    target_job = seeded[0][0]
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT input_payload_json FROM monitoring_ai_jobs
            WHERE job_id = ?
            """,
            (target_job.job_id,),
        ).fetchone()
        payload = json.loads(row[0])
        payload["field_profile"]["row_count"] = 999
        connection.execute(
            """
            UPDATE monitoring_ai_jobs SET input_payload_json = ?
            WHERE job_id = ?
            """,
            (json.dumps(payload), target_job.job_id),
        )
    with pytest.raises(
        MonitoringMappingSourceStateError,
        match="payload hash",
    ):
        mapping_repository.assemble(
            "project-alpha",
            "batch-001",
            PROFILE_HASH,
        )

    path_2 = path.parent / "candidate-identity.sqlite3"
    ai_2 = MonitoringAiRepository(path_2)
    mapping_2 = MonitoringMappingDraftRepository(path_2)
    seeded_2 = _seed_complete_source(ai_2)
    candidate = seeded_2[0][1][0]
    with sqlite3.connect(path_2) as connection:
        row = connection.execute(
            """
            SELECT candidate_json FROM monitoring_ai_candidates
            WHERE candidate_id = ?
            """,
            (candidate.candidate_id,),
        ).fetchone()
        payload = json.loads(row[0])
        payload["candidate_id"] = "candidate-substituted"
        connection.execute(
            """
            UPDATE monitoring_ai_candidates SET candidate_json = ?
            WHERE candidate_id = ?
            """,
            (json.dumps(payload), candidate.candidate_id),
        )
    with pytest.raises(
        MonitoringMappingSourceStateError,
        match="does not match",
    ):
        mapping_2.assemble("project-alpha", "batch-001", PROFILE_HASH)


def test_source_matching_rejects_noncanonical_persisted_profile_digest(
    repositories,
) -> None:
    path, ai_repository, mapping_repository = repositories
    seeded = _seed_complete_source(ai_repository)
    target_job = seeded[0][0]
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT input_payload_json FROM monitoring_ai_jobs WHERE job_id = ?",
            (target_job.job_id,),
        ).fetchone()
        payload = json.loads(row[0])
        payload["field_profile"]["full_profile_sha256"] = PROFILE_HASH.upper()
        connection.execute(
            "UPDATE monitoring_ai_jobs SET input_payload_json = ?, input_payload_sha256 = ? WHERE job_id = ?",
            (json.dumps(payload), content_sha256(payload), target_job.job_id),
        )

    with pytest.raises(
        MonitoringMappingSourceStateError,
        match="missing or extra chunk slots",
    ):
        mapping_repository.assemble(
            "project-alpha",
            "batch-001",
            PROFILE_HASH,
        )


def test_source_matching_rejects_nonstring_persisted_profile_input_digest(
    repositories,
) -> None:
    path, ai_repository, mapping_repository = repositories
    seeded = _seed_complete_source(ai_repository)
    target_job = seeded[0][0]
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT input_payload_json FROM monitoring_ai_jobs WHERE job_id = ?",
            (target_job.job_id,),
        ).fetchone()
        payload = json.loads(row[0])
        payload["field_profile"]["full_input_sha256"] = int("1" * 64)
        connection.execute(
            "UPDATE monitoring_ai_jobs SET input_payload_json = ?, input_payload_sha256 = ? WHERE job_id = ?",
            (json.dumps(payload), content_sha256(payload), target_job.job_id),
        )

    with pytest.raises(
        MonitoringMappingSourceStateError,
        match="source hash is not canonical",
    ):
        mapping_repository.assemble(
            "project-alpha",
            "batch-001",
            PROFILE_HASH,
        )


def test_reassembly_detects_candidate_content_change_after_draft(
    repositories,
) -> None:
    path, ai_repository, mapping_repository = repositories
    seeded = _seed_complete_source(ai_repository)
    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    target_candidate = seeded[0][1][0]
    source = next(
        item
        for item in draft.field_sources
        if item.candidate_id == target_candidate.candidate_id
    )
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT candidate_json FROM monitoring_ai_candidates
            WHERE candidate_id = ?
            """,
            (target_candidate.candidate_id,),
        ).fetchone()
        payload = json.loads(row[0])
        assert source.candidate_content_sha256
        payload["title"] = "被修改的候选标题"
        connection.execute(
            """
            UPDATE monitoring_ai_candidates SET candidate_json = ?
            WHERE candidate_id = ?
            """,
            (json.dumps(payload), target_candidate.candidate_id),
        )

    with pytest.raises(
        MonitoringMappingStateConflictError,
        match="source set changed",
    ):
        mapping_repository.assemble(
            "project-alpha",
            "batch-001",
            PROFILE_HASH,
        )


def test_accepted_candidate_is_not_a_formal_mapping(repositories) -> None:
    path, ai_repository, mapping_repository = repositories
    _seed_complete_source(ai_repository)
    with sqlite3.connect(path) as connection:
        statuses = {
            row[0]
            for row in connection.execute(
                "SELECT status FROM monitoring_ai_candidates"
            ).fetchall()
        }
        assert statuses == {MonitoringAiCandidateStatus.ACCEPTED.value}
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM monitoring_mapping_revisions"
            ).fetchone()[0]
            == 0
        )

    draft = mapping_repository.assemble(
        "project-alpha",
        "batch-001",
        PROFILE_HASH,
    )
    assert draft.status == MonitoringMappingDraftStatus.DRAFT
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM monitoring_mapping_revisions"
            ).fetchone()[0]
            == 0
        )
        serialized = json.loads(
            connection.execute(
                """
                SELECT fields_json FROM monitoring_mapping_drafts
                WHERE draft_id = ?
                """,
                (draft.draft_id,),
            ).fetchone()[0]
        )
        assert len(serialized) == 3
