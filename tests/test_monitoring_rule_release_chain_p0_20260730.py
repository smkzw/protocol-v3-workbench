"""P0 integration coverage for the medical-monitoring rule release chain.

Chain under test: recommendation candidate adoption -> confirmed rule with
immutable identity -> draft pack -> start-shadow -> server-side automatic
shadow sampling (provisional only) -> confirm-shadow promotion -> explicit
publish -> daily-run readiness against the current published pack.

All scenarios run on isolated temporary repositories with fake batch
sources, reusing the fixture patterns from the adjacent monitoring test
modules. No production code is modified by this file.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.medical_monitoring_router import (
    create_medical_monitoring_router,
)
from services.api.app.monitoring_ai_contracts import MonitoringAiCandidateStatus
from services.api.app.monitoring_ai_repository import MonitoringAiRepository
from services.api.app.monitoring_batch_repository import MonitoringBatchRepository
from services.api.app.monitoring_daily_run_repository import (
    MonitoringDailyRunRepository,
)
from services.api.app.monitoring_daily_run_service import (
    MonitoringDailyRunService,
    MonitoringDailyRunServiceError,
    MonitoringRuleRuntimeIdentity,
)
from services.api.app.monitoring_gold_case_authority import (
    MonitoringGoldCaseAuthority,
)
from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
    RulePackRevisionConflictError,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_rule_authoring_service import (
    MonitoringRuleAuthoringError,
    MonitoringRuleAuthoringService,
)
from services.api.app.monitoring_rule_lifecycle_service import (
    MonitoringRuleLifecycleService,
)
from services.api.app.monitoring_shadow_sample_service import (
    MonitoringShadowSampleError,
    MonitoringShadowSampleService,
)
from tests.test_monitoring_mapping_activation import PROJECT_ID
from tests.test_monitoring_protocol_rule_repository_hardening import (
    _assignment,
    _site_version,
)
from tests.test_monitoring_protocol_rules import (
    _fact,
    _publish_pack,
    _rule,
    _start_shadow_pack,
    _version,
)
from tests.test_monitoring_record_rule_resolver import (
    _RULE_IDENTITY,
    _identified_rule,
    _service_stack,
)
from tests.test_monitoring_rule_template_recommendation import _setup
from tests.test_monitoring_shadow_sample_service import (
    CAPABILITY_MANIFEST_SHA256,
    MAPPING_CONTENT_SHA256,
    MAPPING_REVISION,
    OTHER_PROJECT,
    PROJECT,
    _EmptyRiskRepository,
    _FakeSourceRegistry,
    _Fixture,
    _RegistryReader,
    _add_batch,
    _add_project,
    _build_fixture,
    _client,
    _confirmed_and_published_packs,
    _ex_rows_variant,
    _make_batch,
    _prepare,
    _registration,
    _repository_counts,
    _shadow_rule,
    _v2_mapping,
)


def _base(project_id: str = PROJECT) -> str:
    return f"/api/projects/{project_id}/modules/medical-monitoring"


def _capable_mapping() -> dict[str, Any]:
    """v2 mapping with a non-empty capability snapshot, as daily-run
    readiness fails closed on frozen batches without capability states.
    effective_capabilities must equal the ready/limited capability ids."""
    mapping = _v2_mapping()
    mapping["effective_capabilities"] = ["raw_source_review"]
    mapping["capability_states"] = [
        {
            "capability_id": "raw_source_review",
            "state": "ready",
            "limitation_codes": [],
            "blocking_finding_group_ids": [],
        }
    ]
    return mapping


def _build_stack(root: Path, *, mapping: dict[str, Any] | None = None) -> _Fixture:
    """Same stack as ``_build_fixture`` with an overridable frozen mapping."""
    batches = MonitoringBatchRepository(
        root / "batches.sqlite3",
        root / "batch_objects",
    )
    batch = _make_batch(
        batches,
        root,
        project_id=PROJECT,
        key="main",
        mapping=mapping,
    )
    registry_reader = _RegistryReader((_registration(PROJECT, batch),))
    source_registry = _FakeSourceRegistry()
    source_registry.add_entry(PROJECT, batch.entry_id, batch.content_hash)
    authority = MonitoringGoldCaseAuthority(registry_reader, batches)
    repository = MonitoringProtocolRuleRepository(
        root / "rules.sqlite3",
        gold_case_authority=authority.validate,
    )
    version = repository.register_protocol_version(
        _version(PROJECT, "V1.0", "2026-01-01", effective_from="2026-01-10")
    )
    fact = repository.store_fact(_fact(version))
    _lifecycle, pack, confirmed_rules = _start_shadow_pack(
        repository,
        version,
        [_shadow_rule(version, fact)],
    )
    rule_service = MonitoringProtocolRuleService(repository)
    authoring = MonitoringRuleAuthoringService(
        repository=repository,
        lifecycle_service=MonitoringRuleLifecycleService(repository),
        protocol_rule_service=rule_service,
        ai_repository=MonitoringAiRepository(root / "ai.sqlite3"),
        source_registry=source_registry,
    )
    sample_service = MonitoringShadowSampleService(
        repository=repository,
        batch_repository=batches,
        protocol_rule_service=rule_service,
        rule_authoring_service=authoring,
    )
    return _Fixture(
        root=root,
        project_id=PROJECT,
        batches=batches,
        repository=repository,
        rule_service=rule_service,
        authoring=authoring,
        sample_service=sample_service,
        registry_reader=registry_reader,
        source_registry=source_registry,
        pack=pack,
        rules=confirmed_rules,
        batch=batch,
    )


def _rule_runtime_resolver(
    repository: MonitoringProtocolRuleRepository,
) -> Callable[[str], MonitoringRuleRuntimeIdentity]:
    """Mirror of ``main._current_monitoring_rule_runtime`` against the
    isolated repository: resolve identity from the current published pack."""

    def resolve(project_id: str) -> MonitoringRuleRuntimeIdentity:
        pack, rules = repository.current_published_pack(
            project_id,
            as_of=date.today().isoformat(),
        )

        def shared(attribute: str) -> str:
            # Mirror of main._current_monitoring_rule_runtime: fail closed
            # on any empty or mixed member instead of filtering empties. Hash
            # fields remain raw contract bytes and must already be canonical.
            raw_values = [getattr(rule, attribute, None) for rule in rules]
            if attribute in {
                "mapping_content_sha256",
                "capability_manifest_sha256",
                "effective_capabilities_sha256",
            }:
                if any(
                    not isinstance(value, str)
                    or re.fullmatch(r"[0-9a-f]{64}", value) is None
                    for value in raw_values
                ):
                    return ""
                values = set(raw_values)
            else:
                values = {
                    str(value or "").strip()
                    for value in raw_values
                }
            return values.pop() if len(values) == 1 else ""

        return MonitoringRuleRuntimeIdentity(
            rule_pack_revision=pack.rule_pack_id,
            engine_version="monitoring_protocol_rule_engine.v1",
            rule_mapping_revision=shared("mapping_revision"),
            rule_mapping_content_sha256=shared("mapping_content_sha256"),
            rule_capability_manifest_sha256=shared("capability_manifest_sha256"),
            rule_effective_capabilities_sha256=shared(
                "effective_capabilities_sha256"
            ),
        )

    return resolve


_ACTIVE_MAPPING = SimpleNamespace(
    mapping_revision=MAPPING_REVISION,
    mapping_content_sha256=MAPPING_CONTENT_SHA256,
    capability_manifest_sha256=CAPABILITY_MANIFEST_SHA256,
    # Matches the frozen mapping contract and ``_shadow_rule`` identity.
    effective_capabilities_sha256="f" * 64,
)


def _daily_run_service(
    fixture: _Fixture,
    *,
    active_mapping: Any = _ACTIVE_MAPPING,
    rule_runtime: Callable[[str], MonitoringRuleRuntimeIdentity] | None = None,
) -> MonitoringDailyRunService:
    return MonitoringDailyRunService(
        run_repository=MonitoringDailyRunRepository(
            fixture.root / "daily-runs.sqlite3"
        ),
        batch_repository=fixture.batches,
        batch_service=Mock(),
        rule_runtime_resolver=(
            rule_runtime
            if rule_runtime is not None
            else _rule_runtime_resolver(fixture.repository)
        ),
        active_mapping_resolver=lambda _project_id: active_mapping,
    )


def _fresh_client(fixture: _Fixture) -> TestClient:
    """Rebuild the whole service stack from the same on-disk state to prove
    lineage evidence survives a fresh load (new sqlite connections)."""
    root = fixture.root
    batches = MonitoringBatchRepository(
        root / "batches.sqlite3",
        root / "batch_objects",
    )
    authority = MonitoringGoldCaseAuthority(_RegistryReader(()), batches)
    repository = MonitoringProtocolRuleRepository(
        root / "rules.sqlite3",
        gold_case_authority=authority.validate,
    )
    rule_service = MonitoringProtocolRuleService(repository)
    authoring = MonitoringRuleAuthoringService(
        repository=repository,
        lifecycle_service=MonitoringRuleLifecycleService(repository),
        protocol_rule_service=rule_service,
        ai_repository=MonitoringAiRepository(root / "ai.sqlite3"),
        source_registry=_FakeSourceRegistry(),
    )
    sample_service = MonitoringShadowSampleService(
        repository=repository,
        batch_repository=batches,
        protocol_rule_service=rule_service,
        rule_authoring_service=authoring,
    )
    app = FastAPI()
    app.include_router(
        create_medical_monitoring_router(
            risk_repository=_EmptyRiskRepository(),
            protocol_rule_service=rule_service,
            require_server_principal=False,
            protocol_rule_authoring_service=authoring,
            protocol_rule_shadow_sample_service=sample_service,
        )
    )
    return TestClient(app)


def _seed_second_project_coverage(fixture: _Fixture) -> None:
    """Initial release of a rule family requires gold coverage in at least
    two authoritative projects; confirm a second project's shadow pack so
    the main pack can be published."""
    pack_b, _rules_b, batch_b = _add_project(fixture, OTHER_PROJECT, "second")
    inspection_b = _prepare(
        fixture,
        project_id=OTHER_PROJECT,
        rule_pack_id=pack_b.rule_pack_id,
        batch_id=batch_b.batch_id,
    )
    outcome_b = fixture.authoring.confirm_shadow(
        project_id=OTHER_PROJECT,
        rule_pack_id=pack_b.rule_pack_id,
        sample_set_id=inspection_b.sample_set.sample_set_id,
        confirmed_by="medical_manager",
    )
    assert outcome_b.pack.status == "confirmed"


# ---------------------------------------------------------------------------
# A. Full-chain integration
# ---------------------------------------------------------------------------


def test_accepted_recommendation_yields_confirmed_rule_and_direct_shadow_entry(
    tmp_path: Path,
) -> None:
    """A.1/A.2 + B.1: adopting a recommendation candidate produces a
    confirmed rule carrying the five immutable identity fields; the draft
    pack enters shadow directly, with no per-rule confirmation step and no
    residual candidate-state rule."""
    service, ai_service, _ai_repo, rules, _registry, fact, _provider = _setup(
        tmp_path
    )
    queued = service.start(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    assert queued["status"] == "queued"
    run = ai_service.run_next("p0-release-chain-worker")
    assert run.processed is True and run.job.status.value == "completed"
    status = service.status(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    assert status["status"] == "candidate_review"
    candidate = status["candidates"][0]

    decision = service.decide(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        candidate_id=candidate["candidate_id"],
        decision=MonitoringAiCandidateStatus.ACCEPTED,
        expected_input_revision_sha256=status["input_revision_sha256"],
        expected_fact_state_version=fact.state_version,
        actor="medical_manager",
        reason="选择该确定性核对逻辑。",
    )

    assert decision["status"] == "rule_template_selected"
    rule = decision["compiled_rule"]
    assert rule["status"] == "confirmed"
    assert "candidate" not in rule["status"]
    assert str(rule["title"]).strip()
    assert "需医学复核候选" not in str(rule["title"])
    assert "candidate" not in str(rule["title"]).lower()
    for identity_field in (
        "mapping_revision",
        "mapping_content_sha256",
        "capability_manifest_sha256",
        "effective_capabilities_sha256",
        "recommendation_candidate_id",
    ):
        assert str(rule[identity_field]).strip(), identity_field
    assert rule["recommendation_candidate_id"] == candidate["candidate_id"]

    confirmed_fact = decision["confirmed_fact"]
    draft = service.rule_authoring_service.create_draft(
        project_id=PROJECT_ID,
        protocol_version_id=confirmed_fact["protocol_version_id"],
        fact_revision_ids=[confirmed_fact["fact_revision_id"]],
        created_by="medical_manager",
    )
    _, draft_rules = rules.rule_pack(draft.rule_pack_id)
    assert len(draft_rules) == 1
    assert draft_rules[0].status == "confirmed"
    assert draft_rules[0].rule_revision_id == rule["rule_revision_id"]
    assert all(item.status != "candidate" for item in draft_rules)

    shadow = MonitoringRuleLifecycleService(rules).start_shadow(
        draft.rule_pack_id,
        started_by="medical_manager",
    )
    assert shadow.status == "shadow"
    assert shadow.rule_pack_id != draft.rule_pack_id


def test_full_release_chain_provisional_confirm_publish_readiness(
    tmp_path: Path,
) -> None:
    """A.3-A.7: automatic shadow sampling is provisional-only; publish is
    rejected until confirm-shadow promotes trusted evidence; readiness and
    daily-run start require the published pack identity to match the active
    mapping."""
    fixture = _build_stack(tmp_path, mapping=_capable_mapping())
    client = _client(fixture)
    shadow_pack_id = fixture.pack.rule_pack_id
    shadow_url = (
        f"{_base()}/rule-packs/{shadow_pack_id}/automatic-shadow-runs"
    )

    # A.3: automatic shadow run stores only provisional evidence.
    created = client.post(
        shadow_url,
        json={
            "batch_id": fixture.batch.batch_id,
            "actor": "medical_manager",
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["state"] == {
        "code": "shadow_inspection_provisional",
        "label": "自动影子样本待医学确认",
    }
    inspection = payload["inspection"]
    assert inspection["status"] == "provisional"
    assert inspection["rule_pack_id"] == shadow_pack_id
    for forbidden in ("shadow_passed", "trusted", "shadow_run"):
        assert forbidden not in created.text
    sample_set_id = inspection["sample_set_id"]
    assert _repository_counts(fixture.repository) == {
        "gold": 0,
        "diagnostic": 0,
        "runs": 0,
        "sets": 1,
        "confirmations": 0,
    }

    # A.4: a provisional pack cannot be published.
    premature = client.post(
        f"{_base()}/rule-packs/{shadow_pack_id}/publish",
        json={"actor": "medical_manager"},
    )
    assert premature.status_code == 409
    assert premature.json()["detail"]["code"] == (
        "monitoring_rule_pack_stage_conflict"
    )
    assert _repository_counts(fixture.repository)["confirmations"] == 0

    # A.5: confirm-shadow promotes trusted evidence and advances the pack.
    # Initial release of a rule family requires confirmed shadow coverage
    # in a second project before the main pack's own confirmation.
    _seed_second_project_coverage(fixture)
    confirmed = client.post(
        f"{_base()}/rule-packs/{shadow_pack_id}/confirm-shadow",
        json={
            "sample_set_id": sample_set_id,
            "confirmed_by": "medical_manager",
        },
    )
    assert confirmed.status_code == 200
    confirmed_payload = confirmed.json()
    confirmed_pack_id = confirmed_payload["pack"]["rule_pack_id"]
    assert confirmed_pack_id != shadow_pack_id
    assert confirmed_payload["pack"]["status"] == "confirmed"
    assert confirmed_payload["state"]["code"] == "shadow_confirmed"
    assert confirmed_payload["confirmation_id"]
    assert confirmed_payload["shadow_run_id"]
    counts = _repository_counts(fixture.repository)
    assert counts["gold"] >= 1
    assert counts["diagnostic"] >= 1
    assert counts["runs"] >= 1
    # One confirmation per project (main chain + second-project coverage).
    assert counts["confirmations"] == 2
    lineage = fixture.sample_service.lineage_evidence(
        project_id=PROJECT,
        rule_pack_id=confirmed_pack_id,
    )
    assert lineage.confirmation is not None
    assert lineage.confirmation.sample_set_id == sample_set_id
    assert lineage.confirmation.rule_pack_id == shadow_pack_id
    assert lineage.confirmation.confirmation_id == (
        confirmed_payload["confirmation_id"]
    )

    # A.6: explicit publish after confirmation.
    published = client.post(
        f"{_base()}/rule-packs/{confirmed_pack_id}/publish",
        json={"actor": "medical_manager"},
    )
    assert published.status_code == 200
    published_payload = published.json()
    published_pack_id = published_payload["pack"]["rule_pack_id"]
    assert published_payload["pack"]["status"] == "published"
    assert published_payload["state"]["code"] == "published"

    # A.7: readiness and daily-run start contract against the published pack.
    service = _daily_run_service(fixture)
    readiness = service.start_readiness(
        project_id=PROJECT,
        batch_id=fixture.batch.batch_id,
    )
    assert readiness["ready"] is True
    assert readiness["state_code"] == "ready"
    assert readiness["next_action"] == "start_daily_run"
    assert readiness["mapping_revision"] == MAPPING_REVISION
    assert readiness["capability_manifest_sha256"] == (
        CAPABILITY_MANIFEST_SHA256
    )
    assert readiness["rule_pack_revision"] == published_pack_id
    assert readiness["rule_resolution_mode"] == "project_effective"

    identity = _rule_runtime_resolver(fixture.repository)(PROJECT)
    assert identity.rule_mapping_revision == _ACTIVE_MAPPING.mapping_revision
    assert identity.rule_mapping_content_sha256 == (
        _ACTIVE_MAPPING.mapping_content_sha256
    )
    assert identity.rule_capability_manifest_sha256 == (
        _ACTIVE_MAPPING.capability_manifest_sha256
    )
    assert identity.rule_effective_capabilities_sha256 == (
        _ACTIVE_MAPPING.effective_capabilities_sha256
    )

    prepared = service.prepare(
        project_id=PROJECT,
        batch_id=fixture.batch.batch_id,
        idempotency_key="p0-release-chain:prepare",
        actor="medical_manager",
    )
    assert prepared.run.rule_pack_revision == published_pack_id
    assert prepared.run.rule_resolution_mode == "project_effective"


# ---------------------------------------------------------------------------
# B. Negative integration
# ---------------------------------------------------------------------------


def test_cross_batch_sample_sets_never_reused_or_cross_confirmed(
    tmp_path: Path,
) -> None:
    """B.2: distinct frozen batches produce distinct sample sets; after one
    set is confirmed, confirming a set sampled from another batch is a 409
    conflict, and the service keeps no cross-batch reuse state."""
    fixture = _build_fixture(tmp_path)
    batch_b = _add_batch(
        fixture,
        project_id=PROJECT,
        key="batch-b",
        rows_factory=_ex_rows_variant,
    )
    inspection_a = _prepare(fixture)
    inspection_b = _prepare(fixture, batch_id=batch_b.batch_id)
    assert inspection_a.reused is False
    assert inspection_b.reused is False
    assert (
        inspection_a.sample_set.sample_set_id
        != inspection_b.sample_set.sample_set_id
    )

    retry_a = _prepare(fixture)
    assert retry_a.reused is True
    assert (
        retry_a.sample_set.sample_set_id
        == inspection_a.sample_set.sample_set_id
    )

    outcome = fixture.authoring.confirm_shadow(
        project_id=PROJECT,
        rule_pack_id=fixture.pack.rule_pack_id,
        sample_set_id=inspection_a.sample_set.sample_set_id,
        confirmed_by="medical_manager",
    )
    assert outcome.pack.status == "confirmed"

    with pytest.raises(MonitoringRuleAuthoringError) as conflict:
        fixture.authoring.confirm_shadow(
            project_id=PROJECT,
            rule_pack_id=fixture.pack.rule_pack_id,
            sample_set_id=inspection_b.sample_set.sample_set_id,
            confirmed_by="medical_manager",
        )
    assert conflict.value.code == "monitoring_shadow_confirmation_conflict"
    assert conflict.value.http_status == 409
    assert not hasattr(fixture.sample_service, "_existing_run")
    assert _repository_counts(fixture.repository)["confirmations"] == 1


def test_cross_project_access_fails_closed(tmp_path: Path) -> None:
    """B.3: packs, sample sets, lineage evidence and automatic shadow runs
    are invisible across projects; a batch frozen under another project is
    rejected with 404."""
    fixture = _build_fixture(tmp_path)
    client = _client(fixture)
    pack_id = fixture.pack.rule_pack_id
    created = client.post(
        f"{_base()}/rule-packs/{pack_id}/automatic-shadow-runs",
        json={
            "batch_id": fixture.batch.batch_id,
            "actor": "medical_manager",
        },
    )
    assert created.status_code == 201

    foreign_pack = client.get(f"{_base(OTHER_PROJECT)}/rule-packs/{pack_id}")
    assert foreign_pack.status_code == 404
    foreign_sets = client.get(
        f"{_base(OTHER_PROJECT)}/rule-packs/{pack_id}/shadow-sample-sets"
    )
    assert foreign_sets.status_code == 404
    foreign_lineage = client.get(
        f"{_base(OTHER_PROJECT)}/rule-packs/{pack_id}/shadow-lineage-evidence"
    )
    assert foreign_lineage.status_code == 404
    foreign_run = client.post(
        f"{_base(OTHER_PROJECT)}/rule-packs/{pack_id}/automatic-shadow-runs",
        json={
            "batch_id": fixture.batch.batch_id,
            "actor": "medical_manager",
        },
    )
    assert foreign_run.status_code == 404
    assert foreign_run.json()["detail"]["code"] == (
        "monitoring_rule_pack_not_found"
    )

    foreign_batch = _add_batch(
        fixture,
        project_id=OTHER_PROJECT,
        key="foreign",
        rows_factory=_ex_rows_variant,
    )
    cross_batch = client.post(
        f"{_base()}/rule-packs/{pack_id}/automatic-shadow-runs",
        json={
            "batch_id": foreign_batch.batch_id,
            "actor": "medical_manager",
        },
    )
    assert cross_batch.status_code == 404
    assert cross_batch.json()["detail"]["code"] == (
        "monitoring_shadow_batch_not_found"
    )
    assert _repository_counts(fixture.repository) == {
        "gold": 0,
        "diagnostic": 0,
        "runs": 0,
        "sets": 1,
        "confirmations": 0,
    }


def test_mapping_drift_after_sampling_blocks_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B.4 (confirm side): drifting the frozen mapping contract after
    sampling makes confirm fail atomically with 409."""
    fixture = _build_fixture(tmp_path)
    inspection = _prepare(fixture)

    original = fixture.batches.load_frozen_mapping_contract

    def drifted_contract(batch_id: str):
        return replace(
            original(batch_id),
            mapping_content_sha256="0" * 64,
        )

    monkeypatch.setattr(
        fixture.batches,
        "load_frozen_mapping_contract",
        drifted_contract,
    )

    with pytest.raises(MonitoringShadowSampleError) as drift:
        fixture.sample_service.confirm_samples(
            project_id=PROJECT,
            rule_pack_id=fixture.pack.rule_pack_id,
            sample_set_id=inspection.sample_set.sample_set_id,
            actor="medical_manager",
        )
    assert drift.value.code == "monitoring_shadow_confirmation_drift"
    assert drift.value.http_status == 409
    assert _repository_counts(fixture.repository) == {
        "gold": 0,
        "diagnostic": 0,
        "runs": 0,
        "sets": 1,
        "confirmations": 0,
    }


