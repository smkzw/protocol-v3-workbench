from __future__ import annotations

from dataclasses import replace
import json
import sqlite3
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
    content_sha256,
)
from services.api.app.monitoring_ai_repository import MonitoringAiRepository
from services.api.app.monitoring_mapping_activation import (
    MonitoringBatchMappingBindingStatus,
    MonitoringMappingActivationConflictError,
    MonitoringMappingActivationError,
    MonitoringMappingActivationNotFoundError,
    MonitoringMappingActivationService,
    MonitoringMappingActivationSourceError,
    MonitoringMappingCapabilityUnavailableError,
    MonitoringMappingCompatibilityStatus,
)
from services.api.app.monitoring_mapping_draft_repository import (
    MonitoringMappingDraftRepository,
)


PROJECT_ID = "project-alpha"
SOURCE_HASH = "a" * 64
PROFILE_HASH = "b" * 64
INPUT_HASH = "c" * 64
NOW = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)


def _mapping(domain: str, field: str, evidence_id: str) -> dict[str, object]:
    return {
        "domain": domain,
        "source_field": field,
        "recommended_role": (
            "adverse_event_term"
            if field == "AETERM"
            else "adverse_event_start_date"
        ),
        "field_kind": "source_collected",
        "confidence": 0.91,
        "uncertainty": "字段语义需结合项目数据字典持续核对。",
        "user_action": "确认该字段角色是否符合项目实际采集定义。",
        "related_fields": [],
        "evidence_ids": [evidence_id],
        "standards_reference": None,
        "derivation_lineage": None,
    }


