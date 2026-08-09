from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from packages.contracts.workbench_contracts.models import RiskCase, RiskSeverity, RiskStatus
from services.api.app.medical_monitoring_summary import _latest_batch_projection
from services.api.app.medical_risk_repository import MedicalRiskRepository


NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


def risk(
    instance_suffix: str = "001",
    source_revision: str = "monsrcv_001",
    *,
    risk_key: str = "riskkey_shared",
    severity: RiskSeverity = RiskSeverity.HIGH,
    title: str = "AE与MH记录不一致",
    rule_profile_revision: str = "rules_v1",
    engine_version: str = "engine_v1",
) -> RiskCase:
    return RiskCase(
        risk_id=f"legacy_{instance_suffix}",
        risk_key=risk_key,
        risk_instance_id=f"riskinst_{instance_suffix}",
        project_id="proj_test",
        module="medical_monitoring",
        risk_type="AE/MH漏报",
        primary_category="safety_ae_mh",
        tags=["safety_pv"],
        title=title,
        subject_id="S001",
        site_id="01",
        severity=severity,
        status=RiskStatus.ACTION_REQUIRED,
        source_batch_id=f"batch_{instance_suffix}",
        source_revision=source_revision,
        rule_profile_revision=rule_profile_revision,
        engine_version=engine_version,
        batch_delta="unclassified",
        rule_id="AE_MH_RECONCILIATION",
        evidence_span_ids=["listing:AE:row:1"],
        rationale="AE与MH记录需核对。",
        recommended_action="医学复核。",
        created_at=NOW,
    )