def test_rule_pack_identity_drift_fails_readiness_and_prepare(
    tmp_path: Path,
) -> None:
    """B.4 (readiness side): a published pack whose identity no longer
    matches the active mapping makes readiness fail closed with
    monitoring_rule_pack_identity_drift and next action prepare_rule_pack."""
    fixture = _build_stack(tmp_path, mapping=_capable_mapping())
    _inspection, _confirmed_pack, published = (
        _confirmed_and_published_packs(fixture)
    )
    assert published.status == "published"

    drifted_mapping = SimpleNamespace(
        **{**vars(_ACTIVE_MAPPING), "mapping_content_sha256": "0" * 64}
    )
    service = _daily_run_service(fixture, active_mapping=drifted_mapping)
    readiness = service.start_readiness(
        project_id=PROJECT,
        batch_id=fixture.batch.batch_id,
    )
    assert readiness["ready"] is False
    assert readiness["state_code"] == "monitoring_rule_pack_identity_drift"
    assert readiness["next_action"] == "prepare_rule_pack"
    with pytest.raises(MonitoringDailyRunServiceError) as raised:
        service.prepare(
            project_id=PROJECT,
            batch_id=fixture.batch.batch_id,
            idempotency_key="p0-drift:prepare",
            actor="medical_manager",
        )
    assert raised.value.code == "monitoring_rule_pack_identity_drift"