def _seed_confirmed_mapping(
    tmp_path: Path,
    *,
    restricted_coding: bool = False,
) -> tuple[
    MonitoringMappingDraftRepository,
    str,
]:
    database = tmp_path / "mapping.sqlite3"
    ai_repository = MonitoringAiRepository(
        database,
        clock=lambda: NOW,
        lease_seconds=300,
    )
    mapping_repository = MonitoringMappingDraftRepository(
        database,
        clock=lambda: NOW,
    )
    revision = MonitoringAiInputRevision(
        project_id=PROJECT_ID,
        batch_revision="batch-source-v1",
        mapping_revision="pre-mapping-v1",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id="source-listing",
                source_content_sha256=SOURCE_HASH,
            ),
        ),
    )
    fields = [
        {
            "domain": "AE",
            "field": "AETERM",
            "total_rows": 100,
            "non_empty_count": 100,
            "null_rate": 0.0,
            "inferred_type": "string",
            "unique_value_count": 20,
            "top_values": [],
            "representative_values": [],
            "anomaly_examples": [],
        },
        {
            "domain": "AE",
            "field": "AESTDTC",
            "total_rows": 100,
            "non_empty_count": 100,
            "null_rate": 0.0,
            "inferred_type": "date",
            "unique_value_count": 30,
            "top_values": [],
            "representative_values": [],
            "anomaly_examples": [],
        },
    ]
    payload = {
        "schema_version": "monitoring_ai_v1",
        "field_profile": {
            "schema_version": "monitoring_ai_field_profile_v2",
            "scope": "complete_profile_chunk",
            "project_id": PROJECT_ID,
            "batch_id": "batch-source",
            "batch_revision": 1,
            "expected_domains": ["AE"],
            "full_profile_sha256": PROFILE_HASH,
            "full_input_sha256": INPUT_HASH,
            "full_field_count": 2,
            "domain": "AE",
            "domain_field_count": 2,
            "chunk_index": 1,
            "chunk_total": 1,
            "chunk_size_limit": 12,
            "fields": fields,
        },
    }
    request = MonitoringAiJobCreate(
        project_id=PROJECT_ID,
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        input_revision=revision,
        input_payload=payload,
        prompt_version="monitoring-listing-field-mapping-v6",
        profile_id="activation-test",
        provider="test-provider",
        requested_model="test-model",
        max_attempts=2,
        business_key="listing-field-mapping:batch-source:AE:0001-of-0001",
    )
    job = ai_repository.create_or_get(request)
    running = ai_repository.claim_next("worker-activation")
    assert running is not None and running.job_id == job.job_id
    evidence = tuple(
        MonitoringAiEvidence(
            evidence_id=f"evidence-{index}",
            source_entry_id="source-listing",
            source_content_sha256=SOURCE_HASH,
            locator=f"profile://AE/{field['field']}",
            raw_fields={
                "domain": "AE",
                "field": field["field"],
                "inferred_type": field["inferred_type"],
            },
            input_revision_sha256=running.input_revision_sha256,
        )
        for index, field in enumerate(fields, start=1)
    )
    candidate = MonitoringAiCandidate(
        candidate_id="candidate-activation",
        job_id=running.job_id,
        project_id=PROJECT_ID,
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        candidate_type="listing_field_mapping_set",
        title="字段映射建议",
        structured_payload={
            "field_mappings": [
                _mapping("AE", field["field"], evidence[index].evidence_id)
                for index, field in enumerate(fields)
            ]
        },
        claims=(
            MonitoringAiClaim(
                claim_id="claim-activation",
                kind=MonitoringAiClaimKind.RECOMMENDATION,
                text="建议采用项目中立的字段语义映射。",
                confidence=0.91,
                uncertainty="仍需当前医学用户确认。",
                user_action="校对字段角色后确认。",
                evidence_ids=(evidence[0].evidence_id,),
            ),
        ),
        evidence=evidence,
        input_revision_sha256=running.input_revision_sha256,
        prompt_version=running.prompt_version,
        created_at=NOW,
    )
    ai_repository.complete(
        running,
        owner="worker-activation",
        response_model="test-model",
        raw_output={"candidate_count": 1},
        candidates=(candidate,),
    )
    ai_repository.decide_candidate(
        PROJECT_ID,
        candidate.candidate_id,
        decision=MonitoringAiCandidateStatus.ACCEPTED,
        actor="medical-manager",
        reason="字段映射已逐项校对。",
        current_input_revision_sha256=running.input_revision_sha256,
    )
    draft = mapping_repository.assemble(
        PROJECT_ID,
        "batch-source",
        PROFILE_HASH,
        prompt_version=request.prompt_version,
    )
    if restricted_coding:
        draft = mapping_repository.edit_field(
            PROJECT_ID,
            draft.draft_id,
            domain="AE",
            source_field="AETERM",
            patch={
                "recommended_role": "coding.meddra.pt_term",
                "field_kind": "source_collected",
                "derivation_lineage": None,
                "uncertainty": (
                    "保留来源编码术语，但当前缺少可核验的词典版本血缘。"
                ),
                "user_action": "补充编码体系版本后形成新映射修订。",
            },
            expected_version=draft.version,
            actor="medical-manager",
            idempotency_key="make-restricted-coding-mapping",
        )
    confirmed = mapping_repository.confirm(
        PROJECT_ID,
        draft.draft_id,
        expected_version=draft.version,
        confirmed_by="medical-manager",
        confirmation_reason="正式确认字段映射。",
        idempotency_key="confirm-activation-test",
    )
    return mapping_repository, confirmed.mapping_revision


