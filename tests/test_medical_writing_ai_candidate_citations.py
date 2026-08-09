from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.workbench_contracts import (
    AiTaskArtifact,
    AiTaskOutputValidationStatus,
    AiTaskRun,
    AiTaskRunStatus,
    AiTaskSourceRef,
    AuditEvent,
    MedicalWritingProjectReference,
    MedicalWritingReferenceImportResult,
    MedicalWritingRevisionApplyRequest,
    RevisionAction,
    RevisionActionRequest,
    RevisionSuggestion,
    RevisionThread,
)
from services.api.app.ai_task_runner import (
    AiTaskRunner,
    AiTaskStore,
    validate_medical_writing_candidate_citations,
)
from services.api.app.ai_gateway import AiTaskType
from services.api.app.demo_repository import DemoRepository
from services.api.app.medical_writing import MedicalWritingRevisionService
from services.api.app.medical_writing_document import MedicalWritingDocumentService
from services.api.app.medical_writing_literature import (
    MedicalWritingLiteratureRepository,
)
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app.sqlite_runtime_store import RuntimeStoreError, SqliteRuntimeStore


PROJECT_ID = "proj_rux_03_002"
OTHER_PROJECT_ID = "proj_d001"
REF_A = "mwref_0123456789abcdef0123"
REF_B = "mwref_abcdef0123456789abcd"
REF_C = "mwref_11111111111111111111"
REF_OTHER = "mwref_22222222222222222222"


class MedicalWritingAiCandidateCitationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.documents = MedicalWritingDocumentService()
        self.store = SqliteRuntimeStore(self.root / "runtime.sqlite3")
        self.repo = MedicalWritingRuntimeRepository(self.documents, self.store)
        self.literature = MedicalWritingLiteratureRepository(
            self.root / "medical_writing_literature.sqlite3"
        )
        for index, reference_id in enumerate((REF_A, REF_B, REF_C), start=1):
            self._add_reference(PROJECT_ID, reference_id, index)
        self._add_reference(OTHER_PROJECT_ID, REF_OTHER, 9)
        self.ai_store = AiTaskStore(self.root / "ai_task_runs.jsonl")
        self.runner = AiTaskRunner(
            DemoRepository(Path(__file__).resolve().parents[1] / "demo_data" / "workbench_demo_v0_1.json"),
            self.ai_store,
        )
        self.service = MedicalWritingRevisionService(self.repo, self.runner)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _add_reference(self, project_id: str, reference_id: str, index: int) -> None:
        now = datetime.now(timezone.utc)
        reference = MedicalWritingProjectReference(
            reference_id=reference_id,
            project_id=project_id,
            canonical_key=f"manual:test-reference-{project_id}-{index}",
            source_kind="manual",
            source_input=f"test reference {index}",
            title=f"Test reference {index}",
            year="2026",
            created_at=now,
            updated_at=now,
        )
        self.literature.save_import(
            MedicalWritingReferenceImportResult(
                reference=reference,
                created=True,
                matched_on="reference_id",
            ),
            idempotency_key=f"reference-{project_id}-{index}",
            request_hash=f"hash-{project_id}-{index}",
        )

    @staticmethod
    def _candidate(text: str, bindings=None):
        candidate = {
            "proposal_text": text,
            "diff_patch": f"+ {text}",
            "rationale": "仅使用项目已登记文献。",
            "evidence_span_ids": ["span_001"],
        }
        if bindings is not None:
            candidate["citation_bindings"] = bindings
        return candidate

    @staticmethod
    def _binding(marker_text: str, display_numbers: list[int], reference_ids: list[str]):
        return {
            "marker_text": marker_text,
            "display_numbers": display_numbers,
            "reference_ids": reference_ids,
        }

    def _substantive_target(self):
        document = self.documents.document_session(PROJECT_ID)
        for summary in document.sections:
            section = self.documents.section(PROJECT_ID, summary.section_id)
            for block in section.content_blocks:
                text = str(block.get("text", "")).strip()
                if len(text) >= 40 and block.get("source_locator"):
                    return document, section, block, text[: min(48, len(text))]
        self.fail("no substantive source paragraph found")

    def _store_run(self, proposal_text: str, citation_bindings) -> str:
        run_id = f"airun_citation_{len(self.ai_store.list_runs(PROJECT_ID)) + 1}"
        primary = self._candidate(proposal_text, citation_bindings)
        output = {
            "revision": {
                **primary,
                "alternatives": [
                    self._candidate("无引文候选版本一。", []),
                    self._candidate("无引文候选版本二。", []),
                ],
            }
        }
        now = datetime.now(timezone.utc)
        self.ai_store.append(
            AiTaskRun(
                run_id=run_id,
                project_id=PROJECT_ID,
                module="medical_writing",
                task_type="medical_writing_revision",
                purpose="test",
                status=AiTaskRunStatus.COMPLETED,
                provider="deepseek",
                model_name="deepseek-v4-pro",
                ai_gateway_status="configured",
                request_origin="internal_server_source",
                data_classification="local_private_clinical",
                deployment_profile="local_private_clinical",
                prompt_version="medical_writing_revision_v0_3",
                output_validation_status=AiTaskOutputValidationStatus.PASSED,
                artifacts=[
                    AiTaskArtifact(
                        artifact_id=f"artifact_{run_id}",
                        artifact_type="provider_output",
                        payload=output,
                    )
                ],
                created_at=now,
                updated_at=now,
            )
        )
        return run_id

    def _submit_and_accept(self, proposal_text: str, citation_bindings, suffix: str):
        document, section, block, selected_text = self._substantive_target()
        run_id = self._store_run(proposal_text, citation_bindings)
        suggestion = RevisionSuggestion(
            suggestion_id=f"suggestion_{suffix}",
            proposal_text=proposal_text,
            diff_patch=f"- {selected_text}\n+ {proposal_text}",
            rationale="采用项目文献形成候选。",
            evidence_span_ids=["span_001"],
            ai_run_id=run_id,
        )
        thread = RevisionThread(
            thread_id=f"thread_{suffix}",
            project_id=PROJECT_ID,
            document_id=document.document_id,
            section_id=section.section_id,
            anchor_type="selection",
            anchor_path=block["source_locator"],
            selected_text=selected_text,
            user_instruction="采用项目文献修订。",
            intent="evidence_gap",
            ai_run_id=run_id,
            source_locator=block["source_locator"],
            suggestions=[suggestion],
            status="candidate_ready",
            created_at=datetime.now(timezone.utc),
        )
        self.repo.commit_revision_submission(
            thread,
            AuditEvent(
                audit_id=f"audit_submit_{suffix}",
                project_id=PROJECT_ID,
                actor="medical_manager_test",
                action="medical_writing_revision_submitted",
                target_type="revision_thread",
                target_id=thread.thread_id,
                created_at=datetime.now(timezone.utc),
            ),
        )
        accepted = self.service.apply_action(
            PROJECT_ID,
            thread.thread_id,
            RevisionActionRequest(
                action=RevisionAction.ACCEPT,
                suggestion_id=suggestion.suggestion_id,
                actor="medical_manager_test",
            ),
        )
        return section, accepted.thread

    def test_bare_numeric_citations_are_rejected_in_primary_and_variants(self):
        for marker in ("[99]", "［99］", "[1-3]"):
            with self.subTest(marker=marker):
                output = {
                    "revision": {
                        **self._candidate(f"候选正文{marker}"),
                        "alternatives": [
                            self._candidate("无引文版本。"),
                            self._candidate("另一个无引文版本。"),
                        ],
                    }
                }
                errors = validate_medical_writing_candidate_citations(
                    output, {REF_A, REF_B, REF_C}
                )
                self.assertTrue(any("citation_bindings" in item for item in errors), errors)

        output = {
            "revision": {
                **self._candidate("主候选无引文。"),
                "alternatives": [
                    self._candidate("备选候选含裸引文[99]。"),
                    self._candidate("另一个无引文版本。"),
                ],
            }
        }
        errors = validate_medical_writing_candidate_citations(
            output, {REF_A, REF_B, REF_C}
        )
        self.assertTrue(
            any("revision.alternatives[0]" in item for item in errors), errors
        )

    def test_binding_numbers_order_and_project_reference_identity_are_strict(self):
        text = "证据支持[7]及联合证据[9-10]。"
        valid = [
            self._binding("[7]", [7], [REF_A]),
            self._binding("[9-10]", [9, 10], [REF_B, REF_C]),
        ]
        self.assertEqual(
            [],
            validate_medical_writing_candidate_citations(
                {"revision": {**self._candidate(text, valid), "alternatives": []}},
                {REF_A, REF_B, REF_C},
            ),
        )

        cases = (
            [valid[1], valid[0]],
            [self._binding("[7]", [8], [REF_A]), valid[1]],
            [self._binding("[7]", [7], [REF_OTHER]), valid[1]],
            [self._binding("[7]", [7], [REF_A]), self._binding("[9-10]", [9, 10], [REF_B])],
        )
        for bindings in cases:
            with self.subTest(bindings=bindings):
                errors = validate_medical_writing_candidate_citations(
                    {"revision": {**self._candidate(text, bindings), "alternatives": []}},
                    {REF_A, REF_B, REF_C},
                )
                self.assertTrue(errors)

    def test_ai_task_runner_validation_layer_rejects_unbound_variant_marker(self):
        source = AiTaskSourceRef(
            source_id="source_revision_001",
            source_type="protocol_section_selection",
            title="Current protocol",
            locator="docx:paragraph:1",
            text_preview="本研究拟评价试验药物在目标人群中的有效性和安全性。",
            project_id=PROJECT_ID,
            module="medical_writing",
        )
        primary = self._candidate("本研究拟评价试验药物在目标人群中的有效性和安全性。")
        output = {
            "task_id": "airun_validation",
            "task_type": "medical_writing_revision",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "prompt_version": "medical_writing_revision_v0_3",
            "input_source_ids": [source.source_id],
            "forbidden_source_ids": [],
            "findings": [],
            "evidence_spans": [
                {
                    "span_id": "span_001",
                    "source_id": source.source_id,
                    "locator": source.locator,
                    "quote": source.text_preview,
                }
            ],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "revision": {
                **primary,
                "alternatives": [
                    self._candidate("目标人群中的有效性和安全性将予以评价[99]。"),
                    self._candidate("将评价有效性，并同步评价安全性。"),
                ],
            },
        }
        errors = self.runner._validate_run_output(
            "airun_validation",
            AiTaskType.MEDICAL_WRITING_REVISION,
            output,
            allowed_sources=[source],
            forbidden_source_ids=[],
            expected_provider="deepseek",
            expected_model="deepseek-v4-pro",
            expected_prompt_version="medical_writing_revision_v0_3",
            expected_task_context={},
        )
        self.assertTrue(
            any(
                "revision.alternatives[0].citation_bindings" in error
                for error in errors
            ),
            errors,
        )

    def test_legal_single_and_multi_citations_become_structured_nodes_and_replay_is_idempotent(self):
        proposal = "证据支持[7]及联合证据[9-10]。"
        bindings = [
            self._binding("[7]", [7], [REF_A]),
            self._binding("[9-10]", [9, 10], [REF_B, REF_C]),
        ]
        section, thread = self._submit_and_accept(proposal, bindings, "legal")
        request = MedicalWritingRevisionApplyRequest(
            expected_working_copy_revision=0,
            actor="medical_manager_test",
            idempotency_key="apply-legal-citations",
        )
        first = self.repo.apply_approved_revision_to_working_copy(
            PROJECT_ID, section.section_id, thread.thread_id, request
        )
        replay = self.repo.apply_approved_revision_to_working_copy(
            PROJECT_ID, section.section_id, thread.thread_id, request
        )
        self.assertEqual(first.working_copy.revision, replay.working_copy.revision)
        changed = next(
            block
            for block in first.working_copy.content_blocks
            if block.get("source_locator") == thread.anchor_path
        )
        citation_nodes = []

        def visit(node):
            if not isinstance(node, dict):
                return
            if any(mark.get("type") == "citation" for mark in node.get("marks", [])):
                citation_nodes.append(node)
            for child in node.get("content", []):
                visit(child)

        visit(changed["rich_text"])
        self.assertEqual(2, len(citation_nodes))
        self.assertEqual(
            {"referenceId": REF_A}, citation_nodes[0]["marks"][-1]["attrs"]
        )
        self.assertEqual(
            {"referenceIds": [REF_B, REF_C]},
            citation_nodes[1]["marks"][-1]["attrs"],
        )
        self.assertNotEqual("[7]", citation_nodes[0]["text"])
        self.assertNotEqual("[9-10]", citation_nodes[1]["text"])
        self.assertEqual(
            changed["text"], self.repo._rich_text_plain_text(changed["rich_text"])
        )
        replay_nodes = []

        def collect(node):
            if not isinstance(node, dict):
                return
            replay_nodes.extend(
                mark for mark in node.get("marks", []) if mark.get("type") == "citation"
            )
            for child in node.get("content", []):
                collect(child)

        changed_replay = next(
            block
            for block in replay.working_copy.content_blocks
            if block.get("source_locator") == thread.anchor_path
        )
        collect(changed_replay["rich_text"])
        self.assertEqual(2, len(replay_nodes))

    def test_table_cell_rich_text_replacement_preserves_container_and_cell_scope(self):
        rich_text = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "attrs": {"stylePreset": "body"},
                    "content": [
                        {
                            "type": "text",
                            "text": "原始单元格文字",
                            "marks": [{"type": "bold"}],
                        }
                    ],
                }
            ],
        }
        display_text, updated = self.repo._replace_in_rich_text_with_citations(
            rich_text,
            "原始单元格文字",
            "单元格证据[7]。",
            [self._binding("[7]", [7], [REF_A])],
        )
        self.assertEqual("doc", updated["type"])
        self.assertEqual("paragraph", updated["content"][0]["type"])
        self.assertEqual(display_text, self.repo._rich_text_plain_text(updated))
        self.assertEqual(
            {"referenceId": REF_A},
            updated["content"][0]["content"][1]["marks"][-1]["attrs"],
        )
        self.assertEqual(
            {"type": "bold"}, updated["content"][0]["content"][0]["marks"][0]
        )

    def test_cross_project_accept_and_missing_reference_apply_fail_without_partial_writes(self):
        proposal = "跨项目引文[7]。"
        cross_binding = [self._binding("[7]", [7], [REF_OTHER])]
        before_events = self.store.workflow_audit_events(
            PROJECT_ID, "medical_writing_revision"
        )
        with self.assertRaisesRegex(ValueError, "current project"):
            self._submit_and_accept(proposal, cross_binding, "cross_project")
        after_events = self.store.workflow_audit_events(
            PROJECT_ID, "medical_writing_revision"
        )
        self.assertEqual(len(before_events) + 1, len(after_events))
        self.assertFalse(
            any(event.action == "medical_writing_revision_accept" for event in after_events)
        )

        section, thread = self._submit_and_accept(
            "有效引文[7]。",
            [self._binding("[7]", [7], [REF_A])],
            "removed_reference",
        )
        with sqlite3.connect(self.root / "medical_writing_literature.sqlite3") as connection:
            connection.execute(
                "DELETE FROM medical_writing_literature_references WHERE project_id=? AND reference_id=?",
                (PROJECT_ID, REF_A),
            )
        before_copy = self.repo.working_copy(PROJECT_ID, section.section_id)
        before_apply_events = self.store.workflow_audit_events(
            PROJECT_ID, "medical_writing_working_copy"
        )
        with self.assertRaisesRegex(RuntimeStoreError, "current project"):
            self.repo.apply_approved_revision_to_working_copy(
                PROJECT_ID,
                section.section_id,
                thread.thread_id,
                MedicalWritingRevisionApplyRequest(
                    expected_working_copy_revision=0,
                    actor="medical_manager_test",
                    idempotency_key="apply-missing-reference",
                ),
            )
        after_copy = self.repo.working_copy(PROJECT_ID, section.section_id)
        after_apply_events = self.store.workflow_audit_events(
            PROJECT_ID, "medical_writing_working_copy"
        )
        self.assertEqual(before_copy.revision, after_copy.revision)
        self.assertEqual(before_copy.content_blocks, after_copy.content_blocks)
        self.assertEqual(
            before_copy.applied_revision_thread_ids,
            after_copy.applied_revision_thread_ids,
        )
        self.assertEqual(before_apply_events, after_apply_events)

    def test_candidate_without_citations_remains_backward_compatible(self):
        output = {
            "revision": {
                **self._candidate("候选正文不含文献引文。"),
                "alternatives": [
                    self._candidate("无引文版本一。"),
                    self._candidate("无引文版本二。"),
                ],
            }
        }
        self.assertEqual(
            [],
            validate_medical_writing_candidate_citations(
                output, {REF_A, REF_B, REF_C}
            ),
        )


if __name__ == "__main__":
    unittest.main()