def test_record_mode_execute_fails_closed_when_identity_changes_after_prepare(
    tmp_path: Path,
) -> None:
    """B.5: in record_applicability mode, changing assignments or published
    packs after prepare makes execute_rules fail with
    monitoring_rule_identity_changed before any rule run or snapshot."""
    stack = _service_stack(tmp_path)
    batch = stack.batch
    prepared = stack.service.prepare(
        project_id=batch.project_id,
        batch_id=batch.batch_id,
        idempotency_key="p0-record-mutate:prepare",
        actor="medical_manager",
    ).run
    assert prepared.rule_resolution_mode == "record_applicability"
    assert prepared.rule_identity_sha256
    processing = stack.service.process_prepared(
        project_id=batch.project_id,
        run_id=prepared.run_id,
        expected_version=prepared.version,
        owner="worker-1",
    ).run

    version_3 = stack.repository.register_protocol_version(
        _site_version(batch.project_id, "V3.0", "d")
    )
    fact_3 = stack.repository.store_fact(_fact(version_3))
    assignment_3 = stack.repository.create_applicability_assignment(
        _assignment(
            version_3,
            centre_id="003",
            effective_from="2026-01-01",
            effective_to="2026-12-31",
        )
    )
    stack.repository.transition_applicability_assignment(
        assignment_3.project_id,
        assignment_3.assignment_id,
        expected_state_version=1,
        status="confirmed",
        actor="medical_manager",
    )
    _publish_pack(
        stack.repository,
        version_3,
        [_identified_rule(_rule(version_3, fact_3))],
    )
    stack.runner.run = Mock(wraps=stack.runner.run)

    with pytest.raises(MonitoringDailyRunServiceError) as raised:
        stack.service.execute_rules(
            project_id=batch.project_id,
            run_id=processing.run_id,
            expected_version=processing.version,
            owner="worker-2",
        )
    assert raised.value.code == "monitoring_rule_identity_changed"
    assert stack.runner.run.call_count == 0
    assert (
        stack.run_repository.get_rule_snapshot(
            batch.project_id,
            prepared.run_id,
        )
        is None
    )
    frozen = stack.run_repository.get(batch.project_id, prepared.run_id)
    assert frozen.rule_identity_sha256 == prepared.rule_identity_sha256

    with pytest.raises(MonitoringDailyRunServiceError) as repeated:
        stack.service.execute_rules(
            project_id=batch.project_id,
            run_id=frozen.run_id,
            expected_version=frozen.version,
            owner="worker-3",
        )
    assert repeated.value.code == "monitoring_rule_identity_changed"
    assert stack.runner.run.call_count == 0


