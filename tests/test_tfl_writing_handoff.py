from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import (  # noqa: E402
    SourceAdmissionSource,
    SourceAdmissionState,
    TflReviewAction,
    TflReviewActionRequest,
)
from services.api.app import main as main_module  # noqa: E402
from services.api.app.tfl_manifest import MY008_ROOT, RUX_DATASET_ROOT, TflManifestService  # noqa: E402
from services.api.app.tfl_review_workbench import TflReviewStore, TflReviewWorkbenchService  # noqa: E402
from services.api.app.tfl_writing_handoff import TflWritingHandoffService  # noqa: E402
from services.api.app.source_admission import SourceAdmissionRequired  # noqa: E402


class CachedTflManifestService:
    def __init__(self, manifest):
        self.manifest = manifest

    def build_manifest(self, project_id: str, force_refresh: bool = False):
        return self.manifest


@unittest.skipUnless(RUX_DATASET_ROOT.exists() and MY008_ROOT.exists(), "TFL handoff fixture paths are unavailable")
class TflWritingHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = TflManifestService().build_manifest("proj_my008_pnh_3_01")
        cls.cached_manifest_service = CachedTflManifestService(cls.manifest)
        my008_package = next(package for package in cls.manifest.packages if package.package_id == "my008_pnh_3_01")
        cls.paired_output = next(output for output in my008_package.outputs if output.paired_file_id and output.domain_hint in {"DM", "AE", "LB", ""})

    def services(self, store_path: Path):
        store = TflReviewStore(store_path)
        return (
            TflReviewWorkbenchService(self.cached_manifest_service, store, allow_unvalidated_sources=True),
            TflWritingHandoffService(self.cached_manifest_service, store, allow_unvalidated_sources=True),
        )

    def test_citation_handoff_uses_manifest_cache_without_forced_refresh(self):
        class RecordingManifestService:
            def __init__(self, manifest):
                self.manifest = manifest
                self.force_refresh_values = []

            def build_manifest(self, project_id: str, force_refresh: bool = False):
                self.force_refresh_values.append(force_refresh)
                return self.manifest

        with tempfile.TemporaryDirectory() as tmp:
            manifest_service = RecordingManifestService(self.manifest)
            handoff = TflWritingHandoffService(
                manifest_service,
                TflReviewStore(Path(tmp) / "review.jsonl"),
                allow_unvalidated_sources=True,
            )

            self.assertFalse(handoff.has_handoff_candidate_records("proj_my008_pnh_3_01"))
            handoff.citation_manifest("proj_my008_pnh_3_01")

            self.assertEqual([False], manifest_service.force_refresh_values)

    def admission(self, *, revision: int, ready: bool):
        use_status = "confirmed_after_warning" if ready else "requires_confirmation"
        source = SourceAdmissionSource(
            source_role_code="analysis_dataset_package",
            source_role="分析数据集包",
            source_entry_id=f"source_{revision}",
            validation_id=f"validation_{revision}",
            revision=revision,
            validator_version="source_content_consistency_v1",
            technical_status="ready",
            content_status="warning",
            use_status=use_status,
            public_title="真实分析数据集包",
            summary="项目标识仍为警告；医学经理可逐项确认后沿用。",
        )
        return SourceAdmissionState(
            project_id="proj_my008_pnh_3_01",
            module="data_analysis_tfl",
            scope_id="my008_pnh_3_01",
            sources=[source],
            ready_for_use=ready,
        )

    def test_source_confirmation_is_required_and_old_binding_is_blocked_at_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TflReviewStore(Path(tmp) / "tfl_review_actions.jsonl")
            current = {"state": self.admission(revision=1, ready=True)}
            resolver = lambda project_id, package_id: current["state"]
            review = TflReviewWorkbenchService(self.cached_manifest_service, store, resolver)
            handoff = TflWritingHandoffService(self.cached_manifest_service, store, resolver)
            review.apply_action(
                "proj_my008_pnh_3_01",
                "my008_pnh_3_01",
                self.paired_output.output_id,
                TflReviewActionRequest(action=TflReviewAction.MARK_REVIEWED, comment="医学审阅完成。"),
            )
            current["state"] = self.admission(revision=2, ready=False)
            stale_workbench = review.workbench(
                "proj_my008_pnh_3_01",
                "my008_pnh_3_01",
                self.paired_output.output_id,
            )
            self.assertEqual("来源已变化，需重新医学审阅", stale_workbench.current_status)
            self.assertEqual(
                "blocked",
                next(gate for gate in stale_workbench.quality_gates if gate.gate_id == "tfl_review_source_current").status,
            )
            with self.assertRaises(SourceAdmissionRequired):
                review.apply_action(
                    "proj_my008_pnh_3_01",
                    "my008_pnh_3_01",
                    self.paired_output.output_id,
                    TflReviewActionRequest(action=TflReviewAction.CREATE_WRITING_CANDIDATE, comment="申请写作引用。"),
                )

            current["state"] = self.admission(revision=2, ready=True)
            with self.assertRaisesRegex(ValueError, "重新完成医学审阅"):
                review.apply_action(
                    "proj_my008_pnh_3_01",
                    "my008_pnh_3_01",
                    self.paired_output.output_id,
                    TflReviewActionRequest(action=TflReviewAction.CREATE_WRITING_CANDIDATE, comment="尝试沿用旧版本审阅。"),
                )
            review.apply_action(
                "proj_my008_pnh_3_01",
                "my008_pnh_3_01",
                self.paired_output.output_id,
                TflReviewActionRequest(action=TflReviewAction.MARK_REVIEWED, comment="已基于当前来源重新完成医学审阅。"),
            )
            promoted = review.apply_action(
                "proj_my008_pnh_3_01",
                "my008_pnh_3_01",
                self.paired_output.output_id,
                TflReviewActionRequest(action=TflReviewAction.CREATE_WRITING_CANDIDATE, comment="已逐项确认来源警告，申请写作引用。"),
            )
            self.assertEqual("warning", promoted.source_admission.sources[0].content_status)
            self.assertEqual("confirmed_after_warning", promoted.source_admission.sources[0].use_status)
            self.assertEqual(1, handoff.citation_manifest("proj_my008_pnh_3_01").total_candidates)

            current["state"] = self.admission(revision=3, ready=True)
            stale = handoff.citation_manifest("proj_my008_pnh_3_01")
            self.assertEqual(0, stale.total_candidates)
            self.assertEqual(1, stale.blocked_stale_candidate_count)
            self.assertEqual("blocked", next(g for g in stale.quality_gates if g.gate_id == "tfl_source_version_current").status)
            with self.assertRaisesRegex(ValueError, "重新完成医学审阅"):
                review.apply_action(
                    "proj_my008_pnh_3_01",
                    "my008_pnh_3_01",
                    self.paired_output.output_id,
                    TflReviewActionRequest(action=TflReviewAction.CREATE_WRITING_CANDIDATE, comment="不得直接重新绑定新来源。"),
                )

    def test_empty_handoff_has_warning_gate_without_overclaim(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, handoff = self.services(Path(tmp) / "tfl_review_actions.jsonl")
            result = handoff.citation_manifest("proj_my008_pnh_3_01")

        payload = result.model_dump(mode="json")
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertEqual("医学写作", payload["module_label"])
        self.assertEqual("数据分析与TFL", payload["source_module_label"])
        self.assertEqual(0, payload["total_candidates"])
        self.assertEqual("warning", payload["quality_gates"][0]["status"])
        self.assertIn("不自动生成或改写正式医学写作正文", payload["formal_output_boundary"])
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("第7环节", serialized)
        self.assertNotIn("阶段7", serialized)

    def test_writing_candidate_handoff_surfaces_reviewed_tfl_and_dataset_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            review, handoff = self.services(Path(tmp) / "tfl_review_actions.jsonl")
            review.apply_action(
                "proj_my008_pnh_3_01",
                "my008_pnh_3_01",
                self.paired_output.output_id,
                TflReviewActionRequest(
                    action=TflReviewAction.MARK_REVIEWED,
                    comment="医学已核对TFL对象和配对数据集。",
                ),
            )
            review.apply_action(
                "proj_my008_pnh_3_01",
                "my008_pnh_3_01",
                self.paired_output.output_id,
                TflReviewActionRequest(
                    action=TflReviewAction.CREATE_WRITING_CANDIDATE,
                    comment="允许进入医学写作引用候选，正式写入前仍需统计复核。",
                ),
            )

            result = handoff.citation_manifest("proj_my008_pnh_3_01")

        self.assertEqual(1, result.total_candidates)
        candidate = result.candidates[0]
        self.assertEqual(self.paired_output.output_id, candidate.output_id)
        self.assertEqual(self.paired_output.display_id, candidate.output_display_id)
        self.assertTrue(candidate.paired_dataset_id)
        self.assertTrue(candidate.paired_dataset_name)
        self.assertIn("正式写入前仍需统计复核", candidate.review_comment)
        self.assertTrue(candidate.recommended_writing_sections)
        self.assertFalse(candidate.codex_runtime_dependency)
        self.assertTrue(all(gate.status == "passed" for gate in result.quality_gates))

    def test_reset_review_removes_handoff_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            review, handoff = self.services(Path(tmp) / "tfl_review_actions.jsonl")
            review.apply_action(
                "proj_my008_pnh_3_01",
                "my008_pnh_3_01",
                self.paired_output.output_id,
                TflReviewActionRequest(action=TflReviewAction.MARK_REVIEWED, comment="已审阅。"),
            )
            review.apply_action(
                "proj_my008_pnh_3_01",
                "my008_pnh_3_01",
                self.paired_output.output_id,
                TflReviewActionRequest(action=TflReviewAction.CREATE_WRITING_CANDIDATE, comment="写作候选。"),
            )
            review.apply_action(
                "proj_my008_pnh_3_01",
                "my008_pnh_3_01",
                self.paired_output.output_id,
                TflReviewActionRequest(action=TflReviewAction.RESET_REVIEW),
            )

            result = handoff.citation_manifest("proj_my008_pnh_3_01")

        self.assertEqual(0, result.total_candidates)

    def test_endpoint_reads_same_tfl_review_store_as_workbench(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TflReviewStore(Path(tmp) / "tfl_review_actions.jsonl")
            temporary_review = TflReviewWorkbenchService(self.cached_manifest_service, store, allow_unvalidated_sources=True)
            temporary_handoff = TflWritingHandoffService(self.cached_manifest_service, store, allow_unvalidated_sources=True)
            original_review = main_module.tfl_review_workbench_service
            original_handoff = main_module.tfl_writing_handoff_service
            main_module.tfl_review_workbench_service = temporary_review
            main_module.tfl_writing_handoff_service = temporary_handoff
            try:
                client = TestClient(main_module.app)
                review_response = client.post(
                    f"/api/projects/proj_my008_pnh_3_01/tfl/review-workbench/my008_pnh_3_01/outputs/{self.paired_output.output_id}/actions",
                    json={"action": "mark_reviewed", "comment": "API测试：医学已审阅。"},
                )
                self.assertEqual(200, review_response.status_code)
                handoff_blocked = client.post(
                    f"/api/projects/proj_my008_pnh_3_01/tfl/review-workbench/my008_pnh_3_01/outputs/{self.paired_output.output_id}/actions",
                    json={"action": "create_writing_candidate", "comment": "API测试：进入写作候选。"},
                )
                self.assertEqual(200, handoff_blocked.status_code)

                response = client.get("/api/projects/proj_my008_pnh_3_01/medical-writing/tfl-citation-candidates")
                self.assertEqual(200, response.status_code)
                payload = response.json()
                self.assertEqual(1, payload["total_candidates"])
                self.assertEqual(self.paired_output.output_id, payload["candidates"][0]["output_id"])
            finally:
                main_module.tfl_review_workbench_service = original_review
                main_module.tfl_writing_handoff_service = original_handoff
