from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.workbench_contracts import (
    SafetyReviewAction,
    SafetyReviewActionRequest,
    SafetyReviewRecord,
    SafetyMonitoringCollaborationHandoff,
    SourceAdmissionSource,
    SourceAdmissionState,
)
from services.api.app.safety_pv_manifest import SafetyPvManifestService
from services.api.app.safety_pv_review_workbench import (
    SafetyReviewWorkbenchService,
    SqliteSafetyReviewStore,
)
from services.api.app.sqlite_runtime_store import (
    IdempotencyConflictError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


PROJECT_PACKAGES = {
    "proj_my009_uc": "my009_uc_s1",
    "proj_rux_03_002": "rux_03_002_pv",
}


class SafetyPvSqliteWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest_service = SafetyPvManifestService()
        cls.manifests = {
            project_id: cls.manifest_service.build_manifest(project_id)
            for project_id in PROJECT_PACKAGES
        }

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "runtime.sqlite3"
        self.runtime_store = SqliteRuntimeStore(self.db_path)
        self.review_store = SqliteSafetyReviewStore(self.runtime_store)
        self.service = SafetyReviewWorkbenchService(
            self.manifest_service,
            self.review_store,
            allow_unvalidated_sources=True,
        )

    def signal_id(self, project_id: str) -> str:
        package_id = PROJECT_PACKAGES[project_id]
        package = next(
            item
            for item in self.manifests[project_id].packages
            if item.package_id == package_id
        )
        return package.signal_candidates[0].signal_id

    def request(
        self,
        action: SafetyReviewAction,
        revision: int,
        key: str,
        comment: str = "已基于当前原始资料完成医学复核。",
    ) -> SafetyReviewActionRequest:
        return SafetyReviewActionRequest(
            action=action,
            actor="medical_manager",
            comment=comment,
            expected_revision=revision,
            idempotency_key=key,
        )

    def admission(self, project_id: str, revision: int) -> SourceAdmissionState:
        return SourceAdmissionState(
            project_id=project_id,
            module="safety_pv",
            scope_id=PROJECT_PACKAGES[project_id],
            sources=[
                SourceAdmissionSource(
                    source_role_code="safety_analysis_listing",
                    source_role="安全性分析listing",
                    source_entry_id=f"source_{revision}",
                    validation_id=f"validation_{revision}",
                    revision=revision,
                    validator_version="source_content_consistency_v1",
                    technical_status="ready",
                    content_status="matched",
                    use_status="allowed",
                    public_title=f"当前安全性listing revision {revision}",
                    summary="基本信息与项目内容一致。",
                )
            ],
            ready_for_use=True,
        )

    def apply(
        self,
        project_id: str,
        action: SafetyReviewAction,
        revision: int,
        key: str,
        comment: str = "已基于当前原始资料完成医学复核。",
    ):
        return self.service.apply_action(
            project_id,
            PROJECT_PACKAGES[project_id],
            self.signal_id(project_id),
            self.request(action, revision, key, comment),
        )

    def review_record(
        self,
        project_id: str,
        *,
        revision: int,
        previous_status: str,
        new_status: str,
        action: SafetyReviewAction,
        created_at: datetime,
        record_id: str,
    ) -> SafetyReviewRecord:
        return SafetyReviewRecord(
            record_id=record_id,
            project_id=project_id,
            package_id=PROJECT_PACKAGES[project_id],
            signal_id=self.signal_id(project_id),
            signal_label="安全信号候选",
            action=action,
            actor="medical_manager",
            previous_status=previous_status,
            new_status=new_status,
            comment="用于验证SQLite安全复核状态链。",
            previous_revision=revision - 1,
            revision=revision,
            created_at=created_at,
        )

    def test_two_real_projects_persist_independent_revisioned_review_chains(self) -> None:
        for project_id in PROJECT_PACKAGES:
            with self.subTest(project_id=project_id):
                reviewed = self.apply(
                    project_id,
                    SafetyReviewAction.MARK_MEDICAL_REVIEWED,
                    0,
                    f"{project_id}-reviewed",
                )
                self.assertEqual("医学已复核", reviewed.current_status)
                self.assertEqual(1, reviewed.state_revision)
                self.assertEqual(1, reviewed.review_records[-1].revision)

                promoted = self.apply(
                    project_id,
                    SafetyReviewAction.REQUEST_PV_CONFIRMATION,
                    1,
                    f"{project_id}-pv",
                    "请PV确认安全性报告边界及后续协作事项。",
                )
                self.assertEqual("PV确认候选", promoted.current_status)
                self.assertEqual(2, promoted.state_revision)
                self.assertEqual(1, self.service.handoff_candidates(project_id).total_candidates)

        reopened = SqliteSafetyReviewStore(SqliteRuntimeStore(self.db_path))
        for project_id in PROJECT_PACKAGES:
            records = reopened.records(
                project_id,
                PROJECT_PACKAGES[project_id],
                self.signal_id(project_id),
            )
            self.assertEqual([1, 2], [record.revision for record in records])
            self.assertEqual([], self.runtime_store.verify_audit_chain(project_id))

    def test_monitoring_collaboration_projection_preserves_identity_and_stale_gate(self) -> None:
        project_id = "proj_my009_uc"
        handoff = SafetyMonitoringCollaborationHandoff(
            handoff_id="monitoring-safety-pv:record-1",
            project_id=project_id,
            risk_id="risk-1",
            risk_key="risk-key-1",
            risk_instance_id="risk-instance-1",
            snapshot_id="snapshot-1",
            subject_id="S01003",
            rule_id="MY009-UC-AE-MH-001",
            title="AE/MH漏报待协作复核",
            severity="high",
            source_version="source-v1",
            disposition_record_id="record-1",
            reviewer="medical_manager",
            review_comment="已转Safety/PV协作。",
            created_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
            is_current=False,
            stale_reason="原始数据或规则来源版本已变化",
        )
        self.service.monitoring_collaboration_resolver = lambda _: [handoff]

        manifest = self.service.handoff_candidates(project_id)

        self.assertEqual(0, manifest.monitoring_collaboration_count)
        self.assertEqual(1, manifest.blocked_monitoring_collaboration_count)
        self.assertEqual("risk-key-1", manifest.monitoring_collaborations[0].risk_key)
        gate = next(
            item
            for item in manifest.quality_gates
            if item.gate_id == "monitoring_safety_pv_handoff_current"
        )
        self.assertEqual("blocked", gate.status)

    def test_idempotent_replay_does_not_duplicate_and_changed_payload_conflicts(self) -> None:
        project_id = "proj_my009_uc"
        request = self.request(
            SafetyReviewAction.MARK_MEDICAL_REVIEWED,
            0,
            "same-review-request",
        )
        first = self.service.apply_action(
            project_id,
            PROJECT_PACKAGES[project_id],
            self.signal_id(project_id),
            request,
        )
        replay = self.service.apply_action(
            project_id,
            PROJECT_PACKAGES[project_id],
            self.signal_id(project_id),
            request,
        )
        self.assertEqual(1, first.state_revision)
        self.assertEqual(1, replay.state_revision)
        self.assertEqual(1, len(replay.review_records))

        changed = request.model_copy(update={"comment": "同一幂等键下修改了医学意见。"})
        with self.assertRaises(IdempotencyConflictError):
            self.service.apply_action(
                project_id,
                PROJECT_PACKAGES[project_id],
                self.signal_id(project_id),
                changed,
            )

    def test_faults_roll_back_record_state_audit_and_idempotency(self) -> None:
        project_id = "proj_my009_uc"
        checkpoints = (
            "after_safety_pv_review_record",
            "after_safety_pv_review_state",
            "after_safety_pv_review_audit",
            "after_safety_pv_review_idempotency",
        )
        for checkpoint in checkpoints:
            with self.subTest(checkpoint=checkpoint):
                db_path = Path(self.tmp.name) / f"fault-{checkpoint}.sqlite3"

                def fail(actual: str) -> None:
                    if actual == checkpoint:
                        raise RuntimeError(f"fault:{checkpoint}")

                runtime = SqliteRuntimeStore(db_path, fault_injector=fail)
                service = SafetyReviewWorkbenchService(
                    self.manifest_service,
                    SqliteSafetyReviewStore(runtime),
                    allow_unvalidated_sources=True,
                )
                request = self.request(
                    SafetyReviewAction.MARK_MEDICAL_REVIEWED,
                    0,
                    f"fault-{checkpoint}",
                )
                with self.assertRaisesRegex(RuntimeError, checkpoint):
                    service.apply_action(
                        project_id,
                        PROJECT_PACKAGES[project_id],
                        self.signal_id(project_id),
                        request,
                    )
                self.assertEqual([], runtime.safety_review_records(project_id))
                self.assertEqual([], runtime.runtime_audit_records(project_id))

                runtime.fault_injector = None
                recovered = service.apply_action(
                    project_id,
                    PROJECT_PACKAGES[project_id],
                    self.signal_id(project_id),
                    request,
                )
                self.assertEqual(1, recovered.state_revision)

    def test_runtime_rejects_matching_revision_with_wrong_predecessor_status(self) -> None:
        project_id = "proj_rux_03_002"
        record = self.review_record(
            project_id,
            revision=1,
            previous_status="医学已复核",
            new_status="退回补充资料",
            action=SafetyReviewAction.RETURN_FOR_SOURCE_CHECK,
            created_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
            record_id="wrong-predecessor",
        )
        with self.assertRaisesRegex(StaleRuntimeStateError, "status"):
            self.runtime_store.commit_safety_review(
                record,
                expected_revision=0,
                idempotency_key="wrong-predecessor",
                request_fingerprint="wrong-predecessor",
            )
        self.assertEqual([], self.runtime_store.safety_review_records(project_id))

    def test_revision_order_wins_when_timestamps_are_inverted(self) -> None:
        project_id = "proj_my009_uc"
        first = self.review_record(
            project_id,
            revision=1,
            previous_status="待医学/PV确认",
            new_status="医学已复核",
            action=SafetyReviewAction.MARK_MEDICAL_REVIEWED,
            created_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
            record_id="timestamp-late-revision-1",
        )
        second = self.review_record(
            project_id,
            revision=2,
            previous_status="医学已复核",
            new_status="PV确认候选",
            action=SafetyReviewAction.REQUEST_PV_CONFIRMATION,
            created_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
            record_id="timestamp-early-revision-2",
        )
        for record in (first, second):
            self.runtime_store.commit_safety_review(
                record,
                expected_revision=record.previous_revision,
                idempotency_key=record.record_id,
                request_fingerprint=record.record_id,
            )
        records = self.review_store.records(
            project_id,
            PROJECT_PACKAGES[project_id],
            self.signal_id(project_id),
        )
        self.assertEqual([1, 2], [record.revision for record in records])
        self.assertEqual(
            "PV确认候选",
            self.service.workbench(
                project_id,
                PROJECT_PACKAGES[project_id],
                self.signal_id(project_id),
            ).current_status,
        )

    def test_legacy_jsonl_import_is_ordered_idempotent_and_refuses_live_mix(self) -> None:
        project_id = "proj_rux_03_002"
        legacy_path = Path(self.tmp.name) / "legacy-safety.jsonl"
        legacy_records = [
            self.review_record(
                project_id,
                revision=1,
                previous_status="待医学/PV确认",
                new_status="医学已复核",
                action=SafetyReviewAction.MARK_MEDICAL_REVIEWED,
                created_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
                record_id="legacy-1",
            ),
            self.review_record(
                project_id,
                revision=1,
                previous_status="医学已复核",
                new_status="PV确认候选",
                action=SafetyReviewAction.REQUEST_PV_CONFIRMATION,
                created_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
                record_id="legacy-2",
            ),
        ]
        legacy_path.write_text(
            "\n".join(
                json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
                for item in legacy_records
            )
            + "\n",
            encoding="utf-8",
        )
        legacy_db = Path(self.tmp.name) / "legacy-import.sqlite3"
        imported = SqliteSafetyReviewStore(
            SqliteRuntimeStore(legacy_db),
            legacy_path=legacy_path,
        )
        self.assertEqual([1, 2], [item.revision for item in imported.records(project_id)])
        reopened = SqliteSafetyReviewStore(
            SqliteRuntimeStore(legacy_db),
            legacy_path=legacy_path,
        )
        self.assertEqual(2, len(reopened.records(project_id)))

        live_db = Path(self.tmp.name) / "legacy-live-mix.sqlite3"
        live_runtime = SqliteRuntimeStore(live_db)
        live_store = SqliteSafetyReviewStore(live_runtime)
        live = self.review_record(
            project_id,
            revision=1,
            previous_status="待医学/PV确认",
            new_status="医学已复核",
            action=SafetyReviewAction.MARK_MEDICAL_REVIEWED,
            created_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
            record_id="live-1",
        )
        live_runtime.commit_safety_review(
            live,
            expected_revision=0,
            idempotency_key="live-1",
            request_fingerprint="live-1",
        )
        SqliteSafetyReviewStore(live_runtime, legacy_path=legacy_path)
        self.assertEqual(["live-1"], [item.record_id for item in live_store.records(project_id)])
        self.assertTrue(
            any(
                item["event_type"] == "legacy_import_rejected"
                for item in live_runtime.runtime_audit_records(project_id)
            )
        )

    def test_stale_revision_is_rejected_without_overwriting_current_state(self) -> None:
        project_id = "proj_rux_03_002"
        self.apply(
            project_id,
            SafetyReviewAction.MARK_MEDICAL_REVIEWED,
            0,
            "rux-current-review",
        )
        with self.assertRaises(StaleRuntimeStateError):
            self.apply(
                project_id,
                SafetyReviewAction.RETURN_FOR_SOURCE_CHECK,
                0,
                "rux-stale-return",
                "需要补充当前版本的安全性原始资料。",
            )
        current = self.service.workbench(
            project_id,
            PROJECT_PACKAGES[project_id],
            self.signal_id(project_id),
        )
        self.assertEqual("医学已复核", current.current_status)
        self.assertEqual(1, current.state_revision)
        self.assertEqual(1, len(current.review_records))
        rejection_events = [
            item
            for item in self.runtime_store.runtime_audit_records(project_id)
            if item["event_type"] == "stale_write_rejected"
            and item["operation"] == "safety_pv_review"
        ]
        self.assertEqual(1, len(rejection_events))

    def test_explicit_state_machine_covers_all_actions_without_shortcuts(self) -> None:
        project_id = "proj_my009_uc"
        with self.assertRaisesRegex(ValueError, "完成医学复核"):
            self.apply(
                project_id,
                SafetyReviewAction.REQUEST_PV_CONFIRMATION,
                0,
                "pv-too-early",
            )

        returned = self.apply(
            project_id,
            SafetyReviewAction.RETURN_FOR_SOURCE_CHECK,
            0,
            "return-source",
            "缺少当前批次可核对的AE原始记录，请补充资料。",
        )
        self.assertEqual("退回补充资料", returned.current_status)
        reviewed = self.apply(
            project_id,
            SafetyReviewAction.MARK_MEDICAL_REVIEWED,
            1,
            "review-after-source",
        )
        self.assertEqual("医学已复核", reviewed.current_status)
        closed = self.apply(
            project_id,
            SafetyReviewAction.ACCEPT_NO_ACTION,
            2,
            "close-no-action",
            "复核现有资料后未发现需要继续协作的医学事项。",
        )
        self.assertEqual("关闭为暂无需处理", closed.current_status)

        with self.assertRaisesRegex(ValueError, "重置"):
            self.apply(
                project_id,
                SafetyReviewAction.MARK_MEDICAL_REVIEWED,
                3,
                "invalid-reopen",
            )
        reset = self.apply(
            project_id,
            SafetyReviewAction.RESET_REVIEW,
            3,
            "explicit-reset",
            "发现新的资料批次，需要重新开启医学复核。",
        )
        self.assertEqual("待医学/PV确认", reset.current_status)
        self.assertEqual(4, reset.state_revision)

    def test_reset_requires_a_substantive_reason(self) -> None:
        project_id = "proj_rux_03_002"
        with self.assertRaisesRegex(ValueError, "处置意见"):
            self.apply(
                project_id,
                SafetyReviewAction.RESET_REVIEW,
                0,
                "empty-reset",
                "",
            )

    def test_source_revision_change_invalidates_review_and_handoff_until_rereviewed(self) -> None:
        project_id = "proj_rux_03_002"
        current = {"state": self.admission(project_id, 1)}
        service = SafetyReviewWorkbenchService(
            self.manifest_service,
            self.review_store,
            lambda requested_project, package_id: current["state"],
        )
        signal_id = self.signal_id(project_id)
        package_id = PROJECT_PACKAGES[project_id]
        service.apply_action(
            project_id,
            package_id,
            signal_id,
            self.request(
                SafetyReviewAction.MARK_MEDICAL_REVIEWED,
                0,
                "source-v1-review",
            ),
        )

        current["state"] = self.admission(project_id, 2)
        stale = service.workbench(project_id, package_id, signal_id)
        self.assertEqual("来源已变化，需重新医学复核", stale.current_status)
        self.assertEqual(1, stale.state_revision)
        with self.assertRaisesRegex(ValueError, "重新完成医学复核"):
            service.apply_action(
                project_id,
                package_id,
                signal_id,
                self.request(
                    SafetyReviewAction.REQUEST_PV_CONFIRMATION,
                    1,
                    "stale-pv-request",
                    "尝试沿用旧来源版本申请PV确认。",
                ),
            )

        reviewed = service.apply_action(
            project_id,
            package_id,
            signal_id,
            self.request(
                SafetyReviewAction.MARK_MEDICAL_REVIEWED,
                1,
                "source-v2-review",
                "已基于revision 2重新完成医学复核。",
            ),
        )
        self.assertEqual(2, reviewed.state_revision)
        promoted = service.apply_action(
            project_id,
            package_id,
            signal_id,
            self.request(
                SafetyReviewAction.REQUEST_PV_CONFIRMATION,
                2,
                "source-v2-pv-request",
                "请PV基于revision 2确认协作事项。",
            ),
        )
        self.assertEqual("PV确认候选", promoted.current_status)
        self.assertEqual(1, service.handoff_candidates(project_id).total_candidates)

        current["state"] = self.admission(project_id, 3)
        blocked = service.handoff_candidates(project_id)
        self.assertEqual(0, blocked.total_candidates)
        self.assertEqual(1, blocked.blocked_stale_candidate_count)


if __name__ == "__main__":
    unittest.main()
