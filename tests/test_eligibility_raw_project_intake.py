from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.api.app.eligibility_raw_intake import (
    EligibilityRawProjectIntakeService,
    RawEligibilityProjectConfig,
)

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal runtimes.
    TestClient = None


D001_PROTOCOL = Path(
    "/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目/"
    "CMS-D001 银屑病2、3期临床方案 v1.0-2025.12.21.docx"
)
D001_SUBJECT_ROOT = Path("/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目/全量-入组")

MY009_PROTOCOL = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/方案及配套资料/3.0/"
    "MY009-UC-Ⅱa期-临床研究方案-V3.0 20250926-clean (1).docx"
)
MY009_SUBJECT_ROOT = Path("/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/EVF审核")


class EligibilityRawProjectIntakeTests(unittest.TestCase):
    def test_same_path_content_change_rotates_source_and_subject_revisions(self) -> None:
        service = EligibilityRawProjectIntakeService(ai_provider_configured=False)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject_dir = root / "SA00001"
            subject_dir.mkdir()
            source = subject_dir / "source.pdf"
            source.write_bytes(b"first-source-version")
            config = RawEligibilityProjectConfig(
                project_id="proj_revision_probe",
                protocol_path=source,
                raw_subject_root=root,
            )

            first = service.subject_manifest(config, "SA00001")
            source.write_bytes(b"second-source-version-with-different-content")
            second = service.subject_manifest(config, "SA00001")

        self.assertEqual(first.sources[0].source_id, second.sources[0].source_id)
        self.assertNotEqual(first.sources[0].source_revision, second.sources[0].source_revision)
        self.assertNotEqual(first.subject_source_revision, second.subject_source_revision)
        self.assertTrue(first.sources[0].source_revision.startswith("eligsrcv_"))
        self.assertTrue(first.subject_source_revision.startswith("eligsubsrcv_"))

    def test_public_revision_tokens_are_opaque_and_do_not_expose_content_hashes(self) -> None:
        service = EligibilityRawProjectIntakeService(ai_provider_configured=False)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject_dir = root / "S00001"
            subject_dir.mkdir()
            source = subject_dir / "record.png"
            source.write_bytes(b"opaque-revision-probe")
            config = RawEligibilityProjectConfig(
                project_id="proj_public_probe",
                protocol_path=source,
                raw_subject_root=root,
            )
            payload = service.subject_manifest(config, "S00001").public_dict(
                include_sources=True
            )

        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.assertIn("subject_source_revision", payload)
        self.assertIn("source_revision", payload["sources"][0])
        self.assertNotIn("content_hash", serialized)
        self.assertNotIn("opaque-revision-probe", serialized)
        self.assertNotIn(str(root), serialized)

    def test_private_source_resolver_requires_current_opaque_identity(self) -> None:
        service = EligibilityRawProjectIntakeService(ai_provider_configured=False)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject_dir = root / "SA00001"
            subject_dir.mkdir()
            source_path = subject_dir / "record.png"
            source_path.write_bytes(b"private-source-v1")
            config = RawEligibilityProjectConfig(
                project_id="proj_private_resolver",
                protocol_path=source_path,
                raw_subject_root=root,
            )
            manifest = service.subject_manifest(config, "SA00001")
            source = manifest.sources[0]

            resolved = service.resolve_subject_source_path(
                config,
                "SA00001",
                source.source_id,
                source.source_revision,
            )
            self.assertEqual(source_path.resolve(), resolved)

            source_path.write_bytes(b"private-source-v2")
            with self.assertRaises(KeyError):
                service.resolve_subject_source_path(
                    config,
                    "SA00001",
                    source.source_id,
                    source.source_revision,
                )
            with self.assertRaises(KeyError):
                service.resolve_subject_source_path(
                    config,
                    "SA00001",
                    "eligsrc_unknown",
                    source.source_revision,
                )

    @unittest.skipUnless(
        D001_PROTOCOL.exists() and D001_SUBJECT_ROOT.exists(),
        "D001 raw protocol and full enrollment source bundle are not available",
    )
    def test_d001_raw_project_intake_uses_full_source_pool_without_legacy_outputs(self) -> None:
        service = EligibilityRawProjectIntakeService(ai_provider_configured=False)

        snapshot = service.discover_project(
            RawEligibilityProjectConfig(
                project_id="d001_raw_intake",
                project_label="CMS-D001 银屑病",
                protocol_path=D001_PROTOCOL,
                raw_subject_root=D001_SUBJECT_ROOT,
            )
        )

        self.assertEqual("source_registry/raw_source", snapshot.source_system)
        self.assertIn("D001", snapshot.protocol.title + snapshot.protocol.filename)
        self.assertGreater(snapshot.protocol.paragraph_count, 100)
        self.assertGreater(snapshot.protocol.span_count, 100)
        self.assertGreaterEqual(snapshot.subject_pool.unique_subject_count, 100)
        self.assertGreaterEqual(snapshot.subject_pool.total_files, 1000)
        self.assertGreaterEqual(snapshot.subject_pool.source_type_counts.get("pdf", 0), 900)
        self.assertGreater(snapshot.subject_pool.source_type_counts.get("image", 0), 0)
        self.assertGreater(snapshot.subject_pool.archive_count, 0)
        self.assertIn("SA", snapshot.subject_pool.subject_id_prefixes)

        task_types = {task.task_type for task in snapshot.ai_task_plan}
        self.assertIn("protocol_rule_extraction", task_types)
        self.assertIn("eligibility_rule_review", task_types)
        self.assertTrue(all(task.status == "blocked_external_ai_not_configured" for task in snapshot.ai_task_plan))
        self.assertIn("enrollment-review-app", snapshot.forbidden_legacy_inputs)
        self.assertIn("legacy_evidence_bundle", snapshot.forbidden_legacy_inputs)

        public_payload = json.dumps(snapshot.public_dict(), ensure_ascii=False)
        for forbidden in (
            "/Users/",
            "source_path",
            "server_path",
            "content_hash",
            "preview_hash",
            "storage_key",
            "llm/",
        ):
            self.assertNotIn(forbidden, public_payload)

    @unittest.skipUnless(
        MY009_PROTOCOL.exists() and MY009_SUBJECT_ROOT.exists(),
        "MY009 raw protocol and EVF source bundle are not available",
    )
    def test_my009_generalizes_subject_discovery_beyond_d001_sa_prefix(self) -> None:
        service = EligibilityRawProjectIntakeService(ai_provider_configured=False)

        snapshot = service.discover_project(
            RawEligibilityProjectConfig(
                project_id="my009_uc_raw_intake",
                project_label="MY009 UC",
                protocol_path=MY009_PROTOCOL,
                raw_subject_root=MY009_SUBJECT_ROOT,
            )
        )

        self.assertEqual("source_registry/raw_source", snapshot.source_system)
        self.assertIn("MY009", snapshot.protocol.title + snapshot.protocol.filename)
        self.assertGreater(snapshot.protocol.paragraph_count, 100)
        self.assertGreaterEqual(snapshot.subject_pool.unique_subject_count, 5)
        self.assertGreaterEqual(snapshot.subject_pool.total_files, 20)
        self.assertGreater(snapshot.subject_pool.source_type_counts.get("pdf", 0), 0)
        self.assertIn("S", snapshot.subject_pool.subject_id_prefixes)
        self.assertNotEqual(["SA"], snapshot.subject_pool.subject_id_prefixes)

        public_payload = json.dumps(snapshot.public_dict(), ensure_ascii=False)
        self.assertNotIn("/Users/", public_payload)
        self.assertNotIn("D001", public_payload)
        self.assertNotIn("SA07005", public_payload)

    @unittest.skipUnless(
        TestClient is not None and D001_PROTOCOL.exists() and D001_SUBJECT_ROOT.exists(),
        "FastAPI or D001 raw source files are not available",
    )
    def test_raw_intake_api_exposes_d001_snapshot_without_breaking_legacy_adapter(self) -> None:
        from services.api.app.main import app

        client = TestClient(app)
        response = client.get("/api/projects/d001_raw_intake/eligibility/raw-intake")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("source_registry/raw_source", payload["source_system"])
        self.assertGreaterEqual(payload["subject_pool"]["unique_subject_count"], 100)
        self.assertIn("protocol_rule_extraction", {task["task_type"] for task in payload["ai_task_plan"]})
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("content_hash", serialized)

    @unittest.skipUnless(
        D001_PROTOCOL.exists() and D001_SUBJECT_ROOT.exists(),
        "D001 raw protocol and full enrollment source bundle are not available",
    )
    def test_d001_subject_manifests_use_opaque_sources_without_directory_labels(self) -> None:
        service = EligibilityRawProjectIntakeService(ai_provider_configured=False)
        config = RawEligibilityProjectConfig(
            project_id="proj_d001",
            protocol_path=D001_PROTOCOL,
            raw_subject_root=D001_SUBJECT_ROOT,
        )

        subjects = service.subject_manifests(config)
        by_id = {subject.subject_id: subject for subject in subjects}

        self.assertGreaterEqual(len(subjects), 100)
        for subject_id in ("SA07005", "SA17004", "SA11004", "SA04002", "SA07007"):
            self.assertIn(subject_id, by_id)
            self.assertGreater(by_id[subject_id].file_count, 0)
            self.assertTrue(by_id[subject_id].subject_token.startswith("eligsub_"))
        detail = service.subject_manifest(config, "SA07007").public_dict(include_sources=True)
        self.assertTrue(all(source["source_id"].startswith("eligsrc_") for source in detail["sources"]))
        self.assertEqual(len(detail["sources"]), len({source["source_id"] for source in detail["sources"]}))
        serialized = json.dumps(detail, ensure_ascii=False)
        for forbidden in (
            "/Users/",
            "relative_path",
            "filename",
            "阳性导致筛败",
            "白铭江",
        ):
            self.assertNotIn(forbidden, serialized)

    @unittest.skipUnless(
        MY009_PROTOCOL.exists() and MY009_SUBJECT_ROOT.exists(),
        "MY009 raw protocol and EVF source bundle are not available",
    )
    def test_my009_subject_manifests_cover_five_real_candidates_without_label_leakage(self) -> None:
        service = EligibilityRawProjectIntakeService(ai_provider_configured=False)
        config = RawEligibilityProjectConfig(
            project_id="proj_my009_uc",
            protocol_path=MY009_PROTOCOL,
            raw_subject_root=MY009_SUBJECT_ROOT,
        )

        subjects = service.subject_manifests(config)
        by_id = {subject.subject_id: subject for subject in subjects}

        for subject_id in ("S01009", "S08001", "S01008", "S05003", "S01003"):
            self.assertIn(subject_id, by_id)
            self.assertGreater(by_id[subject_id].file_count, 0)
        detail = service.subject_manifest(config, "s01003").public_dict(include_sources=True)
        self.assertEqual("proj_my009_uc", detail["project_id"])
        self.assertTrue(any(source["requires_visual_fallback"] for source in detail["sources"]))
        serialized = json.dumps(detail, ensure_ascii=False)
        self.assertNotIn("V3筛败", serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("relative_path", serialized)

    @unittest.skipUnless(
        TestClient is not None
        and D001_SUBJECT_ROOT.exists()
        and MY009_SUBJECT_ROOT.exists(),
        "FastAPI or raw eligibility sources are unavailable",
    )
    def test_subject_manifest_api_uses_canonical_project_ids_and_safe_public_fields(self) -> None:
        from services.api.app.main import app

        client = TestClient(app)
        d001 = client.get("/api/projects/d001_raw_intake/eligibility/raw-intake/subjects")
        my009 = client.get("/api/projects/my009_uc_raw_intake/eligibility/raw-intake/subjects/S01009")

        self.assertEqual(200, d001.status_code, d001.text)
        self.assertEqual(200, my009.status_code, my009.text)
        self.assertEqual("proj_d001", d001.json()["project_id"])
        self.assertEqual("proj_my009_uc", my009.json()["project_id"])
        self.assertGreaterEqual(d001.json()["subject_count"], 100)
        combined = d001.text + my009.text
        for forbidden in ("/Users/", "relative_path", "root_path", "filename", "筛败"):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
