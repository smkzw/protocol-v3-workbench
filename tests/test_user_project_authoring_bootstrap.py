from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from packages.contracts.workbench_contracts import (
    MedicalWritingGreenfieldCreateRequest,
    MedicalWritingGreenfieldSectionSeed,
    UserProjectCreateRequest,
)
from services.api.app import main as app_main
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.project_source_manifest import ProjectSourceManifestService
from services.api.app.user_project_store import UserProjectStore


class UserProjectAuthoringBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.user_projects = UserProjectStore(root / "user_projects.sqlite3")
        self.journeys = MedicalWritingAuthoringJourneyService(
            root / "authoring_journeys.sqlite3"
        )
        self.manifests = ProjectSourceManifestService(
            app_main.PROJECT_ROOT,
            user_project_store=self.user_projects,
        )
        self.patches = [
            patch.object(app_main, "user_project_store", self.user_projects),
            patch.object(
                app_main,
                "medical_writing_authoring_journey_service",
                self.journeys,
            ),
            patch.object(
                app_main,
                "project_source_manifest_service",
                self.manifests,
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tmpdir.cleanup()

    @staticmethod
    def _request(entry_mode: str, key: str) -> UserProjectCreateRequest:
        return UserProjectCreateRequest(
            project_code=f"QC-{entry_mode}",
            project_name="类风湿关节炎II期临床研究方案",
            indication="类风湿关节炎",
            product_name="RA-01",
            study_phase="II期",
            protocol_id=f"QC-{entry_mode}",
            protocol_version="V0.1",
            protocol_date="2026-07-15",
            entry_mode=entry_mode,
            actor="medical_manager_test",
            idempotency_key=key,
        )

    def test_project_creation_bootstraps_and_replays_the_selected_authoring_mode(self) -> None:
        for entry_mode, journey_mode in (
            ("from_zero", "guided_greenfield"),
            ("synopsis_import", "synopsis_import"),
        ):
            with self.subTest(entry_mode=entry_mode):
                request = self._request(entry_mode, f"bootstrap-{entry_mode}")
                created = app_main.create_project(request)
                replayed = app_main.create_project(request)

                project_id = created["project"]["project_id"]
                self.assertEqual(project_id, replayed["project"]["project_id"])
                self.assertEqual(entry_mode, created["entry_mode"])
                self.assertEqual(journey_mode, created["authoring_journey"]["entry_mode"])
                self.assertEqual(
                    created["authoring_journey"]["journey_id"],
                    replayed["authoring_journey"]["journey_id"],
                )
                journey = self.journeys.get(project_id)
                self.assertEqual(journey_mode, journey.entry_mode)
                self.assertEqual("类风湿关节炎", journey.framing.indication)
                self.assertEqual("RA-01", journey.framing.investigational_product)
                self.assertFalse(journey.framing_complete)

    def test_user_created_project_without_journey_cannot_bypass_authoring_gate(self) -> None:
        record = self.user_projects.create(
            self._request("from_zero", "orphan-user-project")
        )
        request = MedicalWritingGreenfieldCreateRequest(
            protocol_id=record.protocol_id,
            version=record.protocol_version,
            document_title=record.project_name,
            indication=record.indication,
            study_phase=record.study_phase,
            sections=[
                MedicalWritingGreenfieldSectionSeed(
                    section_key="study_design",
                    heading="研究设计",
                    ich_m11_anchor="C.3 Trial Design",
                    initial_text="待两阶段研究设计确认后生成。",
                    source_fact_ids=["unbound.project.fact"],
                )
            ],
            actor="medical_manager_test",
            idempotency_key="orphan-greenfield-document",
        )

        with self.assertRaises(HTTPException) as caught:
            app_main.create_medical_writing_greenfield_document(
                record.project_id,
                request,
            )

        self.assertEqual(422, caught.exception.status_code)
        self.assertIn("require an authoring journey", caught.exception.detail)

    def test_minimal_ai_first_creation_derives_identity_without_reasking_user(self) -> None:
        request = UserProjectCreateRequest(
            indication="类风湿关节炎",
            product_name="RA-NEW-01",
            study_phase="I期",
            entry_mode="from_zero",
            actor="medical_manager_test",
            idempotency_key="minimal-ai-first-project",
        )

        created = app_main.create_project(request)
        project = created["project"]
        journey = created["authoring_journey"]

        self.assertRegex(project["project_code"], r"^MW-I-[A-F0-9]{8}$")
        self.assertEqual(
            "RA-NEW-01用于治疗类风湿关节炎的I期临床研究",
            project["project_name"],
        )
        self.assertEqual(
            f"{project['project_code']}-DRAFT",
            project["protocol_id"],
        )
        self.assertEqual("RA-NEW-01", journey["framing"]["investigational_product"])
        self.assertEqual("类风湿关节炎", journey["framing"]["indication"])
        self.assertEqual("I期", journey["framing"]["study_phase"])
        packet = journey["framing"]["minimum_product_fact_packet"]
        self.assertEqual("not_provided", packet["ib_status"])
        self.assertEqual("sufficient_for_research", packet["status"])
        self.assertTrue(packet["safe_to_start_competitor_research"])
        self.assertFalse(packet["safe_to_generate_protocol_candidates"])
        self.assertIn(
            "product_profile.technology_type",
            packet["unresolved_high_impact_fields"],
        )
        facts = {
            item["field_path"]: item
            for item in journey["framing"]["product_profile"]["evidence_facts"]
        }
        self.assertEqual(
            "user_provided", facts["framing.investigational_product"]["evidence_status"]
        )
        self.assertTrue(
            facts["framing.investigational_product"]["user_confirmed"]
        )

    def test_legacy_phase_token_is_normalized_before_identity_bootstrap(self) -> None:
        request = UserProjectCreateRequest(
            indication="类风湿关节炎",
            product_name="RA-LEGACY-01",
            study_phase="I",
            entry_mode="from_zero",
            actor="medical_manager_test",
            idempotency_key="legacy-phase-project",
        )

        created = app_main.create_project(request)

        self.assertEqual("I期", created["project"]["study_phase"])
        self.assertEqual("I期", created["authoring_journey"]["framing"]["study_phase"])
        self.assertIn("I期临床研究", created["project"]["project_name"])


if __name__ == "__main__":
    unittest.main()
