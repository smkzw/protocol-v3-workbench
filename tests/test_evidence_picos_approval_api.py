from __future__ import annotations

import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import (  # noqa: E402
    ApprovalAction,
    ApprovalActionRequest,
    ApprovalGate,
    ApprovalState,
    AuditEvent,
    EvidenceDesignManifestResult,
    EvidenceDesignPackageSummary,
    EvidencePicosOptionTemplate,
    EvidencePicosQuestion,
    EvidencePicosQuestionState,
    EvidencePicosSnapshot,
)
from services.api.app import main as app_main  # noqa: E402
from services.api.app.demo_repository import DemoRepository  # noqa: E402
from services.api.app.evidence_picos_workflow import (  # noqa: E402
    EvidencePicosApprovalService,
    EvidencePicosWorkflowService,
    SqliteEvidencePicosDecisionStore,
)
from services.api.app.sqlite_runtime_store import RuntimeStoreError, SqliteRuntimeStore  # noqa: E402
from services.api.app.workbench_inbox import WorkbenchInboxService, WorkbenchInboxStore  # noqa: E402


PROJECT_ID = "proj_test_evidence_picos"
PACKAGE_ID = "test_evidence_package"
QUESTION_ID = "picos:population"


class StubEvidenceManifestService:
    def __init__(self):
        self.source_hash = "sha256:test-evidence-v1"

    def build_manifest(self, project_id: str) -> EvidenceDesignManifestResult:
        return EvidenceDesignManifestResult(
            project_id=project_id,
            generated_at=datetime.now(timezone.utc),
            package_count=1,
            picos_question_count=1,
            packages=[
                EvidenceDesignPackageSummary(
                    package_id=PACKAGE_ID,
                    package_label="测试证据资料包",
                    indication="测试适应症",
                    source_root_label="受控测试资料",
                    package_role="workflow_test",
                    picos_questions=[
                        EvidencePicosQuestion(
                            question_id=QUESTION_ID,
                            picos_domain="人群",
                            question="目标人群如何定义？",
                            evidence_status="ready",
                            current_evidence_summary="受控测试证据摘要。",
                            required_user_decision="选择人群候选并填写医学理由。",
                            source_refs=["TestEvidence:population"],
                            option_templates=[
                                EvidencePicosOptionTemplate(
                                    label="目标人群候选",
                                    design_summary="采用受控测试目标人群。",
                                    medical_rationale_prompt="请填写医学理由。",
                                    writing_target_section="入排标准/研究人群",
                                )
                            ],
                        )
                    ],
                )
            ],
        )

    def package_hash(self, project_id: str, package_id: str) -> str:
        if project_id != PROJECT_ID or package_id != PACKAGE_ID:
            raise KeyError(f"{project_id}/{package_id}")
        return self.source_hash


class EvidencePicosApprovalApiTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.data_path = self.root / "demo.json"
        self._write_demo_data()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_demo_data(self, approval_gates=None) -> None:
        now = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc).isoformat()
        self.data_path.write_text(
            json.dumps(
                {
                    "projects": [
                        {
                            "project_id": PROJECT_ID,
                            "project_code": "TEST-PICOS",
                            "project_name": "Evidence PICOS Approval Test",
                            "indication": "测试适应症",
                            "product_name": "测试产品",
                            "study_phase": "II",
                            "protocol_id": "TEST-PICOS-PROT",
                            "protocol_version": "V1.0",
                            "protocol_date": "2026-07-10",
                            "created_at": now,
                            "updated_at": now,
                        }
                    ],
                    "data_batches": [],
                    "risk_cases": [],
                    "approval_gates": list(approval_gates or []),
                    "approval_decisions": [],
                    "audit_events": [],
                    "subject_monitoring_profiles": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _fixture(self, name: str):
        manifest = StubEvidenceManifestService()
        store = SqliteRuntimeStore(self.root / f"{name}.sqlite3")
        workflow = EvidencePicosWorkflowService(
            manifest,
            SqliteEvidencePicosDecisionStore(store),
        )
        approval_service = EvidencePicosApprovalService(workflow, store)
        repo = DemoRepository(self.data_path, approval_store=store)
        return manifest, store, workflow, approval_service, repo

    def _ready_workflow(self, name: str):
        manifest, store, workflow, approval_service, repo = self._fixture(name)
        initial = workflow.workflow(PROJECT_ID, PACKAGE_ID)
        ready = workflow.apply_action(
            PROJECT_ID,
            PACKAGE_ID,
            QUESTION_ID,
            {
                "action": "select_option",
                "option_id": f"{QUESTION_ID}:option:1",
                "user_rationale": "测试医学理由。",
                "expected_revision": initial.revision,
                "expected_evidence_package_hash": initial.evidence_package_hash,
                "idempotency_key": f"{name}-select",
            },
        )
        return manifest, store, workflow, approval_service, repo, ready

    def _commit_legacy_snapshot(self, store, ready, state: ApprovalState):
        snapshot_seed = (
            f"{PROJECT_ID}|{PACKAGE_ID}|{ready.working_state_id}|"
            f"{ready.revision}|{ready.evidence_package_hash}"
        )
        snapshot_token = sha1(snapshot_seed.encode("utf-8")).hexdigest()[:16]
        snapshot_id = f"picos_snapshot_{snapshot_token}"
        approval_id = f"approval_picos_{snapshot_token}_r{ready.revision}"
        created_at = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
        snapshot = EvidencePicosSnapshot(
            snapshot_id=snapshot_id,
            project_id=PROJECT_ID,
            package_id=PACKAGE_ID,
            working_state_id=ready.working_state_id,
            revision=ready.revision,
            evidence_package_hash=ready.evidence_package_hash,
            approval_id=approval_id,
            question_states=[
                EvidencePicosQuestionState(
                    question_id=step.question_id,
                    selected_option_id=step.selected_option_id,
                    user_rationale=step.user_rationale,
                    decision_status=step.decision_status,
                    writing_target_section=step.writing_target_section,
                )
                for step in ready.steps
            ],
            created_at=created_at,
        )
        gate = ApprovalGate(
            approval_id=approval_id,
            project_id=PROJECT_ID,
            target_type="evidence_picos_snapshot",
            target_id=snapshot_id,
            target_revision=ready.revision,
            display_title="PICOS 医学审批快照",
            display_detail="历史流程提交医学审批。",
            state=state,
            requested_by="medical_manager",
            review_comments="历史提交备注",
            created_at=created_at,
            updated_at=created_at,
        )
        audit = AuditEvent(
            audit_id=f"audit_legacy_picos_submission_{snapshot_token}",
            project_id=PROJECT_ID,
            actor="medical_manager",
            action="submit_picos_for_medical_approval",
            target_type="evidence_picos_snapshot",
            target_id=snapshot_id,
            detail={"approval_id": approval_id, "revision": ready.revision},
            created_at=created_at,
        )
        store.commit_evidence_picos_snapshot(
            snapshot,
            gate,
            audit,
            expected_revision=ready.revision,
            idempotency_key=f"legacy-picos-snapshot:{state.value}",
            request_fingerprint=f"legacy-picos-snapshot:{state.value}:v1",
        )
        return snapshot, gate, audit

    def _ready_submission(self, name: str):
        manifest, store, workflow, approval_service, repo, ready = self._ready_workflow(name)
        submission = approval_service.submit_for_approval(
            PROJECT_ID,
            PACKAGE_ID,
            {
                "expected_revision": ready.revision,
                "expected_evidence_package_hash": ready.evidence_package_hash,
                "idempotency_key": f"{name}-submit",
            },
        )
        return manifest, store, workflow, approval_service, repo, submission

    def test_legacy_pending_snapshot_is_upgraded_by_author_reconfirmation(self):
        manifest, store, workflow, service, repo, ready = self._ready_workflow(
            "legacy-author-confirm"
        )
        snapshot_seed = (
            f"{PROJECT_ID}|{PACKAGE_ID}|{ready.working_state_id}|"
            f"{ready.revision}|{ready.evidence_package_hash}"
        )
        snapshot_token = sha1(snapshot_seed.encode("utf-8")).hexdigest()[:16]
        snapshot_id = f"picos_snapshot_{snapshot_token}"
        legacy_approval_id = f"approval_picos_{snapshot_token}_r{ready.revision}"
        legacy_created_at = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
        legacy_snapshot = EvidencePicosSnapshot(
            snapshot_id=snapshot_id,
            project_id=PROJECT_ID,
            package_id=PACKAGE_ID,
            working_state_id=ready.working_state_id,
            revision=ready.revision,
            evidence_package_hash=ready.evidence_package_hash,
            approval_id=legacy_approval_id,
            question_states=[
                EvidencePicosQuestionState(
                    question_id=step.question_id,
                    selected_option_id=step.selected_option_id,
                    user_rationale=step.user_rationale,
                    decision_status=step.decision_status,
                    writing_target_section=step.writing_target_section,
                )
                for step in ready.steps
            ],
            created_at=legacy_created_at,
        )
        legacy_gate = ApprovalGate(
            approval_id=legacy_approval_id,
            project_id=PROJECT_ID,
            target_type="evidence_picos_snapshot",
            target_id=snapshot_id,
            target_revision=ready.revision,
            display_title="PICOS 医学审批快照",
            display_detail="历史流程提交医学审批。",
            state=ApprovalState.IN_MEDICAL_REVIEW,
            requested_by="medical_manager",
            review_comments="历史提交备注",
            created_at=legacy_created_at,
            updated_at=legacy_created_at,
        )
        legacy_audit = AuditEvent(
            audit_id=f"audit_legacy_picos_submission_{snapshot_token}",
            project_id=PROJECT_ID,
            actor="medical_manager",
            action="submit_picos_for_medical_approval",
            target_type="evidence_picos_snapshot",
            target_id=snapshot_id,
            detail={
                "approval_id": legacy_approval_id,
                "revision": ready.revision,
            },
            created_at=legacy_created_at,
        )
        store.commit_evidence_picos_snapshot(
            legacy_snapshot,
            legacy_gate,
            legacy_audit,
            expected_revision=ready.revision,
            idempotency_key="legacy-picos-snapshot",
            request_fingerprint="legacy-picos-snapshot-v1",
        )

        legacy_workflow = workflow.workflow(PROJECT_ID, PACKAGE_ID)
        self.assertEqual(
            "legacy_pending_medical_approval",
            legacy_workflow.confirmation_status,
        )
        self.assertEqual(
            ApprovalState.IN_MEDICAL_REVIEW,
            legacy_workflow.approval_state,
        )
        legacy_dashboard = repo.dashboard(PROJECT_ID)
        self.assertEqual(1, len(legacy_dashboard.pending_approvals))

        def fail_after_gate(point: str) -> None:
            if point == "after_gate":
                raise RuntimeError("injected legacy confirmation failure")

        store.fault_injector = fail_after_gate
        with self.assertRaisesRegex(
            RuntimeError,
            "injected legacy confirmation failure",
        ):
            service.submit_for_approval(
                PROJECT_ID,
                PACKAGE_ID,
                {
                    "expected_revision": ready.revision,
                    "expected_evidence_package_hash": ready.evidence_package_hash,
                    "idempotency_key": "legacy-author-confirm-rollback",
                },
            )
        store.fault_injector = None
        self.assertEqual(
            ApprovalState.IN_MEDICAL_REVIEW,
            next(
                gate
                for gate in store.gates(PROJECT_ID)
                if gate.approval_id == legacy_approval_id
            ).state,
        )
        self.assertEqual([], store.audit_events(PROJECT_ID))
        self.assertEqual([], store.decisions(PROJECT_ID))
        self.assertEqual(
            "legacy_pending_medical_approval",
            workflow.workflow(PROJECT_ID, PACKAGE_ID).confirmation_status,
        )

        confirmation = service.submit_for_approval(
            PROJECT_ID,
            PACKAGE_ID,
            {
                "actor": "medical_manager",
                "comment": "将历史状态迁移为当前版本技术快照。",
                "expected_revision": ready.revision,
                "expected_evidence_package_hash": ready.evidence_package_hash,
                "idempotency_key": "legacy-author-confirm-submit",
            },
        )

        self.assertEqual(snapshot_id, confirmation.snapshot.snapshot_id)
        self.assertEqual(
            "medical_review_submission",
            confirmation.snapshot.snapshot_type,
        )
        self.assertEqual("legacy_medical_approval", confirmation.snapshot.confirmation_type)
        self.assertEqual(legacy_approval_id, confirmation.approval.approval_id)
        self.assertEqual(
            ApprovalState.MEDICALLY_APPROVED,
            confirmation.approval.state,
        )
        self.assertEqual("author_confirmed", confirmation.workflow.confirmation_status)
        self.assertEqual(snapshot_id, confirmation.workflow.confirmed_snapshot_id)

        approval_audits = store.audit_events(PROJECT_ID)
        approval_decisions = store.decisions(PROJECT_ID)
        self.assertEqual(1, len(approval_audits))
        self.assertEqual(1, len(approval_decisions))
        self.assertEqual("migrate_legacy_picos_author_selection", approval_audits[0].action)
        self.assertEqual(
            ApprovalState.IN_MEDICAL_REVIEW,
            ApprovalState(
                approval_audits[0].detail["legacy_gate"]["state"]
            ),
        )
        self.assertFalse(
            approval_audits[0].detail["second_medical_approval_required"]
        )
        self.assertEqual(
            ApprovalState.IN_MEDICAL_REVIEW,
            approval_decisions[0].previous_state,
        )
        self.assertEqual(
            ApprovalState.MEDICALLY_APPROVED,
            approval_decisions[0].new_state,
        )
        self.assertEqual(
            [legacy_audit.audit_id],
            [
                event.audit_id
                for event in store.workflow_audit_events(
                    PROJECT_ID,
                    "evidence_picos_snapshot",
                )
            ],
        )
        self.assertEqual([], store.verify_audit_chain(PROJECT_ID))

        dashboard = repo.dashboard(PROJECT_ID)
        self.assertEqual([], dashboard.pending_approvals)
        counts = {item.module: item.pending_approval_count for item in dashboard.modules}
        self.assertTrue(all(count == 0 for count in counts.values()))
        inbox_service = WorkbenchInboxService(
            repo,
            ai_task_runner=None,
            evidence_picos_workflow_service=None,
            tfl_writing_handoff_service=None,
            safety_review_workbench_service=None,
            medical_writing_manifest_service=None,
            source_registry_service=None,
            eligibility_adapter=None,
            store=WorkbenchInboxStore(self.root / "legacy-inbox.jsonl"),
        )
        self.assertEqual([], inbox_service._approval_items(PROJECT_ID))

        handoff = service.create_handoff(
            PROJECT_ID,
            PACKAGE_ID,
            {
                "snapshot_id": snapshot_id,
                "idempotency_key": "legacy-author-confirm-handoff",
            },
        )
        self.assertEqual(legacy_approval_id, handoff.confirmation_id)
        self.assertEqual(ready.revision, handoff.confirmed_revision)

        replay = service.submit_for_approval(
            PROJECT_ID,
            PACKAGE_ID,
            {
                "expected_revision": ready.revision,
                "expected_evidence_package_hash": ready.evidence_package_hash,
                "idempotency_key": "legacy-author-confirm-submit-replay",
            },
        )
        self.assertEqual(legacy_approval_id, replay.approval.approval_id)
        self.assertEqual(1, len(store.audit_events(PROJECT_ID)))
        self.assertEqual(1, len(store.decisions(PROJECT_ID)))

        restarted_store = SqliteRuntimeStore(store.db_path)
        restarted_workflow = EvidencePicosWorkflowService(
            manifest,
            SqliteEvidencePicosDecisionStore(restarted_store),
        )
        restarted_service = EvidencePicosApprovalService(
            restarted_workflow,
            restarted_store,
        )
        restarted = restarted_service.submit_for_approval(
            PROJECT_ID,
            PACKAGE_ID,
            {
                "expected_revision": ready.revision,
                "expected_evidence_package_hash": ready.evidence_package_hash,
                "idempotency_key": "legacy-author-confirm-after-restart",
            },
        )
        self.assertEqual(legacy_approval_id, restarted.approval.approval_id)
        self.assertEqual("author_confirmed", restarted.workflow.confirmation_status)
        self.assertEqual(1, len(restarted_store.audit_events(PROJECT_ID)))
        self.assertEqual(1, len(restarted_store.decisions(PROJECT_ID)))
        self.assertEqual([], restarted_store.verify_audit_chain(PROJECT_ID))

    def test_legacy_returned_snapshot_migrates_without_false_success_or_pending_task(self):
        manifest, store, workflow, service, repo, ready = self._ready_workflow(
            "legacy-returned"
        )
        snapshot, legacy_gate, _ = self._commit_legacy_snapshot(
            store,
            ready,
            ApprovalState.RETURNED_FOR_REVISION,
        )
        before = workflow.workflow(PROJECT_ID, PACKAGE_ID)
        self.assertEqual(ApprovalState.RETURNED_FOR_REVISION, before.approval_state)
        self.assertEqual(1, len(repo.dashboard(PROJECT_ID).pending_approvals))

        with (
            patch.object(app_main, "evidence_picos_approval_service", service),
            patch.object(
                app_main,
                "_canonical_module_project_id",
                return_value=PROJECT_ID,
            ),
        ):
            response = TestClient(app_main.app).post(
                f"/api/projects/{PROJECT_ID}/evidence-design/picos-workflow/"
                f"{PACKAGE_ID}/approval-submissions",
                json={
                    "actor": "medical_manager",
                    "expected_revision": ready.revision,
                    "expected_evidence_package_hash": ready.evidence_package_hash,
                    "idempotency_key": "legacy-returned-migrate",
                },
            )
        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertEqual(snapshot.snapshot_id, result["snapshot"]["snapshot_id"])
        self.assertEqual(legacy_gate.approval_id, result["approval"]["approval_id"])
        self.assertEqual(
            ApprovalState.MEDICALLY_APPROVED.value,
            result["approval"]["state"],
        )
        self.assertEqual("author_confirmed", result["workflow"]["confirmation_status"])
        self.assertEqual([], repo.dashboard(PROJECT_ID).pending_approvals)
        self.assertEqual(
            ApprovalState.RETURNED_FOR_REVISION,
            store.decisions(PROJECT_ID)[0].previous_state,
        )

    def test_handoff_is_business_idempotent_across_keys_concurrency_restart_and_revision(self):
        manifest, store, workflow, service, _, submission = self._ready_submission(
            "handoff-business-idempotency"
        )
        snapshot_id = submission.snapshot.snapshot_id

        def create(index: int):
            return service.create_handoff(
                PROJECT_ID,
                PACKAGE_ID,
                {
                    "snapshot_id": snapshot_id,
                    "idempotency_key": f"handoff-concurrent-{index}",
                },
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(create, range(4)))
        self.assertEqual(1, len({item.handoff_id for item in results}))
        self.assertEqual(1, len({item.created_at for item in results}))
        self.assertEqual(1, len(store.evidence_picos_handoffs(PROJECT_ID, PACKAGE_ID)))
        projected = workflow.workflow(PROJECT_ID, PACKAGE_ID)
        self.assertEqual(results[0].handoff_id, projected.current_handoff_id)
        self.assertEqual(snapshot_id, projected.current_handoff_snapshot_id)
        self.assertEqual(projected.approved_revision, projected.current_handoff_revision)

        restarted_store = SqliteRuntimeStore(store.db_path)
        restarted_workflow = EvidencePicosWorkflowService(
            manifest,
            SqliteEvidencePicosDecisionStore(restarted_store),
        )
        restarted_service = EvidencePicosApprovalService(
            restarted_workflow,
            restarted_store,
        )
        replay = restarted_service.create_handoff(
            PROJECT_ID,
            PACKAGE_ID,
            {
                "snapshot_id": snapshot_id,
                "idempotency_key": "handoff-after-restart",
            },
        )
        self.assertEqual(results[0], replay)
        self.assertEqual(
            1,
            len(restarted_store.evidence_picos_handoffs(PROJECT_ID, PACKAGE_ID)),
        )

        current = restarted_workflow.workflow(PROJECT_ID, PACKAGE_ID)
        revised = restarted_workflow.apply_action(
            PROJECT_ID,
            PACKAGE_ID,
            QUESTION_ID,
            {
                "action": "save_rationale",
                "user_rationale": "修订后的测试医学理由。",
                "expected_revision": current.revision,
                "expected_evidence_package_hash": current.evidence_package_hash,
                "idempotency_key": "revise-current-domain",
            },
        )
        self.assertEqual("作者已确认", revised.steps[0].decision_status)
        self.assertEqual("", revised.current_handoff_id)
        new_submission = restarted_service.submit_for_approval(
            PROJECT_ID,
            PACKAGE_ID,
            {
                "expected_revision": revised.revision,
                "expected_evidence_package_hash": revised.evidence_package_hash,
                "idempotency_key": "new-revision-snapshot",
            },
        )
        new_handoff = restarted_service.create_handoff(
            PROJECT_ID,
            PACKAGE_ID,
            {
                "snapshot_id": new_submission.snapshot.snapshot_id,
                "idempotency_key": "new-revision-handoff",
            },
        )
        self.assertNotEqual(results[0].handoff_id, new_handoff.handoff_id)
        self.assertEqual(
            2,
            len(restarted_store.evidence_picos_handoffs(PROJECT_ID, PACKAGE_ID)),
        )

    def test_author_confirmation_is_direct_idempotent_and_restart_consistent(self):
        manifest, store, workflow, service, repo, submission = self._ready_submission(
            "author-confirm"
        )
        approval_id = submission.approval.approval_id
        snapshot_id = submission.snapshot.snapshot_id

        self.assertEqual(ApprovalState.MEDICALLY_APPROVED, submission.approval.state)
        self.assertEqual("author_confirmation", submission.snapshot.snapshot_type)
        self.assertEqual("medical_author_confirmation", submission.snapshot.confirmation_type)
        self.assertEqual("author_confirmed", submission.workflow.confirmation_status)
        replay = service.submit_for_approval(
            PROJECT_ID,
            PACKAGE_ID,
            {
                "expected_revision": submission.workflow.revision,
                "expected_evidence_package_hash": submission.workflow.evidence_package_hash,
                "idempotency_key": "author-confirm-submit",
            },
        )
        self.assertEqual(snapshot_id, replay.snapshot.snapshot_id)
        self.assertEqual(1, len(store.gates(PROJECT_ID)))

        dashboard = repo.dashboard(PROJECT_ID)
        counts = {item.module: item.pending_approval_count for item in dashboard.modules}
        self.assertTrue(all(count == 0 for count in counts.values()))

        inbox_service = WorkbenchInboxService(
            repo,
            ai_task_runner=None,
            evidence_picos_workflow_service=None,
            tfl_writing_handoff_service=None,
            safety_review_workbench_service=None,
            medical_writing_manifest_service=None,
            source_registry_service=None,
            eligibility_adapter=None,
            store=WorkbenchInboxStore(self.root / "inbox.jsonl"),
        )
        self.assertEqual([], inbox_service._approval_items(PROJECT_ID))

        restarted_store = SqliteRuntimeStore(store.db_path)
        restarted_repo = DemoRepository(self.data_path, approval_store=restarted_store)
        restarted_workflow = EvidencePicosWorkflowService(
            manifest,
            SqliteEvidencePicosDecisionStore(restarted_store),
        )
        restarted_approval_service = EvidencePicosApprovalService(restarted_workflow, restarted_store)
        self.assertEqual(
            ApprovalState.MEDICALLY_APPROVED,
            restarted_repo.approval(PROJECT_ID, approval_id).state,
        )
        approved_workflow = restarted_workflow.workflow(PROJECT_ID, PACKAGE_ID)
        self.assertEqual(ApprovalState.MEDICALLY_APPROVED, approved_workflow.approval_state)
        self.assertEqual("author_confirmed", approved_workflow.confirmation_status)
        self.assertEqual(submission.snapshot.revision, approved_workflow.approved_revision)
        self.assertEqual(snapshot_id, approved_workflow.approved_snapshot_id)

        handoff = restarted_approval_service.create_handoff(
            PROJECT_ID,
            PACKAGE_ID,
            {
                "snapshot_id": snapshot_id,
                "idempotency_key": "handoff-approved",
            },
        )
        self.assertEqual(approval_id, handoff.approval_id)
        self.assertEqual(approval_id, handoff.confirmation_id)
        self.assertEqual(submission.snapshot.revision, handoff.confirmed_revision)

        manifest.source_hash = "sha256:test-evidence-v2"
        current = restarted_workflow.workflow(PROJECT_ID, PACKAGE_ID)
        self.assertEqual(ApprovalState.AI_DRAFT, current.approval_state)
        self.assertEqual("invalidated", current.confirmation_status)
        restarted_workflow.apply_action(
            PROJECT_ID,
            PACKAGE_ID,
            QUESTION_ID,
            {
                "action": "reset_decision",
                "expected_revision": current.revision,
                "expected_evidence_package_hash": current.evidence_package_hash,
                "idempotency_key": "source-v2-reset",
            },
        )
        with self.assertRaises(RuntimeStoreError):
            restarted_approval_service.create_handoff(
                PROJECT_ID,
                PACKAGE_ID,
                {
                    "snapshot_id": snapshot_id,
                    "idempotency_key": "handoff-stale-revision-source",
                },
            )

    def test_demo_seed_evidence_gate_is_not_misrouted_to_runtime_store(self):
        now = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc).isoformat()
        seed_gate = {
            "approval_id": "approval_demo_seed_picos",
            "project_id": PROJECT_ID,
            "target_type": "evidence_picos_snapshot",
            "target_id": "demo_seed_snapshot",
            "target_revision": 1,
            "state": "in_medical_review",
            "requested_by": "demo_seed",
            "created_at": now,
            "updated_at": now,
        }
        self._write_demo_data([seed_gate])
        store = SqliteRuntimeStore(self.root / "demo-seed.sqlite3")
        repo = DemoRepository(self.data_path, approval_store=store)

        result = repo.record_approval_action(
            PROJECT_ID,
            seed_gate["approval_id"],
            ApprovalActionRequest(
                action=ApprovalAction.APPROVE,
                actor="medical_director",
                idempotency_key="do-not-route-demo-seed",
            ),
        )

        self.assertEqual(ApprovalState.MEDICALLY_APPROVED, result.approval.state)
        self.assertEqual([], store.gates(PROJECT_ID))
        self.assertEqual([], store.decisions(PROJECT_ID))
        self.assertEqual([], store.audit_events(PROJECT_ID))


if __name__ == "__main__":
    unittest.main()