def test_capability_only_revision_can_activate_with_immutable_restricted_snapshot(
    tmp_path: Path,
) -> None:
    repository, mapping_revision = _seed_confirmed_mapping(
        tmp_path,
        restricted_coding=True,
    )
    revision = repository.get_revision(PROJECT_ID, mapping_revision)
    assert revision.semantic_quality_report["status"] == "pass_with_warnings"
    assert (
        revision.semantic_quality_report["activation_disposition"]
        == "activate_restricted"
    )

    service = MonitoringMappingActivationService(repository, clock=lambda: NOW)
    result = service.activate_confirmed_revision(
        PROJECT_ID,
        mapping_revision,
        expected_project_version=0,
        activated_by="medical-manager",
        activation_reason="启用当前真实映射及其可用能力。",
        idempotency_key="activate-restricted",
    )

    state = result.state
    assert state.activation_disposition == "activate_restricted"
    assert (
        state.semantic_quality_report_sha256
        == revision.semantic_quality_report_sha256
    )
    assert len(state.capability_manifest_sha256) == 64
    assert len(state.effective_capabilities_sha256) == 64
    assert "raw_source_review" in state.effective_capabilities
    assert "subject_timeline" in state.effective_capabilities
    assert "standard_coding_rules" not in state.effective_capabilities
    coding = next(
        item
        for item in state.capability_states
        if item.capability_id == "standard_coding_rules"
    )
    assert coding.state == "blocked_by_quality"
    assert coding.limitation_codes == ("coding_lineage_incomplete",)
    assert (
        service.require_monitoring_capability(
            PROJECT_ID,
            "raw_source_review",
        ).state
        == "ready"
    )
    assert (
        service.require_monitoring_capability(
            PROJECT_ID,
            "subject_timeline",
        ).state
        == "limited"
    )
    with pytest.raises(
        MonitoringMappingCapabilityUnavailableError,
        match="coding_lineage_incomplete",
    ):
        service.require_monitoring_capability(
            PROJECT_ID,
            "standard_coding_rules",
        )
    assert service.list_activation_history(PROJECT_ID) == (state,)


def test_active_capability_snapshot_cannot_be_expanded_outside_revision(
    tmp_path: Path,
) -> None:
    repository, mapping_revision = _seed_confirmed_mapping(
        tmp_path,
        restricted_coding=True,
    )
    service = MonitoringMappingActivationService(repository, clock=lambda: NOW)
    service.activate_confirmed_revision(
        PROJECT_ID,
        mapping_revision,
        expected_project_version=0,
        activated_by="medical-manager",
        activation_reason="启用受限映射。",
        idempotency_key="activate-restricted-tamper-test",
    )
    with sqlite3.connect(service.state_path) as connection:
        current = connection.execute(
            """
            SELECT effective_capabilities_json
            FROM monitoring_mapping_project_state
            WHERE project_id = ?
            """,
            (PROJECT_ID,),
        ).fetchone()[0]
        assert "standard_coding_rules" not in current
        connection.execute(
            """
            UPDATE monitoring_mapping_project_state
            SET effective_capabilities_json =
                '["raw_source_review","standard_coding_rules"]'
            WHERE project_id = ?
            """,
            (PROJECT_ID,),
        )

    with pytest.raises(
        MonitoringMappingActivationSourceError,
        match="capability snapshot",
    ):
        service.get_active_mapping(PROJECT_ID)


@pytest.mark.parametrize("tamper", ("hash", "capabilities", "json"))
def test_persisted_mapping_activation_state_read_shape_is_rejected(
    activated,
    tamper: str,
) -> None:
    service, _repository, mapping_revision, result = activated
    with sqlite3.connect(service.state_path) as connection:
        if tamper == "hash":
            connection.execute(
                "UPDATE monitoring_mapping_project_state "
                "SET mapping_content_sha256 = ? WHERE project_id = ?",
                ("A" * 64, PROJECT_ID),
            )
        elif tamper == "capabilities":
            connection.execute(
                "UPDATE monitoring_mapping_project_state "
                "SET capability_states_json = ? WHERE project_id = ?",
                (json.dumps({"capability_id": "raw_source_review"}), PROJECT_ID),
            )
        else:
            connection.execute(
                "UPDATE monitoring_mapping_project_state "
                "SET capability_states_json = ? WHERE project_id = ?",
                ("not-json", PROJECT_ID),
            )

    with pytest.raises(
        MonitoringMappingActivationError,
        match="persisted mapping activation state",
    ):
        service.get_active_mapping(PROJECT_ID, validate_source=False)


