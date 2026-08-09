from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import unittest

from services.api.app.monitoring_real_loop_prompt_manifest import (
    RealLoopPromptManifestError,
    RealLoopPromptIssueCode,
    assess_real_loop_prompt_manifest,
    build_real_loop_prompt_manifest,
    real_loop_prompt_manifest_payload,
)


class RealLoopPromptManifestTests(unittest.TestCase):
    def test_canonical_manifest_has_40_distinct_auditable_prompts(self) -> None:
        manifest = build_real_loop_prompt_manifest()
        report = assess_real_loop_prompt_manifest(manifest)

        self.assertEqual(40, len(manifest))
        self.assertEqual("valid", report.status)
        self.assertEqual((), report.issues)
        self.assertEqual(40, len({row.prompt_id for row in manifest}))
        self.assertEqual(40, len({row.scenario_id for row in manifest}))
        self.assertEqual(40, len({row.prompt_sha256 for row in manifest}))
        self.assertEqual(40, len({row.prompt_text for row in manifest}))
        self.assertEqual(
            "medical_monitoring_real_loop_prompt_manifest_v2",
            real_loop_prompt_manifest_payload(manifest)["schema_version"],
        )

    def test_manifest_varies_by_project_role_and_task(self) -> None:
        manifest = build_real_loop_prompt_manifest()
        rows = {row.scenario_id: row for row in manifest}

        self.assertIn(
            "Project identity: proj_rux_03_002",
            rows["proj_rux_03_002:engineer:field_semantic_mapping"].prompt_text,
        )
        self.assertNotEqual(
            rows["proj_rux_03_002:engineer:field_semantic_mapping"].prompt_text,
            rows["proj_my009_uc:engineer:field_semantic_mapping"].prompt_text,
        )
        self.assertIn(
            "Project identity: proj_my008_3_02_candidate",
            rows["proj_my008_3_02_candidate:engineer:field_semantic_mapping"].prompt_text,
        )
        self.assertNotEqual(
            rows["proj_rux_03_002:engineer:field_semantic_mapping"].prompt_text,
            rows[
                "proj_rux_03_002:senior_medical_monitor:field_semantic_mapping"
            ].prompt_text,
        )
        self.assertNotEqual(
            rows["proj_rux_03_002:engineer:field_semantic_mapping"].prompt_text,
            rows["proj_rux_03_002:engineer:risk_evidence_summary"].prompt_text,
        )

    def test_missing_or_duplicate_coverage_blocks(self) -> None:
        manifest = list(build_real_loop_prompt_manifest())
        manifest.pop()
        report = assess_real_loop_prompt_manifest(manifest)

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopPromptIssueCode.COVERAGE_MISSING,
            {issue.code for issue in report.issues},
        )

        duplicate = list(build_real_loop_prompt_manifest())
        duplicate.append(duplicate[0])
        duplicate_report = assess_real_loop_prompt_manifest(duplicate)
        self.assertIn(
            RealLoopPromptIssueCode.DUPLICATE_PROMPT_REF,
            {issue.code for issue in duplicate_report.issues},
        )

        duplicate_variant = list(build_real_loop_prompt_manifest())
        duplicate_variant[1] = replace(
            duplicate_variant[1], variant_key=duplicate_variant[0].variant_key
        )
        duplicate_variant_report = assess_real_loop_prompt_manifest(duplicate_variant)
        self.assertEqual("blocked", duplicate_variant_report.status)
        self.assertIn(
            RealLoopPromptIssueCode.DUPLICATE_VARIANT,
            {issue.code for issue in duplicate_variant_report.issues},
        )

    def test_exact_hash_and_identity_markers_are_fail_closed(self) -> None:
        row = build_real_loop_prompt_manifest()[0]
        with self.assertRaises(RealLoopPromptManifestError):
            replace(row, prompt_sha256="0" * 64)
        for invalid_hash in (
            f" {row.prompt_sha256}",
            row.prompt_sha256.upper(),
        ):
            with self.subTest(invalid_hash=invalid_hash):
                with self.assertRaises(RealLoopPromptManifestError):
                    replace(row, prompt_sha256=invalid_hash)
        with self.assertRaises(RealLoopPromptManifestError):
            replace(row, prompt_text="Project identity: unrelated")

    def test_empty_manifest_is_blocked(self) -> None:
        report = assess_real_loop_prompt_manifest(())

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopPromptIssueCode.PROMPT_MANIFEST_EMPTY,
            {issue.code for issue in report.issues},
        )

    def test_frozen_audit_artifact_matches_source_builder(self) -> None:
        manifest = build_real_loop_prompt_manifest()
        report = assess_real_loop_prompt_manifest(manifest)
        artifact_path = (
            Path(__file__).resolve().parents[1]
            / "records/active_slices/medical_monitoring_real_loop_prompt_manifest_20260802/PROMPT_MANIFEST.json"
        )
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        payload = real_loop_prompt_manifest_payload(manifest)

        self.assertEqual(payload["manifest_sha256"], artifact["manifest_sha256"])
        self.assertEqual(report.manifest_sha256, artifact["report_sha256"])
        self.assertEqual(payload["prompt_count"], artifact["prompt_count"])
        self.assertEqual(
            [
                {
                    "prompt_id": row.prompt_id,
                    "scenario_id": row.scenario_id,
                    "project_id": row.project_id,
                    "role": row.role,
                    "task_type": row.task_type,
                    "variant_key": row.variant_key,
                    "prompt_sha256": row.prompt_sha256,
                }
                for row in manifest
            ],
            artifact["prompts"],
        )


if __name__ == "__main__":
    unittest.main()