def test_record_mode_prepare_idempotent_with_stable_aggregate_identity(
    tmp_path: Path,
) -> None:
    """B.5: with a stable aggregate identity, repeating prepare with the
    same idempotency key replays the same run and frozen identity."""
    stack = _service_stack(tmp_path)
    batch = stack.batch
    aggregate = stack.resolver.aggregate_identity(batch.project_id)

    first = stack.service.prepare(
        project_id=batch.project_id,
        batch_id=batch.batch_id,
        idempotency_key="p0-record-idempotent:prepare",
        actor="medical_manager",
    )
    replay = stack.service.prepare(
        project_id=batch.project_id,
        batch_id=batch.batch_id,
        idempotency_key="p0-record-idempotent:prepare",
        actor="medical_manager",
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.run.run_id == first.run.run_id
    assert first.run.rule_identity_sha256 == aggregate.identity_sha256
    assert replay.run.rule_identity_sha256 == aggregate.identity_sha256
    assert replay.run.input_sha256 == first.run.input_sha256
    assert len(stack.run_repository.list_runs(batch.project_id)) == 1


def test_stale_pack_revision_rejected_on_shadow_run_and_confirmation(
    tmp_path: Path,
) -> None:
    """B.6: a stale expected_pack_revision is rejected with 409
    monitoring_rule_pack_revision_stale on both automatic-shadow-runs and
    confirm-shadow."""
    fixture = _build_fixture(tmp_path)
    client = _client(fixture)
    pack_id = fixture.pack.rule_pack_id
    stale_revision = fixture.pack.pack_revision + 100
    shadow_url = f"{_base()}/rule-packs/{pack_id}/automatic-shadow-runs"

    stale = client.post(
        shadow_url,
        json={
            "batch_id": fixture.batch.batch_id,
            "actor": "medical_manager",
            "expected_pack_revision": stale_revision,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == (
        "monitoring_rule_pack_revision_stale"
    )

    created = client.post(
        shadow_url,
        json={
            "batch_id": fixture.batch.batch_id,
            "actor": "medical_manager",
        },
    )
    assert created.status_code == 201
    sample_set_id = created.json()["inspection"]["sample_set_id"]

    stale_confirm = client.post(
        f"{_base()}/rule-packs/{pack_id}/confirm-shadow",
        json={
            "sample_set_id": sample_set_id,
            "confirmed_by": "medical_manager",
            "expected_pack_revision": stale_revision,
        },
    )
    assert stale_confirm.status_code == 409
    assert stale_confirm.json()["detail"]["code"] == (
        "monitoring_rule_pack_revision_stale"
    )
    assert _repository_counts(fixture.repository)["confirmations"] == 0


def test_partial_rule_identity_fails_closed_in_daily_run_readiness(
    tmp_path: Path,
) -> None:
    """B.7 (project_effective mode): a published-pack identity missing
    effective_capabilities_sha256 makes readiness fail closed with
    monitoring_rule_pack_identity_unverifiable."""
    fixture = _build_stack(tmp_path, mapping=_capable_mapping())
    legacy_identity = MonitoringRuleRuntimeIdentity(
        rule_pack_revision="monpack_legacy",
        engine_version="monitoring_protocol_rule_engine.v1",
        rule_mapping_revision=MAPPING_REVISION,
        rule_mapping_content_sha256=MAPPING_CONTENT_SHA256,
        rule_capability_manifest_sha256=CAPABILITY_MANIFEST_SHA256,
        rule_effective_capabilities_sha256="",
    )
    service = _daily_run_service(
        fixture,
        rule_runtime=lambda _project_id: legacy_identity,
    )
    readiness = service.start_readiness(
        project_id=PROJECT,
        batch_id=fixture.batch.batch_id,
    )
    assert readiness["ready"] is False
    assert readiness["state_code"] == (
        "monitoring_rule_pack_identity_unverifiable"
    )
    assert readiness["next_action"] == "prepare_rule_pack"
    with pytest.raises(MonitoringDailyRunServiceError) as raised:
        service.prepare(
            project_id=PROJECT,
            batch_id=fixture.batch.batch_id,
            idempotency_key="p0-legacy:prepare",
            actor="medical_manager",
        )
    assert raised.value.code == "monitoring_rule_pack_identity_unverifiable"


def test_record_aggregate_missing_effective_capabilities_fails_closed(
    tmp_path: Path,
) -> None:
    """B.7 (record_applicability mode): a legacy pack without
    effective_capabilities_sha256 fails closed identically."""
    stack = _service_stack(
        tmp_path,
        rule_identity={
            **_RULE_IDENTITY,
            "effective_capabilities_sha256": "",
        },
    )
    readiness = stack.service.start_readiness(
        project_id=stack.batch.project_id,
        batch_id=stack.batch.batch_id,
    )
    assert readiness["ready"] is False
    assert readiness["state_code"] == (
        "monitoring_rule_pack_identity_unverifiable"
    )
    assert readiness["next_action"] == "prepare_rule_pack"
    with pytest.raises(MonitoringDailyRunServiceError) as raised:
        stack.service.prepare(
            project_id=stack.batch.project_id,
            batch_id=stack.batch.batch_id,
            idempotency_key="p0-record-legacy:prepare",
            actor="medical_manager",
        )
    assert raised.value.code == "monitoring_rule_pack_identity_unverifiable"
    assert stack.run_repository.list_runs(stack.batch.project_id) == ()


def test_same_sample_set_id_with_different_payload_conflicts(
    tmp_path: Path,
) -> None:
    """B.8: re-storing a sample set under the same id with different
    content raises a revision conflict (409-class), never a silent
    overwrite."""
    fixture = _build_fixture(tmp_path)
    inspection = _prepare(fixture)
    sample_set = inspection.sample_set

    conflicting = replace(
        sample_set,
        mapping_content_sha256="0" * 64,
    )
    assert conflicting.sample_set_id == sample_set.sample_set_id
    with pytest.raises(RulePackRevisionConflictError):
        fixture.repository.store_shadow_sample_set(conflicting)
    assert _repository_counts(fixture.repository)["sets"] == 1


def test_manual_gold_or_diagnostic_case_injection_endpoints_absent(
    tmp_path: Path,
) -> None:
    """B.9: no endpoint may register gold or diagnostic cases manually;
    both POSTs are 404/405 and the repository stays empty."""
    fixture = _build_fixture(tmp_path)
    client = _client(fixture)
    pack_id = fixture.pack.rule_pack_id

    gold = client.post(
        f"{_base()}/rule-packs/{pack_id}/gold-cases",
        json={},
    )
    assert gold.status_code in {404, 405}
    diagnostic = client.post(
        f"{_base()}/rule-packs/{pack_id}/diagnostic-cases",
        json={},
    )
    assert diagnostic.status_code in {404, 405}
    counts = _repository_counts(fixture.repository)
    assert counts["gold"] == 0
    assert counts["diagnostic"] == 0


# ---------------------------------------------------------------------------
# C. Fresh-load lineage continuity (API level)
# ---------------------------------------------------------------------------


def test_fresh_load_lineage_evidence_api_contract(tmp_path: Path) -> None:
    """C: after confirm + publish, a completely rebuilt service stack over
    the same sqlite files still projects shadow-stage lineage evidence for
    the published pack, empty evidence for the draft pack, and 404 across
    projects."""
    fixture = _build_fixture(tmp_path)
    inspection, _confirmed_pack, published = (
        _confirmed_and_published_packs(fixture)
    )
    assert published.status == "published"
    shadow_pack_id = fixture.pack.rule_pack_id
    sample_set_id = inspection.sample_set.sample_set_id
    draft_pack_id = fixture.repository.rule_pack_lifecycle(shadow_pack_id)[
        "predecessor_rule_pack_id"
    ]

    client = _fresh_client(fixture)

    response = client.get(
        f"{_base()}/rule-packs/{published.rule_pack_id}"
        "/shadow-lineage-evidence"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == PROJECT
    assert payload["rule_pack_id"] == published.rule_pack_id
    assert payload["shadow_rule_pack_id"] == shadow_pack_id
    assert [item["sample_set_id"] for item in payload["items"]] == [
        sample_set_id
    ]
    confirmation = payload["confirmation"]
    assert confirmation is not None
    assert set(confirmation) == {
        "confirmation_id",
        "sample_set_id",
        "trusted_shadow_run_id",
        "confirmed_at",
    }
    assert confirmation["sample_set_id"] == sample_set_id

    draft = client.get(
        f"{_base()}/rule-packs/{draft_pack_id}/shadow-lineage-evidence"
    )
    assert draft.status_code == 200
    draft_payload = draft.json()
    assert draft_payload["shadow_rule_pack_id"] == ""
    assert draft_payload["items"] == []
    assert draft_payload["confirmation"] is None

    foreign = client.get(
        f"{_base(OTHER_PROJECT)}/rule-packs/{published.rule_pack_id}"
        "/shadow-lineage-evidence"
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["code"] == "monitoring_rule_pack_not_found"