def test_persisted_mapping_activation_operation_state_read_shape_is_rejected(
    activated,
) -> None:
    service, _repository, mapping_revision, result = activated
    with sqlite3.connect(service.state_path) as connection:
        row = connection.execute(
            "SELECT result_json FROM monitoring_mapping_activation_operations "
            "WHERE project_id = ? AND operation_id = ?",
            (PROJECT_ID, "activate-001"),
        ).fetchone()
        payload = json.loads(row[0])
        payload["state"]["effective_capabilities"] = {"not": "a-list"}
        connection.execute(
            "UPDATE monitoring_mapping_activation_operations SET result_json = ? "
            "WHERE project_id = ? AND operation_id = ?",
            (json.dumps(payload), PROJECT_ID, "activate-001"),
        )

    with pytest.raises(
        MonitoringMappingActivationError,
        match="persisted mapping activation state",
    ):
        service.activate_confirmed_revision(
            PROJECT_ID,
            mapping_revision,
            expected_project_version=0,
            activated_by="medical-manager",
            activation_reason="作为后续批次的当前项目映射。",
            idempotency_key="activate-001",
        )


def test_persisted_mapping_binding_read_shape_is_rejected(activated) -> None:
    service, _repository, _mapping_revision, _result = activated
    binding_result = service.register_batch_comparison(
        PROJECT_ID,
        _profile(),
        expected_binding_version=0,
        actor="medical-manager",
        idempotency_key="binding-shape",
    )
    with sqlite3.connect(service.state_path) as connection:
        connection.execute(
            "UPDATE monitoring_mapping_batch_bindings SET profile_sha256 = ? "
            "WHERE project_id = ? AND batch_id = ?",
            ("A" * 64, PROJECT_ID, binding_result.binding.batch_id),
        )

    with pytest.raises(
        MonitoringMappingActivationError,
        match="persisted mapping binding",
    ):
        service.get_batch_binding(PROJECT_ID, binding_result.binding.batch_id)


def _profile(
    *,
    batch_id: str = "batch-new",
    project_id: str = PROJECT_ID,
    fields: tuple[tuple[str, str, str], ...] = (
        ("AE", "AETERM", "string"),
        ("AE", "AESTDTC", "date"),
    ),
) -> dict[str, object]:
    domains = sorted({domain for domain, _field, _type in fields})
    payload: dict[str, object] = {
        "schema_version": "monitoring_ai_field_profile_v2",
        "batch_id": batch_id,
        "project_id": project_id,
        "batch_revision": 1,
        "mapping_revision": None,
        "expected_domains": domains,
        "source_bindings": [
            {
                "source_entry_id": f"source-{batch_id}",
                "source_content_sha256": "d" * 64,
            }
        ],
        "source_sha256s": ["d" * 64],
        "row_count": 12,
        "input_sha256": "e" * 64,
        "fields": [
            {
                "domain": domain,
                "field": field,
                "total_rows": 12,
                "non_empty_count": 12,
                "null_rate": 0.0,
                "inferred_type": inferred_type,
                "unique_value_count": 4,
                "top_values": [],
                "representative_values": [],
                "anomaly_examples": [],
            }
            for domain, field, inferred_type in fields
        ],
        "relationships": [],
    }
    payload["profile_sha256"] = content_sha256(payload)
    return payload


@pytest.fixture
def activated(tmp_path: Path):
    repository, mapping_revision = _seed_confirmed_mapping(tmp_path)
    service = MonitoringMappingActivationService(
        repository,
        clock=lambda: NOW,
    )
    result = service.activate_confirmed_revision(
        PROJECT_ID,
        mapping_revision,
        expected_project_version=0,
        activated_by="medical-manager",
        activation_reason="作为后续批次的当前项目映射。",
        idempotency_key="activate-001",
    )
    return service, repository, mapping_revision, result