class MedicalRiskRepositoryTests(unittest.TestCase):
    def test_resolution_complete_write_requires_literal_boolean(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            for malformed in ("false", 0, 1, None):
                with self.subTest(malformed=malformed):
                    with self.assertRaisesRegex(
                        ValueError,
                        "resolution_complete must be a boolean",
                    ):
                        repository.save_snapshot(
                            project_id="proj_test",
                            source_revision=f"monsrcv_{malformed!s}",
                            rule_profile_revision="rules_v1",
                            engine_version="engine_v1",
                            evaluated_subject_count=0,
                            risks=[],
                            resolution_complete=malformed,
                        )

    def test_malformed_persisted_resolution_complete_fails_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "risk.sqlite3"
            repository = MedicalRiskRepository(db_path)
            snapshot = repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=0,
                risks=[],
                resolution_complete=False,
            )

            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    "UPDATE medical_risk_snapshots SET resolution_complete = ? WHERE snapshot_id = ?",
                    ("false", snapshot.snapshot_id),
                )

            error_text = (
                "medical_risk_snapshots.resolution_complete must be a SQLite boolean"
            )
            with self.assertRaisesRegex(ValueError, error_text):
                repository.current_snapshot("proj_test")

            with self.assertRaisesRegex(ValueError, error_text):
                repository.save_snapshot(
                    project_id="proj_test",
                    source_revision="monsrcv_001",
                    rule_profile_revision="rules_v1",
                    engine_version="engine_v1",
                    evaluated_subject_count=0,
                    risks=[],
                    resolution_complete=False,
                )

    def test_latest_batch_projection_does_not_coerce_truthy_text(self) -> None:
        snapshot = type(
            "Snapshot",
            (),
            {
                "snapshot_id": "snapshot_001",
                "source_revision": "monsrcv_001",
                "created_at": NOW,
                "resolution_complete": "false",
            },
        )()
        binding = type(
            "Binding",
            (),
            {
                "display_batch_label": "Batch 001",
                "display_extract_date": "2026-07-29",
            },
        )()

        projection = _latest_batch_projection(snapshot, binding)

        self.assertIs(projection["resolution_complete"], False)
        self.assertEqual("not_asserted", projection["completeness"])

    def test_snapshot_write_normalizes_legacy_category_without_text_refinement(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            snapshot = repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[
                    risk().model_copy(
                        update={
                            "title": "确定为禁用药PD",
                            "rationale": "自然语言包含AE漏报和永久停药。",
                        }
                    )
                ],
            )

            stored = repository.list_risks(
                "proj_test",
                snapshot.snapshot_id,
            )[0]
            self.assertEqual("other_medical_review", stored.primary_category)
            self.assertIn(
                "risk_category_lineage:legacy_coarse:safety_ae_mh",
                stored.tags,
            )

    def test_snapshot_lookup_is_project_scoped_for_pinned_pagination(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            snapshot = repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk()],
            )

            self.assertEqual(
                snapshot.snapshot_id,
                repository.snapshot(
                    "proj_test",
                    snapshot.snapshot_id,
                ).snapshot_id,
            )
            with self.assertRaises(KeyError):
                repository.snapshot(
                    "another_project",
                    snapshot.snapshot_id,
                )

    def test_snapshot_write_rejects_cm_and_study_treatment_domain_crossing(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            for primary_category, source_domain in (
                ("prohibited_concomitant_medication_pd", "ex"),
                ("study_treatment_restart", "cm"),
            ):
                with self.subTest(
                    primary_category=primary_category,
                    source_domain=source_domain,
                ):
                    with self.assertRaises(ValueError):
                        repository.save_snapshot(
                            project_id="proj_test",
                            source_revision="monsrcv_001",
                            rule_profile_revision="rules_v1",
                            engine_version="engine_v1",
                            evaluated_subject_count=1,
                            risks=[
                                risk().model_copy(
                                    update={
                                        "primary_category": primary_category,
                                        "tags": [f"source_domain:{source_domain}"],
                                    }
                                )
                            ],
                        )

    def test_snapshot_write_accepts_my009_ex_sheet_alias_for_study_treatment(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            snapshot = repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[
                    risk().model_copy(
                        update={
                            "primary_category": "study_treatment_adherence",
                            "tags": ["source_domain:ex2"],
                        }
                    )
                ],
            )

            stored = repository.list_risks(
                "proj_test",
                snapshot.snapshot_id,
            )[0]
            self.assertEqual("study_treatment_adherence", stored.primary_category)

    def test_p7_snapshot_and_risks_preserve_uploaded_batch_identity(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            snapshot = repository.save_snapshot(
                project_id="proj_test",
                source_batch_id="monbatch_001",
                source_revision="batch-content-sha256-001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[
                    risk(
                        "p7",
                        "batch-content-sha256-001",
                    ).model_copy(
                        update={"source_batch_id": "monbatch_001"}
                    )
                ],
            )

            restored = MedicalRiskRepository(
                Path(tmp) / "risk.sqlite3"
            ).current_snapshot("proj_test")
            stored_risk = repository.list_risks(
                "proj_test",
                snapshot.snapshot_id,
            )[0]
            self.assertEqual("monbatch_001", snapshot.source_batch_id)
            self.assertEqual("monbatch_001", restored.source_batch_id)
            self.assertEqual("monbatch_001", stored_risk.source_batch_id)

    def test_risk_instance_can_be_resolved_against_an_exact_historical_snapshot(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            first = repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk("same", "monsrcv_001")],
            )
            second = repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_002",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk("same", "monsrcv_002")],
            )

            latest_snapshot, latest_risk = repository.risk_instance(
                "proj_test", "riskinst_same"
            )
            historical_snapshot, historical_risk = repository.risk_instance(
                "proj_test", "riskinst_same", snapshot_id=first.snapshot_id
            )

            self.assertEqual(second.snapshot_id, latest_snapshot.snapshot_id)
            self.assertEqual("monsrcv_002", latest_risk.source_revision)
            self.assertEqual(first.snapshot_id, historical_snapshot.snapshot_id)
            self.assertEqual("monsrcv_001", historical_risk.source_revision)

    def test_engine_identity_migration_supersedes_aggregate_risk_when_episode_risks_replace_it(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            aggregate = risk(
                "aggregate",
                risk_key="riskkey_aggregate",
                engine_version="engine_v1",
            )
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[aggregate],
            )

            episode = risk(
                "episode",
                "monsrcv_001",
                risk_key="riskkey_episode",
                engine_version="engine_v2",
            ).model_copy(
                update={
                    "aggregation_scope": "episode",
                    "episode_key": "EX3|2026-02-05|2026-03-06|3",
                }
            )
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v2",
                evaluated_subject_count=1,
                risks=[episode],
            )

            current = {item.risk_key: item for item in repository.list_risks("proj_test")}
            self.assertEqual("new", current["riskkey_episode"].batch_delta)
            self.assertEqual(RiskStatus.ACTION_REQUIRED, current["riskkey_episode"].status)
            self.assertEqual(
                "superseded_by_engine",
                current["riskkey_aggregate"].batch_delta,
            )
            self.assertEqual(RiskStatus.SUPERSEDED, current["riskkey_aggregate"].status)
            self.assertIn(
                "engine_identity_migration",
                current["riskkey_aggregate"].closure_evidence,
            )

    def test_adjacent_snapshots_classify_new_changed_and_persisting_by_risk_key(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=2,
                risks=[
                    risk("a1", risk_key="riskkey_a"),
                    risk("b1", risk_key="riskkey_b", title="ALT升高待复核"),
                ],
            )
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_002",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=3,
                risks=[
                    risk("a2", "monsrcv_002", risk_key="riskkey_a"),
                    risk("b2", "monsrcv_002", risk_key="riskkey_b", title="ALT升高且需复测"),
                    risk("c2", "monsrcv_002", risk_key="riskkey_c", title="新增访视窗风险"),
                ],
            )

            deltas = {item.risk_key: item.batch_delta for item in repository.list_risks("proj_test")}

            self.assertEqual(
                {"riskkey_a": "persisting", "riskkey_b": "changed", "riskkey_c": "new"},
                deltas,
            )

    def test_complete_snapshot_resolves_missing_risk_and_later_reopens_it(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk("a1", risk_key="riskkey_a")],
            )
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_002",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[],
                resolution_complete=True,
                resolution_eligible_risk_keys={"riskkey_a"},
            )

            resolved = repository.list_risks("proj_test")
            self.assertEqual(1, len(resolved))
            self.assertEqual("resolved_by_data", resolved[0].batch_delta)
            self.assertEqual(RiskStatus.RESOLVED, resolved[0].status)

            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_003",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk("a3", "monsrcv_003", risk_key="riskkey_a")],
                resolution_complete=True,
            )

            reopened = repository.list_risks("proj_test")
            self.assertEqual("reopened", reopened[0].batch_delta)
            self.assertEqual(RiskStatus.ACTION_REQUIRED, reopened[0].status)

    def test_closed_risk_reopens_when_the_same_stable_key_returns(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_closed_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[
                    risk(
                        "closed",
                        source_revision="monsrcv_closed_001",
                        risk_key="riskkey_closed",
                    ).model_copy(
                        update={"status": RiskStatus.CLOSED}
                    )
                ],
            )

            reopened = repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_closed_002",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk("reopened", "monsrcv_closed_002", risk_key="riskkey_closed")],
            )

            current = repository.list_risks("proj_test", reopened.snapshot_id)
            self.assertEqual("reopened", current[0].batch_delta)
            self.assertEqual(RiskStatus.ACTION_REQUIRED, current[0].status)

    def test_incomplete_snapshot_blocks_false_resolution(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk("a1", risk_key="riskkey_a")],
            )
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_002",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[],
                resolution_complete=False,
                resolution_eligible_risk_keys={"riskkey_a"},
            )

            retained = repository.list_risks("proj_test")
            self.assertEqual(1, len(retained))
            self.assertEqual("requires_rereview", retained[0].batch_delta)
            self.assertNotEqual(RiskStatus.RESOLVED, retained[0].status)
            self.assertIn("incomplete", retained[0].closure_evidence)

    def test_rule_or_engine_change_requires_rereview_even_when_risk_meaning_is_unchanged(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk("a1", risk_key="riskkey_a")],
            )
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_002",
                rule_profile_revision="rules_v2",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk("a2", "monsrcv_002", risk_key="riskkey_a", rule_profile_revision="rules_v2")],
            )

            self.assertEqual("requires_rereview", repository.list_risks("proj_test")[0].batch_delta)

    def test_rule_change_blocks_automatic_resolution_even_when_source_is_complete(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk("a1", risk_key="riskkey_a")],
            )
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_002",
                rule_profile_revision="rules_v2",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[],
                resolution_complete=True,
                resolution_eligible_risk_keys={"riskkey_a"},
            )

            retained = repository.list_risks("proj_test")
            self.assertEqual("requires_rereview", retained[0].batch_delta)
            self.assertNotEqual(RiskStatus.RESOLVED, retained[0].status)
            self.assertIn("rule_or_engine_changed", retained[0].closure_evidence)

    def test_complete_snapshot_without_per_risk_eligibility_does_not_auto_resolve(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk("a1", risk_key="riskkey_a")],
            )
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_002",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[],
                resolution_complete=True,
            )

            retained = repository.list_risks("proj_test")
            self.assertEqual("requires_rereview", retained[0].batch_delta)
            self.assertNotEqual(RiskStatus.RESOLVED, retained[0].status)

    def test_replaying_older_snapshot_uses_its_original_predecessor(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            first = risk("a1", risk_key="riskkey_a")
            second = risk("a2", "monsrcv_002", risk_key="riskkey_a")
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[first],
            )
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_002",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[second],
            )
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[first.model_copy(update={"created_at": NOW + timedelta(minutes=2)})],
            )

            self.assertEqual("persisting", repository.list_risks("proj_test")[0].batch_delta)

    def test_duplicate_risk_key_is_rejected_before_persisting(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            with self.assertRaisesRegex(ValueError, "duplicate risk_key"):
                repository.save_snapshot(
                    project_id="proj_test",
                    source_revision="monsrcv_001",
                    rule_profile_revision="rules_v1",
                    engine_version="engine_v1",
                    evaluated_subject_count=1,
                    risks=[risk("a1"), risk("a2")],
                )

    def test_risk_history_orders_instances_by_snapshot_without_mutating_current_state(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            first = repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk("a1", risk_key="riskkey_a")],
            )
            second = repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_002",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk("a2", "monsrcv_002", risk_key="riskkey_a")],
            )

            history = repository.risk_history("proj_test", "riskkey_a")

            self.assertEqual([first.snapshot_id, second.snapshot_id], [item[0].snapshot_id for item in history])
            self.assertEqual(["baseline", "persisting"], [item[1].batch_delta for item in history])
            self.assertEqual(second.snapshot_id, repository.current_snapshot("proj_test").snapshot_id)

    def test_generated_timestamp_does_not_create_false_snapshot_conflict(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            first = repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk()],
            )

            regenerated = risk().model_copy(update={"created_at": NOW + timedelta(seconds=30)})
            replay = repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[regenerated],
            )

            self.assertEqual(first.snapshot_id, replay.snapshot_id)

    def test_snapshot_and_instances_survive_repository_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "risk.sqlite3"
            first = MedicalRiskRepository(db_path)
            snapshot = first.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=241,
                risks=[risk()],
            )

            reopened = MedicalRiskRepository(db_path)
            current = reopened.current_snapshot("proj_test")
            risks = reopened.list_risks("proj_test")

            self.assertEqual(snapshot.snapshot_id, current.snapshot_id)
            self.assertEqual("monsrcv_001", current.source_revision)
            self.assertEqual(241, current.evaluated_subject_count)
            self.assertEqual(["riskinst_001"], [item.risk_instance_id for item in risks])
            self.assertEqual("riskkey_shared", risks[0].risk_key)
            self.assertEqual("baseline", risks[0].batch_delta)

    def test_persisted_snapshot_payload_and_row_tamper_fail_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "risk.sqlite3"
            repository = MedicalRiskRepository(db_path)
            snapshot = repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk()],
            )
            original_payload = repository.list_risks(
                "proj_test", snapshot.snapshot_id
            )[0].model_dump_json()
            tampered_payload = repository.list_risks(
                "proj_test", snapshot.snapshot_id
            )[0].model_copy(update={"title": "语义有效但被篡改"}).model_dump_json()

            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    "UPDATE medical_risk_instances SET payload_json = ? "
                    "WHERE snapshot_id = ?",
                    (
                        tampered_payload,
                        snapshot.snapshot_id,
                    ),
                )
            with self.assertRaisesRegex(ValueError, "payload hash mismatch"):
                repository.current_snapshot("proj_test")

            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    "UPDATE medical_risk_instances SET payload_json = ?, "
                    "risk_key = ? WHERE snapshot_id = ?",
                    (original_payload, "riskkey_tampered", snapshot.snapshot_id),
                )
            with self.assertRaisesRegex(ValueError, "row identity mismatch"):
                repository.risk_instance(
                    "proj_test",
                    "riskinst_001",
                    snapshot.snapshot_id,
                )

    def test_same_snapshot_metadata_rejects_different_risk_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            repository = MedicalRiskRepository(Path(tmp) / "risk.sqlite3")
            repository.save_snapshot(
                project_id="proj_test",
                source_revision="monsrcv_001",
                rule_profile_revision="rules_v1",
                engine_version="engine_v1",
                evaluated_subject_count=1,
                risks=[risk()],
            )

            changed = risk().model_copy(update={"title": "同一版本下出现不同标题"})
            with self.assertRaisesRegex(ValueError, "snapshot payload conflict"):
                repository.save_snapshot(
                    project_id="proj_test",
                    source_revision="monsrcv_001",
                    rule_profile_revision="rules_v1",
                    engine_version="engine_v1",
                    evaluated_subject_count=1,
                    risks=[changed],
                )


if __name__ == "__main__":
    unittest.main()
