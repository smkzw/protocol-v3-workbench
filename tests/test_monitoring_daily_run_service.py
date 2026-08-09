from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from services.api.app.monitoring_batch_diff import (
    MONITORING_BATCH_DIFF_ALGORITHM_VERSION,
    diff_monitoring_batches,
)
from services.api.app.monitoring_daily_run_repository import (
    MonitoringDailyRunRepository,
)
from services.api.app.monitoring_daily_run_service import (
    MonitoringDailyRunService,
    MonitoringDailyRunServiceError,
    MonitoringRuleRuntimeIdentity,
)
from services.api.app.monitoring_record_rule_resolver import (
    RecordRuleAggregateIdentityError,
)


def _row(key: str, value: str = "头痛"):
    return SimpleNamespace(
        business_key=key,
        row_fingerprint=f"hash-{key}-{value}",
        to_dict=lambda: {
            "domain": "AE",
            "business_key": key,
            "data": {"AETERM": value},
            "source_locator": {"locator": f"listing:AE:{key}"},
        },
    )


def _diff_batch(
    batch_id: str,
    *,
    rows=(),
    schema_fields=(("AE", "AETERM", "AE"),),
    full_snapshot_proven=False,
):
    return SimpleNamespace(
        batch_id=batch_id,
        project_id="project-1",
        state="frozen",
        version=7,
        expected_domains=("AE",),
        active_mapping_revision="mapping-v1",
        mapping_revision="mapping-v1",
        source_bindings=((f"source-{batch_id}", f"sha-{batch_id}"),),
        source_hashes=(f"sha-{batch_id}",),
        rows=tuple(rows),
        schema_fields=tuple(schema_fields),
        full_snapshot_proven=full_snapshot_proven,
    )


class _BatchService:
    def __init__(self, previous, current):
        self.previous = previous
        self.current = current

    def detailed_diff(self, previous_batch_id, current_batch_id):
        from services.api.app.monitoring_batch_diff import diff_monitoring_batches
        from dataclasses import asdict

        detailed = diff_monitoring_batches(
            (row.to_dict() for row in self.previous.rows),
            (row.to_dict() for row in self.current.rows),
            previous_mapping_revision=self.previous.mapping_revision,
            current_mapping_revision=self.current.mapping_revision,
            expected_domains=set(self.current.expected_domains),
            full_snapshot_proven=True,
            previous_schema_fields=self.previous.schema_fields,
            current_schema_fields=self.current.schema_fields,
        )
        return {
            "previous_batch_id": previous_batch_id,
            "current_batch_id": current_batch_id,
            "row_diff": asdict(detailed.row_diff),
            "field_changes": [asdict(item) for item in detailed.field_changes],
            "schema_diffs": [asdict(item) for item in detailed.schema_diffs],
            "removal_eligible_keys": detailed.removal_eligible_keys,
            "removal_blocked_keys": detailed.removal_blocked_keys,
            "full_snapshot_proven": detailed.full_snapshot_proven,
            "algorithm_version": detailed.algorithm_version,
            "output_sha256": detailed.output_sha256,
        }


class _RuleRunner:
    def __init__(self):
        self.calls = 0

    def run(self, batch, *, rule_pack_id, capability_states=None):
        self.calls += 1
        assert capability_states
        return SimpleNamespace(
            to_dict=lambda: {
                "run_id": "batch-rule-run-1",
                "project_id": batch.project_id,
                "batch_id": batch.batch_id,
                "batch_version": batch.version,
                "mapping_revision": batch.mapping_revision,
                "rule_pack_id": rule_pack_id,
                "rule_revision_ids": ["rule-revision-1"],
                "evaluated_record_count": 2,
                "candidates": [{"candidate_id": "candidate-1"}],
                "diagnostics": [],
                "output_sha256": "f" * 64,
            }
        )


class MonitoringDailyRunServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.run_repository = MonitoringDailyRunRepository(
            Path(self.temporary.name) / "runs.sqlite3"
        )
        self.previous = _diff_batch("batch-1", rows=(_row("AE-1"),))
        self.current = _diff_batch(
            "batch-2",
            rows=(_row("AE-1", "头晕"), _row("AE-2")),
        )
        self.batch_repository = Mock()
        self.batch_repository.get_batch.side_effect = self._get_batch
        self.batch_repository.load_diff_ready_batch.side_effect = self._get_batch
        self.batch_repository.load_frozen_mapping_contract.return_value = (
            SimpleNamespace(
                mapping_revision="mapping-v1",
                mapping_content_sha256="b" * 64,
                capability_manifest_sha256="c" * 64,
                effective_capabilities_sha256="d" * 64,
                capability_states=(
                    {
                        "capability_id": "raw_source_review",
                        "state": "ready",
                        "limitation_codes": [],
                        "blocking_finding_group_ids": [],
                    },
                ),
            )
        )
        self.service = MonitoringDailyRunService(
            run_repository=self.run_repository,
            batch_repository=self.batch_repository,
            batch_service=_BatchService(self.previous, self.current),
            rule_runtime_resolver=lambda project_id: MonitoringRuleRuntimeIdentity(
                rule_pack_revision="rule-pack-v1",
                engine_version="rule-engine-v1",
            ),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_diff_input_identity_binds_full_snapshot_proof(self):
        unproven = _diff_batch("batch-proof", full_snapshot_proven=False)
        proven = _diff_batch("batch-proof", full_snapshot_proven=True)

        self.assertNotEqual(
            self.service._diff_batch_identity(unproven),
            self.service._diff_batch_identity(proven),
        )

    def _get_batch(self, batch_id):
        if batch_id == self.previous.batch_id:
            return self.previous
        if batch_id == self.current.batch_id:
            return self.current
        raise KeyError(batch_id)

    def _confirm_initial_baseline(self):
        prepared = self.service.prepare(
            project_id="project-1",
            batch_id=self.previous.batch_id,
            idempotency_key="prepare-initial",
            actor="medical_manager",
        ).run
        processed = self.service.process_prepared(
            project_id="project-1",
            run_id=prepared.run_id,
            expected_version=prepared.version,
            owner="worker-1",
        ).run
        processed = self.run_repository.save_rule_snapshot(
            "project-1",
            processed.run_id,
            input_sha256="a" * 64,
            payload={
                "project_id": "project-1",
                "batch_id": processed.batch_id,
                "rule_pack_id": processed.rule_pack_revision,
                "candidates": [],
                "diagnostics": [],
            },
            expected_version=processed.version,
            actor="worker-1",
        ).run
        bound = self.run_repository.bind_risk_snapshot(
            "project-1",
            processed.run_id,
            risk_snapshot_id="risk-snapshot-1",
            expected_version=processed.version,
            actor="worker-1",
        ).run
        review = self.run_repository.transition(
            "project-1",
            bound.run_id,
            target_status="risk_review",
            expected_version=bound.version,
            actor="medical_manager",
        )
        ready = self.run_repository.transition(
            "project-1",
            review.run_id,
            target_status="ready_to_confirm",
            expected_version=review.version,
            actor="medical_manager",
        )
        return self.run_repository.confirm_run(
            "project-1",
            ready.run_id,
            expected_run_version=ready.version,
            expected_baseline_revision=0,
            confirmed_by="medical_manager",
        )

    def test_prepare_requires_frozen_mapped_batch_and_server_rule_identity(self):
        not_frozen = SimpleNamespace(
            **{**self.current.__dict__, "state": "parsed"}
        )
        self.batch_repository.get_batch.side_effect = lambda batch_id: not_frozen
        with self.assertRaises(MonitoringDailyRunServiceError) as raised:
            self.service.prepare(
                project_id="project-1",
                batch_id="batch-2",
                idempotency_key="bad-state",
                actor="medical_manager",
            )
        self.assertEqual("monitoring_batch_not_frozen", raised.exception.code)

        unmapped = SimpleNamespace(
            **{**self.current.__dict__, "active_mapping_revision": None}
        )
        self.batch_repository.get_batch.side_effect = lambda batch_id: unmapped
        with self.assertRaises(MonitoringDailyRunServiceError) as raised:
            self.service.prepare(
                project_id="project-1",
                batch_id="batch-2",
                idempotency_key="missing-mapping",
                actor="medical_manager",
            )
        self.assertEqual("monitoring_mapping_required", raised.exception.code)

    def test_readiness_projects_gate_without_creating_a_run(self):
        readiness = self.service.start_readiness(
            project_id="project-1",
            batch_id="batch-1",
        )
        self.assertTrue(readiness["ready"])
        self.assertEqual("start_daily_run", readiness["next_action"])
        self.assertEqual("mapping-v1", readiness["mapping_revision"])
        self.assertEqual((), self.run_repository.list_runs("project-1"))

    def test_readiness_rejects_batch_bound_to_noncurrent_mapping(self):
        service = MonitoringDailyRunService(
            run_repository=self.run_repository,
            batch_repository=self.batch_repository,
            batch_service=_BatchService(self.previous, self.current),
            rule_runtime_resolver=lambda project_id: MonitoringRuleRuntimeIdentity(
                rule_pack_revision="rule-pack-v1",
                engine_version="rule-engine-v1",
            ),
            active_mapping_resolver=lambda project_id: SimpleNamespace(
                mapping_revision="mapping-v2",
            ),
        )
        readiness = service.start_readiness(
            project_id="project-1",
            batch_id="batch-1",
        )
        self.assertFalse(readiness["ready"])
        self.assertEqual("monitoring_mapping_changed", readiness["state_code"])
        self.assertEqual("confirm_mapping", readiness["next_action"])
        self.assertEqual((), self.run_repository.list_runs("project-1"))

    def test_initial_batch_skips_diff_and_advances_to_rules(self):
        prepared = self.service.prepare(
            project_id="project-1",
            batch_id="batch-1",
            idempotency_key="prepare-1",
            actor="medical_manager",
        ).run
        self.assertIsNone(prepared.baseline_batch_id)
        self.assertEqual(
            MONITORING_BATCH_DIFF_ALGORITHM_VERSION,
            prepared.diff_algorithm_version,
        )

        result = self.service.process_prepared(
            project_id="project-1",
            run_id=prepared.run_id,
            expected_version=prepared.version,
            owner="worker-1",
        )

        self.assertEqual("rules_running", result.run.status)
        self.assertEqual("run_rules", result.next_action)
        self.assertIsNone(result.diff_snapshot)
        self.assertEqual(
            "completed",
            self.run_repository.list_steps(prepared.run_id)[0].status,
        )

    def test_rule_execution_freezes_result_before_ai_transition(self):
        runner = _RuleRunner()
        service = MonitoringDailyRunService(
            run_repository=self.run_repository,
            batch_repository=self.batch_repository,
            batch_service=_BatchService(self.previous, self.current),
            rule_runtime_resolver=lambda project_id: MonitoringRuleRuntimeIdentity(
                rule_pack_revision="rule-pack-v1",
                engine_version="rule-engine-v1",
                rule_mapping_revision="mapping-v1",
                rule_mapping_content_sha256="b" * 64,
                rule_capability_manifest_sha256="c" * 64,
                rule_effective_capabilities_sha256="d" * 64,
            ),
            rule_runner=runner,
        )
        prepared = service.prepare(
            project_id="project-1",
            batch_id=self.previous.batch_id,
            idempotency_key="prepare-rule-execution",
            actor="medical_manager",
        ).run
        processed = service.process_prepared(
            project_id="project-1",
            run_id=prepared.run_id,
            expected_version=prepared.version,
            owner="worker-1",
        ).run

        result = service.execute_rules(
            project_id="project-1",
            run_id=processed.run_id,
            expected_version=processed.version,
            owner="rule-worker",
        )

        self.assertEqual("ai_running", result.run.status)
        self.assertEqual("run_independent_ai", result.next_action)
        self.assertEqual("project_effective", result.run.rule_resolution_mode)
        self.assertEqual(
            "project_effective",
            result.rule_snapshot.resolution_mode,
        )
        self.assertEqual(
            "rule-pack-v1",
            result.rule_snapshot.rule_pack_id,
        )
        self.assertEqual(1, runner.calls)
        self.assertEqual(
            "candidate-1",
            result.rule_snapshot.payload["candidates"][0]["candidate_id"],
        )
        self.assertEqual(
            "completed",
            self.run_repository.list_steps(prepared.run_id)[-1].status,
        )

    def test_rule_execution_rejects_legacy_batch_without_capability_snapshot(
        self,
    ):
        runner = _RuleRunner()
        self.batch_repository.load_frozen_mapping_contract.return_value = (
            SimpleNamespace(
                mapping_revision="mapping-v1",
                capability_manifest_sha256="",
                effective_capabilities_sha256="",
                capability_states=(),
            )
        )
        service = MonitoringDailyRunService(
            run_repository=self.run_repository,
            batch_repository=self.batch_repository,
            batch_service=_BatchService(self.previous, self.current),
            rule_runtime_resolver=lambda project_id: MonitoringRuleRuntimeIdentity(
                rule_pack_revision="rule-pack-v1",
                engine_version="rule-engine-v1",
            ),
            rule_runner=runner,
        )
        with self.assertRaises(MonitoringDailyRunServiceError) as raised:
            service.prepare(
                project_id="project-1",
                batch_id=self.previous.batch_id,
                idempotency_key="prepare-legacy-capability-contract",
                actor="medical_manager",
            )

        self.assertEqual(
            "monitoring_capability_contract_required",
            raised.exception.code,
        )
        self.assertEqual(0, runner.calls)
        self.assertEqual((), self.run_repository.list_runs("project-1"))

    def test_prepare_fails_before_run_creation_when_product_ai_is_not_ready(self):
        service = MonitoringDailyRunService(
            run_repository=self.run_repository,
            batch_repository=self.batch_repository,
            batch_service=_BatchService(self.previous, self.current),
            rule_runtime_resolver=lambda project_id: MonitoringRuleRuntimeIdentity(
                rule_pack_revision="rule-pack-v1",
                engine_version="rule-engine-v1",
            ),
            ai_runtime_resolver=lambda: SimpleNamespace(
                available=False,
                diagnostic="独立 AI 配置未就绪",
                transport="",
            ),
        )

        with self.assertRaises(MonitoringDailyRunServiceError) as raised:
            service.prepare(
                project_id="project-1",
                batch_id="batch-1",
                idempotency_key="prepare-ai-blocked",
                actor="medical_manager",
            )

        self.assertEqual("monitoring_ai_not_ready", raised.exception.code)
        self.assertEqual((), self.run_repository.list_runs("project-1"))

    def test_prepare_fails_closed_for_malformed_ai_runtime_availability(self):
        for malformed in ("false", 1):
            with self.subTest(malformed=malformed):
                service = MonitoringDailyRunService(
                    run_repository=self.run_repository,
                    batch_repository=self.batch_repository,
                    batch_service=_BatchService(self.previous, self.current),
                    rule_runtime_resolver=lambda project_id: MonitoringRuleRuntimeIdentity(
                        rule_pack_revision="rule-pack-v1",
                        engine_version="rule-engine-v1",
                    ),
                    ai_runtime_resolver=lambda value=malformed: SimpleNamespace(
                        available=value,
                        diagnostic="独立 AI 配置状态类型无效",
                        transport="openai_compatible",
                    ),
                )

                with self.assertRaises(MonitoringDailyRunServiceError) as raised:
                    service.prepare(
                        project_id="project-1",
                        batch_id="batch-1",
                        idempotency_key=f"prepare-ai-malformed-{malformed}",
                        actor="medical_manager",
                    )

                self.assertEqual(
                    "monitoring_ai_not_ready",
                    raised.exception.code,
                )
                self.assertEqual((), self.run_repository.list_runs("project-1"))

    def test_incremental_batch_persists_diff_and_advances_to_rules(self):
        self._confirm_initial_baseline()
        prepared = self.service.prepare(
            project_id="project-1",
            batch_id="batch-2",
            idempotency_key="prepare-2",
            actor="medical_manager",
        ).run

        result = self.service.process_prepared(
            project_id="project-1",
            run_id=prepared.run_id,
            expected_version=prepared.version,
            owner="worker-2",
        )

        self.assertEqual("batch-1", prepared.baseline_batch_id)
        self.assertEqual("rules_running", result.run.status)
        self.assertEqual("run_rules", result.next_action)
        self.assertIsNotNone(result.diff_snapshot)
        self.assertEqual(
            result.diff_snapshot.snapshot_id,
            result.run.diff_snapshot_id,
        )

    def test_header_only_schema_drift_stops_before_rules(self):
        self._confirm_initial_baseline()
        self.current.schema_fields = (
            *self.current.schema_fields,
            ("AE", "AESEV", "AE"),
        )
        prepared = self.service.prepare(
            project_id="project-1",
            batch_id="batch-2",
            idempotency_key="prepare-drift",
            actor="medical_manager",
        ).run

        result = self.service.process_prepared(
            project_id="project-1",
            run_id=prepared.run_id,
            expected_version=prepared.version,
            owner="worker-2",
        )

        self.assertEqual("drift_review_required", result.run.status)
        self.assertEqual("review_mapping_drift", result.next_action)
        self.assertEqual(["AESEV"], result.diff_snapshot.payload["schema_diffs"][0]["added_fields"])

    def test_unresolved_removal_identity_stops_before_rules(self):
        """Ambiguous identity must not be interpreted as a resolved deletion."""
        self._confirm_initial_baseline()
        alias = "edc-display-v1|AE|01|S01|V1"

        def row(key: str, term: str) -> dict:
            return {
                "domain": "AE",
                "business_key": key,
                "data": {"AETERM": term},
                "source_locator": {
                    "locator": f"listing:AE:{key}",
                    "identity_aliases": [alias],
                },
            }

        detailed = diff_monitoring_batches(
            [row("old-1", "头痛"), row("old-2", "恶心")],
            [row("new-1", "皮疹"), row("new-2", "瘙痒")],
            expected_domains={"AE"},
            full_snapshot_proven=True,
        )
        payload = asdict(detailed)
        payload.update(
            previous_batch_id=self.previous.batch_id,
            current_batch_id=self.current.batch_id,
        )
        self.service.batch_service.detailed_diff = Mock(return_value=payload)

        prepared = self.service.prepare(
            project_id="project-1",
            batch_id=self.current.batch_id,
            idempotency_key="prepare-ambiguous-removal",
            actor="medical_manager",
        ).run
        result = self.service.process_prepared(
            project_id="project-1",
            run_id=prepared.run_id,
            expected_version=prepared.version,
            owner="worker-ambiguous-removal",
        )

        self.assertEqual("drift_review_required", result.run.status)
        self.assertEqual("review_mapping_drift", result.next_action)
        self.assertEqual(
            ["old-1", "old-2"],
            result.diff_snapshot.payload["removal_blocked_keys"],
        )
        transitions = [
            event
            for event in self.run_repository.list_events(prepared.run_id)
            if event.event_type == "run_status_changed"
        ]
        self.assertEqual(
            ["removal_resolution_blocked"],
            transitions[-1].payload["drift_reasons"],
        )

    def test_unproven_full_snapshot_stops_before_rules(self):
        self._confirm_initial_baseline()
        payload = {
            "previous_batch_id": self.previous.batch_id,
            "current_batch_id": self.current.batch_id,
            "row_diff": {
                "new_keys": [],
                "changed_keys": [],
                "persisting_keys": ["AE-1"],
                "removed_keys": [],
                "requires_rereview_keys": [],
                "missing_current_domains": [],
                "removal_resolution_blocked_keys": [],
            },
            "field_changes": [],
            "schema_diffs": [],
            "removal_eligible_keys": [],
            "removal_blocked_keys": [],
            "full_snapshot_proven": False,
            "algorithm_version": MONITORING_BATCH_DIFF_ALGORITHM_VERSION,
            "output_sha256": "f" * 64,
        }
        self.service.batch_service.detailed_diff = Mock(return_value=payload)

        prepared = self.service.prepare(
            project_id="project-1",
            batch_id=self.current.batch_id,
            idempotency_key="prepare-unproven-snapshot",
            actor="medical_manager",
        ).run
        result = self.service.process_prepared(
            project_id="project-1",
            run_id=prepared.run_id,
            expected_version=prepared.version,
            owner="worker-unproven-snapshot",
        )

        self.assertEqual("drift_review_required", result.run.status)
        self.assertEqual(
            ["full_snapshot_unproven"],
            [
                event.payload["drift_reasons"]
                for event in self.run_repository.list_events(prepared.run_id)
                if event.event_type == "run_status_changed"
                and "drift_reasons" in event.payload
            ][-1],
        )

    def test_incremental_processing_resumes_after_crash_in_diffing(self):
        self._confirm_initial_baseline()
        prepared = self.service.prepare(
            project_id="project-1",
            batch_id="batch-2",
            idempotency_key="prepare-resume",
            actor="medical_manager",
        ).run
        claimed = self.run_repository.claim(
            "project-1",
            prepared.run_id,
            owner="crashed-worker",
            expected_version=prepared.version,
        )
        diffing = self.run_repository.transition(
            "project-1",
            prepared.run_id,
            target_status="diffing",
            expected_version=claimed.version,
            actor="crashed-worker",
            lease_owner="crashed-worker",
            lease_epoch=claimed.lease_epoch,
        )
        released = self.run_repository.release_lease(
            "project-1",
            prepared.run_id,
            owner="crashed-worker",
            lease_epoch=diffing.lease_epoch,
        )

        resumed = self.service.process_prepared(
            project_id="project-1",
            run_id=prepared.run_id,
            expected_version=released.version,
            owner="recovery-worker",
        )

        self.assertEqual("rules_running", resumed.run.status)
        self.assertEqual("run_rules", resumed.next_action)
        self.assertIsNotNone(resumed.diff_snapshot)
        self.assertEqual(
            "completed",
            self.run_repository.list_steps(prepared.run_id)[0].status,
        )

    def test_rules_running_replay_does_not_repeat_diff(self):
        self._confirm_initial_baseline()
        prepared = self.service.prepare(
            project_id="project-1",
            batch_id="batch-2",
            idempotency_key="prepare-rules-replay",
            actor="medical_manager",
        ).run
        first = self.service.process_prepared(
            project_id="project-1",
            run_id=prepared.run_id,
            expected_version=prepared.version,
            owner="worker-2",
        )

        replayed = self.service.process_prepared(
            project_id="project-1",
            run_id=prepared.run_id,
            expected_version=first.run.version,
            owner="worker-3",
        )

        self.assertEqual("rules_running", replayed.run.status)
        self.assertEqual(first.diff_snapshot.snapshot_id, replayed.diff_snapshot.snapshot_id)
        self.assertEqual(1, len(self.run_repository.list_steps(prepared.run_id)))

    def _service_with_active_mapping(
        self,
        *,
        identity=None,
        record_rule_resolver=None,
        rule_runner=None,
        resolver=None,
    ):
        return MonitoringDailyRunService(
            run_repository=self.run_repository,
            batch_repository=self.batch_repository,
            batch_service=_BatchService(self.previous, self.current),
            rule_runtime_resolver=resolver
            or (
                lambda project_id: (
                    identity
                    if identity is not None
                    else MonitoringRuleRuntimeIdentity(
                        rule_pack_revision="rule-pack-v1",
                        engine_version="rule-engine-v1",
                        rule_mapping_revision="mapping-v1",
                        rule_mapping_content_sha256="b" * 64,
                        rule_capability_manifest_sha256="c" * 64,
                        rule_effective_capabilities_sha256="d" * 64,
                    )
                )
            ),
            active_mapping_resolver=lambda project_id: SimpleNamespace(
                mapping_revision="mapping-v1",
                mapping_content_sha256="b" * 64,
                capability_manifest_sha256="c" * 64,
                effective_capabilities_sha256="d" * 64,
            ),
            record_rule_resolver=record_rule_resolver,
            rule_runner=rule_runner,
        )

    def test_readiness_ready_when_rule_identity_matches_active_mapping(self):
        service = self._service_with_active_mapping()

        readiness = service.start_readiness(
            project_id="project-1",
            batch_id="batch-1",
        )

        self.assertTrue(readiness["ready"])
        self.assertEqual("start_daily_run", readiness["next_action"])
        self.assertEqual((), self.run_repository.list_runs("project-1"))

    def test_rule_identity_drift_fails_closed_for_readiness_and_creation(self):
        drift_cases = (
            MonitoringRuleRuntimeIdentity(
                rule_pack_revision="rule-pack-v1",
                engine_version="rule-engine-v1",
                rule_mapping_revision="mapping-v0",
                rule_mapping_content_sha256="b" * 64,
                rule_capability_manifest_sha256="c" * 64,
                rule_effective_capabilities_sha256="d" * 64,
            ),
            MonitoringRuleRuntimeIdentity(
                rule_pack_revision="rule-pack-v1",
                engine_version="rule-engine-v1",
                rule_mapping_revision="mapping-v1",
                rule_mapping_content_sha256="b" * 64,
                rule_capability_manifest_sha256="e" * 64,
                rule_effective_capabilities_sha256="d" * 64,
            ),
            MonitoringRuleRuntimeIdentity(
                rule_pack_revision="rule-pack-v1",
                engine_version="rule-engine-v1",
                rule_mapping_revision="mapping-v1",
                rule_mapping_content_sha256="b" * 64,
                rule_capability_manifest_sha256="c" * 64,
                rule_effective_capabilities_sha256="f" * 64,
            ),
        )
        for index, identity in enumerate(drift_cases):
            with self.subTest(case=index):
                service = self._service_with_active_mapping(identity=identity)

                readiness = service.start_readiness(
                    project_id="project-1",
                    batch_id="batch-1",
                )

                self.assertFalse(readiness["ready"])
                self.assertEqual(
                    "monitoring_rule_pack_identity_drift",
                    readiness["state_code"],
                )
                self.assertEqual(
                    "prepare_rule_pack",
                    readiness["next_action"],
                )
                with self.assertRaises(MonitoringDailyRunServiceError) as raised:
                    service.prepare(
                        project_id="project-1",
                        batch_id="batch-1",
                        idempotency_key=f"prepare-drift-{index}",
                        actor="medical_manager",
                    )
                self.assertEqual(
                    "monitoring_rule_pack_identity_drift",
                    raised.exception.code,
                )
                self.assertEqual(
                    (),
                    self.run_repository.list_runs("project-1"),
                )

    def test_rule_identity_unverifiable_fails_closed(self):
        service = self._service_with_active_mapping(
            identity=MonitoringRuleRuntimeIdentity(
                rule_pack_revision="rule-pack-v1",
                engine_version="rule-engine-v1",
            ),
        )

        readiness = service.start_readiness(
            project_id="project-1",
            batch_id="batch-1",
        )

        self.assertFalse(readiness["ready"])
        self.assertEqual(
            "monitoring_rule_pack_identity_unverifiable",
            readiness["state_code"],
        )
        self.assertEqual("prepare_rule_pack", readiness["next_action"])
        with self.assertRaises(MonitoringDailyRunServiceError) as raised:
            service.prepare(
                project_id="project-1",
                batch_id="batch-1",
                idempotency_key="prepare-unverifiable",
                actor="medical_manager",
            )
        self.assertEqual(
            "monitoring_rule_pack_identity_unverifiable",
            raised.exception.code,
        )
        self.assertEqual((), self.run_repository.list_runs("project-1"))

    def test_project_effective_identity_digests_require_exact_lowercase_hex(self):
        for field in (
            "rule_mapping_content_sha256",
            "rule_capability_manifest_sha256",
            "rule_effective_capabilities_sha256",
            "rule_identity_sha256",
        ):
            for malformed in (f" {'a' * 64}", "A" * 64, 123):
                with self.subTest(field=field, malformed=repr(malformed)):
                    service = self._service_with_active_mapping(
                        identity=self._valid_project_identity(
                            **{field: malformed}
                        )
                    )
                    readiness = service.start_readiness(
                        project_id="project-1",
                        batch_id="batch-1",
                    )
                    self.assertFalse(readiness["ready"])
                    self.assertEqual(
                        "monitoring_rule_pack_identity_unverifiable",
                        readiness["state_code"],
                    )
                    with self.assertRaises(
                        MonitoringDailyRunServiceError
                    ) as raised:
                        service.prepare(
                            project_id="project-1",
                            batch_id="batch-1",
                            idempotency_key=(
                                f"prepare-noncanonical-{field}-{malformed!r}"
                            ),
                            actor="medical_manager",
                        )
                    self.assertEqual(
                        "monitoring_rule_pack_identity_unverifiable",
                        raised.exception.code,
                    )

    def test_frozen_mapping_contract_digests_require_exact_lowercase_hex(self):
        original = self.batch_repository.load_frozen_mapping_contract.return_value
        for field in (
            "mapping_content_sha256",
            "capability_manifest_sha256",
            "effective_capabilities_sha256",
        ):
            for malformed in (f" {'b' * 64}", "B" * 64, 123):
                with self.subTest(field=field, malformed=repr(malformed)):
                    self.batch_repository.load_frozen_mapping_contract.return_value = SimpleNamespace(
                        **{
                            **vars(original),
                            field: malformed,
                        }
                    )
                    service = self._service_with_active_mapping()
                    readiness = service.start_readiness(
                        project_id="project-1",
                        batch_id="batch-1",
                    )
                    self.assertFalse(readiness["ready"])
                    self.assertEqual(
                        "monitoring_capability_contract_required",
                        readiness["state_code"],
                    )
        self.batch_repository.load_frozen_mapping_contract.return_value = original

    def test_active_mapping_digests_require_exact_lowercase_hex(self):
        for field in (
            "mapping_content_sha256",
            "capability_manifest_sha256",
            "effective_capabilities_sha256",
        ):
            for malformed in (f" {'b' * 64}", "B" * 64, 123):
                with self.subTest(field=field, malformed=repr(malformed)):
                    service = self._service_with_active_mapping()
                    service.active_mapping_resolver = (
                        lambda project_id, field=field, malformed=malformed: SimpleNamespace(
                            mapping_revision="mapping-v1",
                            mapping_content_sha256=(
                                malformed
                                if field == "mapping_content_sha256"
                                else "b" * 64
                            ),
                            capability_manifest_sha256=(
                                malformed
                                if field == "capability_manifest_sha256"
                                else "c" * 64
                            ),
                            effective_capabilities_sha256=(
                                malformed
                                if field == "effective_capabilities_sha256"
                                else "d" * 64
                            ),
                        )
                    )
                    readiness = service.start_readiness(
                        project_id="project-1",
                        batch_id="batch-1",
                    )
                    self.assertFalse(readiness["ready"])
                    self.assertEqual(
                        "monitoring_rule_pack_identity_unverifiable",
                        readiness["state_code"],
                    )

    def _record_mode_resolver(
        self,
        *,
        mapping_revision="mapping-v1",
        mapping_content_sha256="b" * 64,
        capability_manifest_sha256="c" * 64,
        effective_capabilities_sha256="d" * 64,
        identity_sha256="a" * 64,
    ):
        record_resolver = Mock()
        record_resolver.project_supports_record_resolution.return_value = True
        record_resolver.aggregate_identity.return_value = SimpleNamespace(
            identity_sha256=identity_sha256,
            mapping_revision=mapping_revision,
            mapping_content_sha256=mapping_content_sha256,
            capability_manifest_sha256=capability_manifest_sha256,
            effective_capabilities_sha256=effective_capabilities_sha256,
        )
        return record_resolver

    def test_record_applicability_mode_freezes_aggregate_identity(self):
        service = self._service_with_active_mapping(
            record_rule_resolver=self._record_mode_resolver(),
        )

        prepared = service.prepare(
            project_id="project-1",
            batch_id="batch-1",
            idempotency_key="prepare-record-applicability",
            actor="medical_manager",
        ).run

        self.assertEqual(
            "record_applicability",
            prepared.rule_resolution_mode,
        )
        self.assertEqual("a" * 64, prepared.rule_identity_sha256)
        self.assertEqual("", prepared.rule_pack_revision)

    def test_record_applicability_mode_enforces_mapping_identity_drift(self):
        service = self._service_with_active_mapping(
            record_rule_resolver=self._record_mode_resolver(
                mapping_content_sha256="9" * 64,
            ),
        )

        readiness = service.start_readiness(
            project_id="project-1",
            batch_id="batch-1",
        )

        self.assertFalse(readiness["ready"])
        self.assertEqual(
            "monitoring_rule_pack_identity_drift",
            readiness["state_code"],
        )
        self.assertEqual("prepare_rule_pack", readiness["next_action"])
        with self.assertRaises(MonitoringDailyRunServiceError) as raised:
            service.prepare(
                project_id="project-1",
                batch_id="batch-1",
                idempotency_key="prepare-record-drift",
                actor="medical_manager",
            )
        self.assertEqual(
            "monitoring_rule_pack_identity_drift",
            raised.exception.code,
        )
        self.assertEqual((), self.run_repository.list_runs("project-1"))

    def test_record_applicability_mode_propagates_unverifiable_identity(self):
        record_resolver = self._record_mode_resolver()
        record_resolver.aggregate_identity.side_effect = (
            RecordRuleAggregateIdentityError(
                "monitoring_rule_pack_identity_unverifiable",
                "已发布规则缺少可追溯的字段映射身份。",
            )
        )
        service = self._service_with_active_mapping(
            record_rule_resolver=record_resolver,
        )

        readiness = service.start_readiness(
            project_id="project-1",
            batch_id="batch-1",
        )

        self.assertFalse(readiness["ready"])
        self.assertEqual(
            "monitoring_rule_pack_identity_unverifiable",
            readiness["state_code"],
        )
        self.assertEqual("prepare_rule_pack", readiness["next_action"])
        with self.assertRaises(MonitoringDailyRunServiceError) as raised:
            service.prepare(
                project_id="project-1",
                batch_id="batch-1",
                idempotency_key="prepare-record-unverifiable",
                actor="medical_manager",
            )
        self.assertEqual(
            "monitoring_rule_pack_identity_unverifiable",
            raised.exception.code,
        )
        self.assertEqual((), self.run_repository.list_runs("project-1"))

    def test_record_applicability_identity_digests_require_exact_lowercase_hex(
        self,
    ):
        cases = (
            {"mapping_content_sha256": f" {'b' * 64}"},
            {"capability_manifest_sha256": "C" * 64},
            {"effective_capabilities_sha256": 123},
            {"identity_sha256": f"{'a' * 64} "},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                resolver = self._record_mode_resolver(**overrides)
                service = self._service_with_active_mapping(
                    record_rule_resolver=resolver,
                )
                readiness = service.start_readiness(
                    project_id="project-1",
                    batch_id="batch-1",
                )
                self.assertFalse(readiness["ready"])
                self.assertEqual(
                    "monitoring_rule_pack_identity_unverifiable",
                    readiness["state_code"],
                )

    def test_persisted_record_identity_digest_is_not_normalized(self):
        resolver = self._record_mode_resolver()
        service = self._service_with_active_mapping(
            record_rule_resolver=resolver,
        )
        for malformed in ("A" * 64, f"{'a' * 64} "):
            with self.subTest(malformed=repr(malformed)):
                with self.assertRaises(MonitoringDailyRunServiceError) as raised:
                    service._assert_record_rule_identity_frozen(
                        SimpleNamespace(
                            project_id="project-1",
                            rule_identity_sha256=malformed,
                        )
                    )
                self.assertEqual(
                    "monitoring_rule_identity_unverifiable",
                    raised.exception.code,
                )
        resolver.aggregate_identity.assert_not_called()

    def _valid_project_identity(self, **overrides):
        values = {
            "rule_pack_revision": "rule-pack-v1",
            "engine_version": "rule-engine-v1",
            "rule_mapping_revision": "mapping-v1",
            "rule_mapping_content_sha256": "b" * 64,
            "rule_capability_manifest_sha256": "c" * 64,
            "rule_effective_capabilities_sha256": "d" * 64,
        }
        values.update(overrides)
        return MonitoringRuleRuntimeIdentity(**values)

    def _assert_pre_execute_drift_blocked(self, drifted, key):
        runner = _RuleRunner()
        holder = {"identity": self._valid_project_identity()}
        service = self._service_with_active_mapping(
            resolver=lambda project_id: holder["identity"],
            rule_runner=runner,
        )
        prepared = service.prepare(
            project_id="project-1",
            batch_id="batch-1",
            idempotency_key=f"prepare-execute-drift-{key}",
            actor="medical_manager",
        ).run
        processed = service.process_prepared(
            project_id="project-1",
            run_id=prepared.run_id,
            expected_version=prepared.version,
            owner="worker-1",
        ).run

        # The published pack identity drifts after preparation but
        # before the first rule execution.
        holder["identity"] = drifted
        with self.assertRaises(MonitoringDailyRunServiceError) as raised:
            service.execute_rules(
                project_id="project-1",
                run_id=processed.run_id,
                expected_version=processed.version,
                owner="rule-worker",
            )

        self.assertEqual(
            "monitoring_rule_identity_changed",
            raised.exception.code,
        )
        self.assertEqual(0, runner.calls)

    def test_pre_execute_mapping_revision_drift_fails_before_rule_runner(self):
        self._assert_pre_execute_drift_blocked(
            self._valid_project_identity(rule_mapping_revision="mapping-v2"),
            "mapping-revision",
        )

    def test_pre_execute_empty_identity_fails_before_rule_runner(self):
        self._assert_pre_execute_drift_blocked(
            self._valid_project_identity(rule_effective_capabilities_sha256=""),
            "empty-effective",
        )

    def test_project_effective_snapshot_replay_skips_identity_revalidation(
        self,
    ):
        runner = _RuleRunner()
        holder = {"identity": self._valid_project_identity()}
        service = self._service_with_active_mapping(
            resolver=lambda project_id: holder["identity"],
            rule_runner=runner,
        )
        prepared = service.prepare(
            project_id="project-1",
            batch_id="batch-1",
            idempotency_key="prepare-execute-replay",
            actor="medical_manager",
        ).run
        processed = service.process_prepared(
            project_id="project-1",
            run_id=prepared.run_id,
            expected_version=prepared.version,
            owner="worker-1",
        ).run

        # Simulate a worker crash after the rule snapshot was frozen but
        # before the deterministic-rules step was completed.
        original_finish_step = self.run_repository.finish_step

        def crashing_finish_step(*args, **kwargs):
            raise RuntimeError("simulated worker crash")

        self.run_repository.finish_step = crashing_finish_step
        try:
            with self.assertRaises(RuntimeError):
                service.execute_rules(
                    project_id="project-1",
                    run_id=processed.run_id,
                    expected_version=processed.version,
                    owner="rule-worker",
                )
        finally:
            self.run_repository.finish_step = original_finish_step
        self.assertEqual(1, runner.calls)

        # The published pack identity drifts after the snapshot was frozen;
        # intentional stored-snapshot replay must not be invalidated.
        holder["identity"] = self._valid_project_identity(
            rule_pack_revision="rule-pack-v2",
        )
        current = self.run_repository.list_runs("project-1")[0]
        replayed = service.execute_rules(
            project_id="project-1",
            run_id=current.run_id,
            expected_version=current.version,
            owner="rule-worker",
        )

        self.assertEqual(1, runner.calls)
        self.assertEqual("ai_running", replayed.run.status)
        self.assertEqual("run_independent_ai", replayed.next_action)