def test_only_confirmed_monmaprev_can_be_activated_and_content_is_server_loaded(
    tmp_path: Path,
) -> None:
    repository, mapping_revision = _seed_confirmed_mapping(tmp_path)
    service = MonitoringMappingActivationService(repository, clock=lambda: NOW)

    result = service.activate_confirmed_revision(
        PROJECT_ID,
        mapping_revision,
        expected_project_version=0,
        activated_by="medical-manager",
        activation_reason="用户确认后激活。",
        idempotency_key="activate-first",
    )

    stored_revision = repository.get_revision(PROJECT_ID, mapping_revision)
    assert result.changed is True
    assert result.replayed is False
    assert result.state.mapping_revision == mapping_revision
    assert result.state.mapping_content_sha256 == content_sha256(
        stored_revision.model_dump(mode="json")
    )
    assert result.state.source_batch_id == "batch-source"
    assert result.state.project_version == 1
    assert result.state.activation_disposition == "activate_full"
    assert len(result.state.effective_capabilities) == 11
    assert all(
        item.state == "ready" for item in result.state.capability_states
    )

    with pytest.raises(MonitoringMappingActivationSourceError):
        service.activate_confirmed_revision(
            PROJECT_ID,
            "layered-business-key-v1",
            expected_project_version=1,
            activated_by="medical-manager",
            activation_reason="不能激活前端声明的自由版本。",
            idempotency_key="activate-invalid",
        )


