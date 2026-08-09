from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import TflReviewAction, TflReviewActionRequest  # noqa: E402
from services.api.app import main as main_module  # noqa: E402
from services.api.app.tfl_manifest import MY008_ROOT, RUX_DATASET_ROOT, TflManifestService  # noqa: E402
from services.api.app.tfl_review_workbench import TflReviewStore, TflReviewWorkbenchService  # noqa: E402
from services.api.app.source_admission import SourceAdmissionRequired  # noqa: E402


@unittest.skipUnless(RUX_DATASET_ROOT.exists() and MY008_ROOT.exists(), "TFL review fixture paths are unavailable")
class TflReviewWorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest_service = TflManifestService()
        cls.my008_manifest = cls.manifest_service.build_manifest("proj_my008_pnh_3_01")
        cls.my008_package = cls.my008_manifest.packages[0]
        cls.paired_output = next(output for output in cls.my008_package.outputs if output.paired_file_id)

    def service(self, store_path: Path):
        return TflReviewWorkbenchService(
            self.manifest_service,
            TflReviewStore(store_path),
            allow_unvalidated_sources=True,
        )

    def test_workbench_public_contract_has_no_local_paths_or_lifecycle_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.service(Path(tmp) / "tfl_review_actions.jsonl").workbench(
                "proj_rux_03_002",
                package_id="rux_03_002",
            )
        payload = result.model_dump(mode="json")
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertEqual("data_analysis_tfl", payload["module"])
        self.assertEqual("数据分析与TFL", payload["module_label"])
        self.assertEqual("待医学审阅", payload["current_status"])
        self.assertTrue(payload["needs_medical_confirmation"])
        self.assertFalse(payload["codex_runtime_dependency"])
        self.assertIn("不生成正式监管TFL", payload["formal_output_boundary"])
        self.assertGreater(len(payload["candidate_outputs"]), 0)
        self.assertGreater(len(payload["quality_gates"]), 0)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("第7环节", serialized)
        self.assertNotIn("阶段7", serialized)

    def test_review_action_chain_persists_status_and_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "tfl_review_actions.jsonl"
            service = self.service(store_path)

            reviewed = service.apply_action(
                "proj_my008_pnh_3_01",
                "my008_pnh_3_01",
                self.paired_output.output_id,
                TflReviewActionRequest(
                    action=TflReviewAction.MARK_REVIEWED,
                    actor="medical_manager",
                    comment="医学已核对表题、领域和配对数据集，作为写作候选前置审阅。",
                ),
            )
            self.assertEqual("医学已审阅", reviewed.current_status)

            candidate = service.apply_action(
                "proj_my008_pnh_3_01",
                "my008_pnh_3_01",
                self.paired_output.output_id,
                TflReviewActionRequest(
                    action=TflReviewAction.CREATE_WRITING_CANDIDATE,
                    actor="medical_manager",
                    comment="允许进入医学写作引用候选，但正式引用前仍需统计复核。",
                ),
            )
            self.assertEqual("写作引用候选", candidate.current_status)
            self.assertEqual(2, len(candidate.review_records))

            reloaded = self.service(store_path).workbench(
                "proj_my008_pnh_3_01",
                package_id="my008_pnh_3_01",
                output_id=self.paired_output.output_id,
            )
            self.assertEqual("写作引用候选", reloaded.current_status)
            self.assertEqual(2, len(reloaded.review_records))

    def test_action_validation_blocks_unsafe_disposition(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(Path(tmp) / "tfl_review_actions.jsonl")

            with self.assertRaisesRegex(ValueError, "必须填写"):
                service.apply_action(
                    "proj_my008_pnh_3_01",
                    "my008_pnh_3_01",
                    self.paired_output.output_id,
                    TflReviewActionRequest(action=TflReviewAction.MARK_REVIEWED, comment=""),
                )

            with self.assertRaisesRegex(ValueError, "需先完成医学审阅"):
                service.apply_action(
                    "proj_my008_pnh_3_01",
                    "my008_pnh_3_01",
                    self.paired_output.output_id,
                    TflReviewActionRequest(
                        action=TflReviewAction.CREATE_WRITING_CANDIDATE,
                        comment="尝试跳过医学审阅直接进入写作候选。",
                    ),
                )

    def test_missing_source_admission_resolver_fails_closed_for_medical_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = TflReviewWorkbenchService(
                self.manifest_service,
                TflReviewStore(Path(tmp) / "tfl_review_actions.jsonl"),
            )
            with self.assertRaises(SourceAdmissionRequired):
                service.apply_action(
                    "proj_my008_pnh_3_01",
                    "my008_pnh_3_01",
                    self.paired_output.output_id,
                    TflReviewActionRequest(action=TflReviewAction.MARK_REVIEWED, comment="医学审阅。"),
                )

    def test_main_source_candidates_use_the_exact_manifest_roots(self):
        self.assertEqual(
            main_module.RUX_DATASET_ROOT.resolve(),
            Path(main_module.SOURCE_REGISTRY_CANDIDATES["tfl-rux-sdtm-package"]["path"]).resolve(),
        )
        self.assertEqual(
            main_module.RUX_TFL_SINGLE_ROOT.resolve(),
            Path(main_module.SOURCE_REGISTRY_CANDIDATES["tfl-rux-final-tfl"]["path"]).resolve(),
        )
        self.assertEqual(
            main_module.MY008_ROOT.resolve(),
            Path(main_module.SOURCE_REGISTRY_CANDIDATES["tfl-my008-dataset-package"]["path"]).resolve(),
        )
        self.assertEqual(
            (main_module.MY008_ROOT / "tlf").resolve(),
            Path(main_module.SOURCE_REGISTRY_CANDIDATES["tfl-my008-output-package"]["path"]).resolve(),
        )

    def test_review_workbench_endpoint_and_action_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            temporary_service = self.service(Path(tmp) / "tfl_review_actions.jsonl")
            original_service = main_module.tfl_review_workbench_service
            main_module.tfl_review_workbench_service = temporary_service
            try:
                client = TestClient(main_module.app)
                response = client.get(
                    "/api/projects/proj_my008_pnh_3_01/tfl/review-workbench",
                    params={"package_id": "my008_pnh_3_01", "output_id": self.paired_output.output_id},
                )
                self.assertEqual(200, response.status_code)
                payload = response.json()
                self.assertEqual("数据分析与TFL", payload["module_label"])
                self.assertEqual(self.paired_output.output_id, payload["selected_output_id"])
                self.assertIsNotNone(payload["paired_dataset"])

                action_response = client.post(
                    f"/api/projects/proj_my008_pnh_3_01/tfl/review-workbench/my008_pnh_3_01/outputs/{self.paired_output.output_id}/actions",
                    json={
                        "action": "mark_reviewed",
                        "actor": "medical_manager",
                        "comment": "API路由动作测试：医学已审阅。",
                    },
                )
                self.assertEqual(200, action_response.status_code)
                self.assertEqual("医学已审阅", action_response.json()["current_status"])
            finally:
                main_module.tfl_review_workbench_service = original_service
