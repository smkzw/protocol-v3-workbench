from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from docx import Document

from packages.contracts.workbench_contracts import (
    MedicalWritingGreenfieldCreateRequest,
    MedicalWritingGreenfieldSectionSeed,
    MedicalWritingTemplateUpgradeApplyRequest,
    MedicalWritingTemplateUpgradeRollbackRequest,
    MedicalWritingWorkingCopySaveRequest,
)
from services.api.app.medical_writing_company_corpus import (
    MedicalWritingCompanyCorpusService,
)
from services.api.app.medical_writing_document import MedicalWritingDocumentService
from services.api.app.medical_writing_document_exporter import (
    export_medical_writing_document_docx,
)
from services.api.app.medical_writing_greenfield import (
    CompositeMedicalWritingDocumentService,
    GreenfieldMedicalWritingConflictError,
    GreenfieldMedicalWritingDocumentService,
)
from services.api.app.medical_writing_protocol_template import (
    M11_TEMPLATE_ID,
    M11_TEMPLATE_VERSION,
    MedicalWritingProtocolTemplateService,
)
from services.api.app.medical_writing_repository import (
    MedicalWritingRuntimeRepository,
)
from services.api.app.medical_writing_style_profile import (
    MedicalWritingStyleProfileService,
)
from services.api.app.medical_writing_template_upgrade import (
    MedicalWritingTemplateUpgradeService,
)
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore


LEGACY_SECTIONS = [
    ("synopsis", "方案摘要", "", "B Protocol Synopsis"),
    ("introduction", "研究背景与依据", "", "C.2 Background and Rationale"),
    ("disease_background", "疾病背景", "introduction", "C.2.1 Disease Background"),
    ("study_rationale", "研究依据", "introduction", "C.2.2 Trial Rationale"),
    ("objectives_endpoints", "研究目的与终点", "", "C.3 Objectives and Endpoints"),
    ("study_design", "研究设计", "", "C.4 Trial Design"),
    ("population", "研究人群", "", "C.5 Trial Population"),
    ("intervention", "研究治疗", "", "C.6 Trial Intervention"),
    ("assessments", "研究评估和程序", "", "C.7 Trial Assessments and Procedures"),
    (
        "schedule_of_activities",
        "研究流程表",
        "assessments",
        "C.7.1 Schedule of Activities",
    ),
    ("safety", "安全性评估", "", "C.8 Safety"),
    ("statistics", "统计学考虑", "", "C.9 Statistical Considerations"),
    ("ethics", "伦理与监管", "", "C.10 Ethics and Regulatory"),
    ("references", "参考文献", "", "References"),
]


def legacy_request() -> MedicalWritingGreenfieldCreateRequest:
    return MedicalWritingGreenfieldCreateRequest(
        protocol_id="LEGACY-RA-001",
        version="V0.1",
        document_title="旧版RA研究方案",
        indication="类风湿关节炎",
        study_phase="II期",
        sections=[
            MedicalWritingGreenfieldSectionSeed(
                section_key=key,
                heading=heading,
                parent_key=parent,
                ich_m11_anchor=anchor,
                initial_text=(
                    "随机、双盲、安慰剂对照、多中心II期研究。"
                    if key == "study_design"
                    else ""
                ),
            )
            for key, heading, parent, anchor in LEGACY_SECTIONS
        ],
        actor="medical_manager",
        idempotency_key="create-legacy-ra",
    )


class MedicalWritingTemplateUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.greenfield = GreenfieldMedicalWritingDocumentService(
            root / "greenfield.sqlite3"
        )
        self.created = self.greenfield.create("proj_legacy_ra", legacy_request())
        self.runtime_store = SqliteRuntimeStore(root / "runtime.sqlite3")
        self.documents = CompositeMedicalWritingDocumentService(
            MedicalWritingDocumentService(),
            self.greenfield,
        )
        self.repository = MedicalWritingRuntimeRepository(
            self.documents,
            self.runtime_store,
        )
        self.service = MedicalWritingTemplateUpgradeService(
            self.greenfield,
            self.runtime_store,
            MedicalWritingProtocolTemplateService(),
            MedicalWritingStyleProfileService(),
            MedicalWritingCompanyCorpusService(),
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def save_synopsis(self, text: str, *, expected_revision: int = 0, key: str = "save"):
        session = self.documents.document_session("proj_legacy_ra")
        source = self.documents.section("proj_legacy_ra", session.sections[0].section_id)
        current = self.repository.working_copy("proj_legacy_ra", source.section_id)
        blocks = [dict(block) for block in current.content_blocks]
        blocks[1] = dict(blocks[1])
        blocks[1]["text"] = text
        return self.repository.save_working_copy(
            "proj_legacy_ra",
            source.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=session.document_id,
                expected_revision=expected_revision,
                content_blocks=blocks,
                actor="medical_manager",
                idempotency_key=key,
            ),
        )

    def apply_request(self, preview, *, key: str = "upgrade"):
        return MedicalWritingTemplateUpgradeApplyRequest(
            expected_baseline_revision=preview.current_baseline_revision,
            expected_baseline_sha256=preview.current_baseline_sha256,
            expected_preview_sha256=preview.preview_sha256,
            target_template_id=preview.target_template_id,
            target_template_version=preview.target_template_version,
            target_template_definition_sha256=preview.target_template_definition_sha256,
            acknowledge_consolidation=True,
            acknowledge_approval_reset=True,
            actor="medical_manager",
            idempotency_key=key,
        )

    def test_preview_maps_all_legacy_sections_and_binds_working_copy_state(self):
        self.save_synopsis("这是医学经理保存的旧版方案摘要。")

        preview = self.service.preview("proj_legacy_ra")

        self.assertTrue(preview.can_apply)
        self.assertEqual(14, preview.source_section_count)
        self.assertEqual(160, preview.target_section_count)
        self.assertEqual(14, preview.mapped_source_section_count)
        self.assertEqual([], preview.unmapped_source_section_ids)
        self.assertEqual(["ich_m11_2"], preview.consolidation_target_node_ids)
        synopsis = next(
            item for item in preview.mappings if item.source_section_key == "synopsis"
        )
        self.assertEqual("working_copy", synopsis.source_content_origin)
        self.assertEqual(1, synopsis.source_content_revision)
        self.assertEqual("ich_m11_1_1", synopsis.target_template_node_id)
        self.assertEqual(1, preview.working_copy_count)

    def test_apply_creates_new_160_node_document_preserves_content_and_can_rollback(self):
        saved = self.save_synopsis("这是医学经理保存的旧版方案摘要。")
        old_document_id = self.created.document.document_id
        old_section_id = saved.section_id
        preview = self.service.preview("proj_legacy_ra")

        applied = self.service.apply(
            "proj_legacy_ra",
            self.apply_request(preview),
        )

        self.assertNotEqual(old_document_id, applied.document.document_id)
        self.assertEqual(M11_TEMPLATE_ID, applied.document.template_id)
        self.assertEqual(M11_TEMPLATE_VERSION, applied.document.template_version)
        self.assertEqual(160, applied.target_section_count)
        upgraded = self.greenfield.document_for_revision("proj_legacy_ra")
        synopsis = next(
            section
            for section in upgraded.sections
            if section.template_node_id == "ich_m11_1_1"
        )
        self.assertIn(
            "这是医学经理保存的旧版方案摘要。",
            [str(block.get("text") or "") for block in synopsis.content_blocks],
        )
        self.assertEqual("template_upgrade_candidate", upgraded.status)
        self.assertEqual(
            1,
            self.runtime_store.medical_writing_working_copy(
                "proj_legacy_ra",
                old_document_id,
                old_section_id,
            ).revision,
        )
        exported = export_medical_writing_document_docx(
            self.repository.assemble_document_for_export(
                "proj_legacy_ra",
                "draft_preview",
            ),
            mode="draft_preview",
        )
        text = "\n".join(
            paragraph.text for paragraph in Document(io.BytesIO(exported.content)).paragraphs
        )
        self.assertIn("这是医学经理保存的旧版方案摘要。", text)

        replay = self.service.apply("proj_legacy_ra", self.apply_request(preview))
        self.assertEqual(applied.migration_event_id, replay.migration_event_id)
        rolled_back = self.service.rollback(
            "proj_legacy_ra",
            MedicalWritingTemplateUpgradeRollbackRequest(
                migration_event_id=applied.migration_event_id,
                expected_baseline_revision=applied.baseline_revision,
                expected_baseline_sha256=applied.baseline_sha256,
                actor="medical_manager",
                idempotency_key="rollback-upgrade",
            ),
        )
        self.assertEqual(old_document_id, rolled_back.restored_document.document_id)
        self.assertEqual(
            1,
            self.repository.working_copy("proj_legacy_ra", old_section_id).revision,
        )
        rollback_replay = self.service.rollback(
            "proj_legacy_ra",
            MedicalWritingTemplateUpgradeRollbackRequest(
                migration_event_id=applied.migration_event_id,
                expected_baseline_revision=applied.baseline_revision,
                expected_baseline_sha256=applied.baseline_sha256,
                actor="medical_manager",
                idempotency_key="rollback-upgrade",
            ),
        )
        self.assertEqual(rolled_back.rollback_event_id, rollback_replay.rollback_event_id)

    def test_preview_becomes_stale_when_working_copy_changes(self):
        self.save_synopsis("第一版旧方案摘要。")
        preview = self.service.preview("proj_legacy_ra")
        self.save_synopsis("第二版旧方案摘要。", expected_revision=1, key="save-r2")

        with self.assertRaisesRegex(
            GreenfieldMedicalWritingConflictError,
            "preview is stale",
        ):
            self.service.apply("proj_legacy_ra", self.apply_request(preview))

    def test_rollback_blocks_after_upgraded_document_has_a_saved_working_copy(self):
        preview = self.service.preview("proj_legacy_ra")
        applied = self.service.apply(
            "proj_legacy_ra",
            self.apply_request(preview, key="upgrade-for-edit"),
        )
        new_session = self.documents.document_session("proj_legacy_ra")
        target = next(
            section
            for section in new_session.sections
            if section.template_node_id == "ich_m11_1_1"
        )
        current = self.repository.working_copy("proj_legacy_ra", target.section_id)
        self.repository.save_working_copy(
            "proj_legacy_ra",
            target.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=new_session.document_id,
                expected_revision=0,
                content_blocks=current.content_blocks,
                actor="medical_manager",
                idempotency_key="save-after-upgrade",
            ),
        )

        with self.assertRaisesRegex(ValueError, "blocked after"):
            self.service.rollback(
                "proj_legacy_ra",
                MedicalWritingTemplateUpgradeRollbackRequest(
                    migration_event_id=applied.migration_event_id,
                    expected_baseline_revision=applied.baseline_revision,
                    expected_baseline_sha256=applied.baseline_sha256,
                    actor="medical_manager",
                    idempotency_key="unsafe-rollback",
                ),
            )

    def test_current_template_document_is_not_offered_an_upgrade(self):
        preview = self.service.preview("proj_legacy_ra")
        self.service.apply("proj_legacy_ra", self.apply_request(preview))

        current = self.service.preview("proj_legacy_ra")

        self.assertFalse(current.can_apply)
        self.assertTrue(any("仅旧绿地" in blocker for blocker in current.blockers))


if __name__ == "__main__":
    unittest.main()
