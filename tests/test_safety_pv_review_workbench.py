from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import services.api.app.main as main_module  # noqa: E402
from packages.contracts.workbench_contracts import (  # noqa: E402
    SafetyReviewAction,
    SafetyReviewActionRequest,
    SafetyReviewRecord,
    SourceAdmissionSource,
    SourceAdmissionState,
)
from services.api.app.source_admission import SourceAdmissionRequired  # noqa: E402
from services.api.app.safety_pv_manifest import MY009_LISTING, SafetyPvManifestService  # noqa: E402
from services.api.app.safety_pv_review_workbench import SafetyReviewStore, SafetyReviewWorkbenchService  # noqa: E402


PROJECT_ID = "proj_my009_uc"


class CachedSafetyManifestService:
    def __init__(self, manifest):
        self.manifest = manifest

    def build_manifest(self, project_id: str):
        if project_id != PROJECT_ID:
            raise KeyError(project_id)
        return self.manifest


@unittest.skipUnless(MY009_LISTING.exists(), "MY009 safety listing path is unavailable")
class SafetyPvReviewWorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = SafetyPvManifestService().build_manifest(PROJECT_ID)

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.store = SafetyReviewStore(Path(self.tmpdir.name) / "safety_review_actions.jsonl")
        self.service = SafetyReviewWorkbenchService(
            CachedSafetyManifestService(self.manifest),
            self.store,
            allow_unvalidated_sources=True,
        )

    def package(self, package_id: str):
        return next(package for package in self.manifest.packages if package.package_id == package_id)

    def ae_signal(self):
        package = self.package("my009_uc_s1")
        return next(signal for signal in package.signal_candidates if signal.signal_type == "ae_medical_review_candidate")

    def test_empty_review_store_has_no_handoff_candidate_records(self):
        self.assertFalse(self.service.has_handoff_candidate_records(PROJECT_ID))

    def admission(self, *, revision: int, ready: bool):
        return SourceAdmissionState(
            project_id=PROJECT_ID,
            module="safety_pv",
            scope_id="my009_uc_s1",
            sources=[
                SourceAdmissionSource(
                    source_role_code="safety_analysis_listing",
                    source_role="安全性分析listing",
                    source_entry_id=f"source_{revision}",
                    validation_id=f"validation_{revision}",
                    revision=revision,
                    validator_version="source_content_consistency_v1",
                    technical_status="ready",
                    content_status="warning",
                    use_status="confirmed_after_warning" if ready else "requires_confirmation",
                    public_title="MY009 20260410 Comparison listing",
                    summary="来源内容状态仍为警告。",
                )
            ],
            ready_for_use=ready,
        )

    def test_pv_promotion_requires_confirmation_and_stale_source_stops_handoff(self):
        signal = self.ae_signal()
        current = {"state": self.admission(revision=1, ready=True)}
        service = SafetyReviewWorkbenchService(
            CachedSafetyManifestService(self.manifest),
            self.store,
            lambda project_id, package_id: current["state"],
        )
        service.apply_action(
            PROJECT_ID,
            "my009_uc_s1",
            signal.signal_id,
            SafetyReviewActionRequest(action=SafetyReviewAction.MARK_MEDICAL_REVIEWED, comment="医学复核完成。"),
        )
        current["state"] = self.admission(revision=2, ready=False)
        stale_workbench = service.workbench(PROJECT_ID, "my009_uc_s1", signal.signal_id)
        self.assertEqual("来源已变化，需重新医学复核", stale_workbench.current_status)
        self.assertEqual(
            "blocked",
            next(
                gate
                for gate in stale_workbench.quality_gates
                if gate.gate_id == "my009_uc_s1:review_source_current"
            ).status,
        )
        with self.assertRaises(SourceAdmissionRequired):
            service.apply_action(
                PROJECT_ID,
                "my009_uc_s1",
                signal.signal_id,
                SafetyReviewActionRequest(action=SafetyReviewAction.REQUEST_PV_CONFIRMATION, comment="申请PV确认。"),
            )

        current["state"] = self.admission(revision=2, ready=True)
        with self.assertRaisesRegex(ValueError, "重新完成医学复核"):
            service.apply_action(
                PROJECT_ID,
                "my009_uc_s1",
                signal.signal_id,
                SafetyReviewActionRequest(action=SafetyReviewAction.REQUEST_PV_CONFIRMATION, comment="尝试沿用旧版本复核。"),
            )
        service.apply_action(
            PROJECT_ID,
            "my009_uc_s1",
            signal.signal_id,
            SafetyReviewActionRequest(action=SafetyReviewAction.MARK_MEDICAL_REVIEWED, comment="已基于当前来源重新完成医学复核。"),
        )
        promoted = service.apply_action(
            PROJECT_ID,
            "my009_uc_s1",
            signal.signal_id,
            SafetyReviewActionRequest(action=SafetyReviewAction.REQUEST_PV_CONFIRMATION, comment="已确认来源警告，申请PV确认。"),
        )
        self.assertEqual("warning", promoted.source_admission.sources[0].content_status)
        self.assertEqual("confirmed_after_warning", promoted.source_admission.sources[0].use_status)
        self.assertEqual(1, service.handoff_candidates(PROJECT_ID).total_candidates)

        current["state"] = self.admission(revision=3, ready=True)
        stale = service.handoff_candidates(PROJECT_ID)
        self.assertEqual(0, stale.total_candidates)
        self.assertEqual(1, stale.blocked_stale_candidate_count)
        self.assertEqual("blocked", next(g for g in stale.quality_gates if g.gate_id == "safety_source_version_current").status)
        with self.assertRaisesRegex(ValueError, "重新完成医学复核"):
            service.apply_action(
                PROJECT_ID,
                "my009_uc_s1",
                signal.signal_id,
                SafetyReviewActionRequest(action=SafetyReviewAction.REQUEST_PV_CONFIRMATION, comment="不得直接重新绑定新来源。"),
            )

    def test_review_workbench_initializes_from_real_manifest_candidates(self):
        workbench = self.service.workbench(PROJECT_ID, package_id="my009_uc_s1")

        self.assertEqual("安全信号与PV协同", workbench.module_label)
        self.assertEqual("待医学/PV确认", workbench.current_status)
        self.assertGreaterEqual(len(workbench.candidate_signals), 4)
        self.assertIsNotNone(workbench.selected_signal)
        self.assertGreaterEqual(len(workbench.listing_context), 4)
        self.assertGreaterEqual(len(workbench.document_context), 1)
        self.assertIn(SafetyReviewAction.MARK_MEDICAL_REVIEWED, workbench.available_actions)
        self.assertFalse(workbench.codex_runtime_dependency)

    def test_missing_source_admission_resolver_fails_closed_for_medical_review(self):
        signal = self.ae_signal()
        strict_service = SafetyReviewWorkbenchService(
            CachedSafetyManifestService(self.manifest),
            self.store,
        )
        with self.assertRaises(SourceAdmissionRequired):
            strict_service.apply_action(
                PROJECT_ID,
                "my009_uc_s1",
                signal.signal_id,
                SafetyReviewActionRequest(action=SafetyReviewAction.MARK_MEDICAL_REVIEWED, comment="医学复核。"),
            )

    def test_main_source_candidates_use_the_exact_safety_manifest_sources(self):
        self.assertEqual(
            main_module.MY009_LISTING.resolve(),
            Path(main_module.SOURCE_REGISTRY_CANDIDATES["pv-my009-mm-listing"]["path"]).resolve(),
        )
        self.assertEqual(
            main_module.MY009_S1_ROOT.resolve(),
            Path(main_module.SOURCE_REGISTRY_CANDIDATES["pv-my009-safety-package"]["path"]).resolve(),
        )
        self.assertEqual(
            main_module.MY009_DSUR_DOC.resolve(),
            Path(main_module.SOURCE_REGISTRY_CANDIDATES["pv-my009-dsur"]["path"]).resolve(),
        )
        self.assertEqual(
            main_module.RUX_LISTING_PATH.resolve(),
            Path(main_module.SOURCE_REGISTRY_CANDIDATES["pv-rux-mm-listing"]["path"]).resolve(),
        )
        rux_requirements = main_module.SOURCE_ADMISSION_REQUIREMENTS[(
            "safety_pv",
            "proj_rux_03_002",
            "rux_03_002_pv",
        )]
        self.assertEqual(
            ["safety_analysis_listing", "pv_plan_package", "clinical_safety_summary_package"],
            [item[0] for item in rux_requirements],
        )

    def test_action_chain_persists_status_records_and_handoff_candidate(self):
        signal = self.ae_signal()

        with self.assertRaises(ValueError):
            self.service.apply_action(
                PROJECT_ID,
                "my009_uc_s1",
                signal.signal_id,
                SafetyReviewActionRequest(action=SafetyReviewAction.REQUEST_PV_CONFIRMATION, comment="需要PV确认"),
            )

        reviewed = self.service.apply_action(
            PROJECT_ID,
            "my009_uc_s1",
            signal.signal_id,
            SafetyReviewActionRequest(action=SafetyReviewAction.MARK_MEDICAL_REVIEWED, actor="medical_manager", comment="已完成医学复核，建议进入PV协同确认。"),
        )
        self.assertEqual("医学已复核", reviewed.current_status)

        pv_candidate = self.service.apply_action(
            PROJECT_ID,
            "my009_uc_s1",
            signal.signal_id,
            SafetyReviewActionRequest(action=SafetyReviewAction.REQUEST_PV_CONFIRMATION, actor="medical_manager", comment="请PV基于AE/MH、SAE字段和医学解释进一步确认。"),
        )
        self.assertEqual("PV确认候选", pv_candidate.current_status)
        self.assertEqual(2, len(pv_candidate.review_records))

        handoff = self.service.handoff_candidates(PROJECT_ID)
        self.assertEqual(1, handoff.total_candidates)
        self.assertEqual(signal.signal_id, handoff.candidates[0].signal_id)
        self.assertIn("DSUR/IB安全更新素材", handoff.candidates[0].recommended_handoff_sections)
        self.assertFalse(handoff.codex_runtime_dependency)

    def test_all_state_changing_actions_require_comment_and_reset_is_explicit(self):
        signal = self.ae_signal()

        with self.assertRaises(ValueError):
            self.service.apply_action(
                PROJECT_ID,
                "my009_uc_s1",
                signal.signal_id,
                SafetyReviewActionRequest(action=SafetyReviewAction.RETURN_FOR_SOURCE_CHECK, comment=""),
            )

        with self.assertRaises(ValueError):
            self.service.apply_action(
                PROJECT_ID,
                "my009_uc_s1",
                signal.signal_id,
                SafetyReviewActionRequest(action=SafetyReviewAction.RESET_REVIEW, comment=""),
            )
        reviewed = self.service.apply_action(
            PROJECT_ID,
            "my009_uc_s1",
            signal.signal_id,
            SafetyReviewActionRequest(
                action=SafetyReviewAction.MARK_MEDICAL_REVIEWED,
                comment="已完成医学复核。",
            ),
        )
        self.assertEqual("医学已复核", reviewed.current_status)
        reset = self.service.apply_action(
            PROJECT_ID,
            "my009_uc_s1",
            signal.signal_id,
            SafetyReviewActionRequest(
                action=SafetyReviewAction.RESET_REVIEW,
                comment="发现新的资料批次，需要重新开启医学复核。",
            ),
        )
        self.assertEqual("待医学/PV确认", reset.current_status)

    def test_endpoint_uses_same_store_for_actions_and_handoff_candidates(self):
        signal = self.ae_signal()
        original_service = main_module.safety_review_workbench_service
        main_module.safety_review_workbench_service = self.service
        try:
            client = TestClient(main_module.app)
            get_response = client.get(f"/api/projects/{PROJECT_ID}/safety-pv/review-workbench?package_id=my009_uc_s1&signal_id={signal.signal_id}")
            self.assertEqual(200, get_response.status_code)
            self.assertEqual("待医学/PV确认", get_response.json()["current_status"])

            review_response = client.post(
                f"/api/projects/{PROJECT_ID}/safety-pv/review-workbench/my009_uc_s1/signals/{signal.signal_id}/actions",
                json={"action": "mark_medical_reviewed", "actor": "medical_manager", "comment": "医学复核完成，转PV协同前保留来源定位。"},
            )
            self.assertEqual(200, review_response.status_code)
            self.assertEqual("医学已复核", review_response.json()["current_status"])

            pv_response = client.post(
                f"/api/projects/{PROJECT_ID}/safety-pv/review-workbench/my009_uc_s1/signals/{signal.signal_id}/actions",
                json={"action": "request_pv_confirmation", "actor": "medical_manager", "comment": "请PV确认报告性判断和后续流程。"},
            )
            self.assertEqual(200, pv_response.status_code)
            self.assertEqual("PV确认候选", pv_response.json()["current_status"])

            handoff_response = client.get(f"/api/projects/{PROJECT_ID}/safety-pv/handoff-candidates")
            self.assertEqual(200, handoff_response.status_code)
            self.assertEqual(1, handoff_response.json()["total_candidates"])
        finally:
            main_module.safety_review_workbench_service = original_service

    def test_public_payload_has_no_paths_lifecycle_or_forbidden_pv_terms(self):
        signal = self.ae_signal()
        self.service.apply_action(
            PROJECT_ID,
            "my009_uc_s1",
            signal.signal_id,
            SafetyReviewActionRequest(action=SafetyReviewAction.MARK_MEDICAL_REVIEWED, comment="医学复核完成。"),
        )
        self.service.apply_action(
            PROJECT_ID,
            "my009_uc_s1",
            signal.signal_id,
            SafetyReviewActionRequest(action=SafetyReviewAction.REQUEST_PV_CONFIRMATION, comment="请PV协同确认。"),
        )

        serialized = json.dumps(
            {
                "workbench": self.service.workbench(PROJECT_ID, package_id="my009_uc_s1", signal_id=signal.signal_id).model_dump(mode="json"),
                "handoff": self.service.handoff_candidates(PROJECT_ID).model_dump(mode="json"),
            },
            ensure_ascii=False,
        )

        for forbidden in [
            "/Users/",
            "朗来项目资料/",
            "康哲项目资料/",
            "第9环节",
            "阶段9",
            "Stage 9",
            "正式PV判定",
            "PV正式判定",
            "PV最终判定",
            "E2B",
            "监管clock",
            "case intake",
            "PV数据库写入",
            "提交PV",
            "批准PV",
            "生成E2B",
            "写入PV",
            "final_seriousness",
            "final_expectedness",
            "final_causality",
        ]:
            self.assertNotIn(forbidden, serialized)

    def test_store_filters_other_projects_and_skips_corrupt_lines(self):
        self.store.path.write_text("{not json}\n", encoding="utf-8")
        other_project = SafetyReviewRecord(
            record_id="other_project_record",
            project_id="other_project",
            package_id="my009_uc_s1",
            signal_id="signal_1",
            signal_label="其他项目",
            action=SafetyReviewAction.MARK_MEDICAL_REVIEWED,
            actor="medical_manager",
            previous_status="待医学/PV确认",
            new_status="医学已复核",
            comment="其他项目记录。",
            created_at=datetime.now(timezone.utc),
        )
        current_project = other_project.model_copy(update={"record_id": "current_project_record", "project_id": PROJECT_ID, "comment": "当前项目记录。"})
        self.store.append(other_project)
        self.store.append(current_project)

        records = self.store.records(PROJECT_ID)
        self.assertEqual(1, len(records))
        self.assertEqual("current_project_record", records[0].record_id)


if __name__ == "__main__":
    unittest.main()