def test_activation_is_cas_safe_idempotent_and_preserves_history(
    activated,
) -> None:
    service, _repository, mapping_revision, first = activated

    replay = service.activate_confirmed_revision(
        PROJECT_ID,
        mapping_revision,
        expected_project_version=0,
        activated_by="medical-manager",
        activation_reason="作为后续批次的当前项目映射。",
        idempotency_key="activate-001",
    )
    assert replay.replayed is True
    assert replay.state == first.state

    unchanged = service.activate_confirmed_revision(
        PROJECT_ID,
        mapping_revision,
        expected_project_version=1,
        activated_by="medical-manager",
        activation_reason="重复确认当前映射。",
        idempotency_key="activate-002",
    )
    assert unchanged.changed is False
    assert unchanged.state.project_version == 1

    with pytest.raises(MonitoringMappingActivationConflictError):
        service.activate_confirmed_revision(
            PROJECT_ID,
            mapping_revision,
            expected_project_version=0,
            activated_by="medical-manager",
            activation_reason="错误的 CAS。",
            idempotency_key="activate-cas-fail",
        )
    with sqlite3.connect(service.state_path) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*) FROM monitoring_mapping_activation_history
            WHERE project_id = ?
            """,
            (PROJECT_ID,),
        ).fetchone()[0] == 1
    assert service.list_activation_history(PROJECT_ID) == (first.state,)


def test_serialized_mapping_boolean_flags_are_strict(activated) -> None:
    service, _repository, _mapping_revision, result = activated

    with pytest.raises(MonitoringMappingActivationError, match="strict boolean"):
        replace(result, replayed="false")

    report = service.compare_new_batch(PROJECT_ID, _profile())
    with pytest.raises(MonitoringMappingActivationError, match="strict boolean"):
        replace(report, reuse_recommended="false")

    binding = service.register_batch_comparison(
        PROJECT_ID,
        _profile(),
        expected_binding_version=0,
        actor="medical-manager",
        idempotency_key="strict-boolean-binding",
    )
    with pytest.raises(MonitoringMappingActivationError, match="strict boolean"):
        replace(binding, replayed="false")


def test_activation_rejects_source_candidate_that_is_no_longer_accepted(
    tmp_path: Path,
) -> None:
    repository, mapping_revision = _seed_confirmed_mapping(tmp_path)
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            """
            UPDATE monitoring_ai_candidates
            SET status = 'rejected'
            WHERE candidate_id = 'candidate-activation'
            """
        )
    service = MonitoringMappingActivationService(repository, clock=lambda: NOW)

    with pytest.raises(
        MonitoringMappingActivationSourceError,
        match="no longer accepted",
    ):
        service.activate_confirmed_revision(
            PROJECT_ID,
            mapping_revision,
            expected_project_version=0,
            activated_by="medical-manager",
            activation_reason="来源失效时不得激活。",
            idempotency_key="activate-stale",
        )


def test_activation_rejects_revision_without_semantic_quality_report(
    tmp_path: Path,
) -> None:
    repository, mapping_revision = _seed_confirmed_mapping(tmp_path)
    with sqlite3.connect(repository.path) as connection:
        connection.execute("DROP TRIGGER trg_mapping_revision_no_update")
        connection.execute(
            """
            UPDATE monitoring_mapping_revisions
            SET semantic_quality_report_json = '{}',
                semantic_quality_report_sha256 = ''
            WHERE mapping_revision = ?
            """,
            (mapping_revision,),
        )
    service = MonitoringMappingActivationService(repository, clock=lambda: NOW)

    with pytest.raises(
        MonitoringMappingActivationSourceError,
        match="has no semantic quality report",
    ):
        service.activate_confirmed_revision(
            PROJECT_ID,
            mapping_revision,
            expected_project_version=0,
            activated_by="medical-manager",
            activation_reason="缺少语义质量报告时不得激活。",
            idempotency_key="activate-no-semantic-quality",
        )


def test_get_active_mapping_requires_project_state(tmp_path: Path) -> None:
    repository, _mapping_revision = _seed_confirmed_mapping(tmp_path)
    service = MonitoringMappingActivationService(repository, clock=lambda: NOW)
    with pytest.raises(MonitoringMappingActivationNotFoundError):
        service.get_active_mapping(PROJECT_ID)


def test_fully_compatible_profile_recommends_reuse(activated) -> None:
    service, _repository, mapping_revision, _result = activated
    report = service.compare_new_batch(PROJECT_ID, _profile())

    assert report.status == MonitoringMappingCompatibilityStatus.FULLY_COMPATIBLE
    assert report.reuse_recommended is True
    assert report.mapping_revision == mapping_revision
    assert report.added == ()
    assert report.missing == ()
    assert report.same_name_conflicts == ()
    assert report.report_sha256 == content_sha256(
        {key: value for key, value in report.to_dict().items() if key != "report_sha256"}
    )


def test_new_missing_and_same_name_conflicts_are_separated(activated) -> None:
    service, _repository, _mapping_revision, _result = activated
    report = service.compare_new_batch(
        PROJECT_ID,
        _profile(
            fields=(
                ("AE", "AETERM", "integer"),
                ("CM", "AESTDTC", "date"),
                ("AE", "AESEV", "string"),
            )
        ),
    )

    assert (
        report.status
        == MonitoringMappingCompatibilityStatus.DIFFERENCE_REVIEW_REQUIRED
    )
    assert report.reuse_recommended is False
    assert [(item.domain, item.source_field) for item in report.added] == [
        ("AE", "AESEV")
    ]
    assert report.missing == ()
    assert {
        (item.source_field, item.reason)
        for item in report.same_name_conflicts
    } == {
        ("AETERM", "inferred_type_changed"),
        ("AESTDTC", "same_name_moved_or_duplicated_across_domains"),
    }


def test_numeric_widening_is_compatible_and_profile_hash_is_verified(
    activated,
) -> None:
    service, _repository, _mapping_revision, _result = activated
    profile = _profile(
        fields=(
            ("AE", "AETERM", "string"),
            ("AE", "AESTDTC", "date"),
        )
    )
    report = service.compare_new_batch(PROJECT_ID, profile)
    assert report.reuse_recommended is True

    profile["fields"][0]["inferred_type"] = "integer"
    with pytest.raises(
        MonitoringMappingActivationSourceError,
        match="hash is inconsistent",
    ):
        service.compare_new_batch(PROJECT_ID, profile)


@pytest.mark.parametrize("encoding", ["padded", "uppercase"])
def test_new_profile_hash_requires_exact_lowercase_bytes(activated, encoding: str) -> None:
    service, _repository, _mapping_revision, _result = activated
    profile = _profile()
    claimed = profile["profile_sha256"]
    profile["profile_sha256"] = (
        f" {claimed}" if encoding == "padded" else str(claimed).upper()
    )

    with pytest.raises(ValueError, match="profile_sha256 must be a lowercase SHA-256"):
        service.compare_new_batch(PROJECT_ID, profile)


def test_capability_manifest_hash_requires_exact_lowercase_bytes(activated) -> None:
    service, repository, mapping_revision, _result = activated
    revision = repository.get_revision(PROJECT_ID, mapping_revision)
    report = dict(revision.semantic_quality_report)
    report["capability_manifest_sha256"] = (
        f" {report['capability_manifest_sha256']}"
    )
    tampered = SimpleNamespace(semantic_quality_report=report)

    with pytest.raises(
        MonitoringMappingActivationSourceError,
        match="capability manifest is stale or invalid",
    ):
        service._capability_contract_from_revision(tampered)


def test_numeric_compatibility_allows_widening_but_not_narrowing_or_empty_domains(
    activated,
) -> None:
    service, _repository, _mapping_revision, _result = activated

    assert service._types_compatible("integer", "decimal") is True
    assert service._types_compatible("decimal", "integer") is False
    assert service._types_compatible("string", "unknown") is True
    assert service._types_compatible("unknown", "date") is True


def test_cross_project_profile_is_rejected(activated) -> None:
    service, _repository, _mapping_revision, _result = activated
    profile = _profile(project_id="project-other")
    with pytest.raises(
        MonitoringMappingActivationSourceError,
        match="another project",
    ):
        service.compare_new_batch(PROJECT_ID, profile)


def test_batch_binding_is_cas_safe_idempotent_and_keeps_all_history(
    activated,
) -> None:
    service, _repository, mapping_revision, _result = activated
    compatible = service.register_batch_comparison(
        PROJECT_ID,
        _profile(),
        expected_binding_version=0,
        actor="medical-manager",
        idempotency_key="bind-001",
    )
    assert compatible.replayed is False
    assert (
        compatible.binding.status
        == MonitoringBatchMappingBindingStatus.REUSE_SUGGESTED
    )
    assert compatible.binding.evaluated_mapping_revision == mapping_revision
    assert compatible.binding.binding_version == 1

    replay = service.register_batch_comparison(
        PROJECT_ID,
        _profile(),
        expected_binding_version=0,
        actor="medical-manager",
        idempotency_key="bind-001",
    )
    assert replay.replayed is True
    assert replay.binding == compatible.binding

    changed_profile = _profile(
        fields=(
            ("AE", "AETERM", "string"),
            ("AE", "AESTDTC", "date"),
            ("AE", "AESEV", "string"),
        )
    )
    changed = service.register_batch_comparison(
        PROJECT_ID,
        changed_profile,
        expected_binding_version=1,
        actor="medical-manager",
        idempotency_key="bind-002",
    )
    assert changed.binding.binding_version == 2
    assert (
        changed.binding.status
        == MonitoringBatchMappingBindingStatus.DIFFERENCE_REVIEW_REQUIRED
    )
    assert service.get_batch_binding(PROJECT_ID, "batch-new") == changed.binding
    history = service.list_batch_binding_history(PROJECT_ID, "batch-new")
    assert history == (compatible.binding, changed.binding)

    with pytest.raises(MonitoringMappingActivationConflictError):
        service.register_batch_comparison(
            PROJECT_ID,
            changed_profile,
            expected_binding_version=1,
            actor="medical-manager",
            idempotency_key="bind-cas-fail",
        )


def test_binding_history_is_immutable(activated) -> None:
    service, _repository, _mapping_revision, _result = activated
    service.register_batch_comparison(
        PROJECT_ID,
        _profile(),
        expected_binding_version=0,
        actor="medical-manager",
        idempotency_key="bind-history",
    )
    with sqlite3.connect(service.state_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                UPDATE monitoring_mapping_batch_binding_history
                SET created_at = 'changed'
                WHERE project_id = ? AND batch_id = ?
                """,
                (PROJECT_ID, "batch-new"),
            )


def test_duplicate_profile_field_fails_closed(activated) -> None:
    service, _repository, _mapping_revision, _result = activated
    profile = _profile(
        fields=(
            ("AE", "AETERM", "string"),
            ("AE", "AETERM", "string"),
        )
    )
    with pytest.raises(
        MonitoringMappingActivationSourceError,
        match="duplicate",
    ):
        service.compare_new_batch(PROJECT_ID, profile)
