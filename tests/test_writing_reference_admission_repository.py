from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.workbench_contracts import (
    WritingReferenceDocumentArtifact,
    WritingReferenceDocumentValidationCheck,
    WritingReferenceDocumentValidationRecord,
    WritingReferenceExtractedSpan,
    WritingReferenceExtractionResult,
    WritingReferenceTranslationRevision,
)
from services.api.app.writing_reference_repository import (
    WritingReferenceConflictError,
    WritingReferenceRepository,
    WritingReferenceStaleStateError,
)
from tests.test_writing_reference_repository import PROJECT_ID, snapshot


NOW = datetime(2026, 7, 12, 5, 0, tzinfo=timezone.utc)


class WritingReferenceAdmissionRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "writing_reference.sqlite3"
        self.repo = WritingReferenceRepository(self.path)
        self.repo.save_search_snapshot(snapshot(), idempotency_key="search-001")
        self.artifact = WritingReferenceDocumentArtifact(
            artifact_id="wref_doc_001",
            project_id=PROJECT_ID,
            snapshot_id="wref_search_001",
            nct_id="NCT05014438",
            source_document_id="ctgov_NCT05014438_000",
            document_type="protocol_sap",
            filename="Prot_SAP_000.pdf",
            requested_url="https://clinicaltrials.gov/ProvidedDocs/38/NCT05014438/Prot_SAP_000.pdf",
            final_url="https://clinicaltrials.gov/ProvidedDocs/38/NCT05014438/Prot_SAP_000.pdf",
            content_type="application/pdf",
            actual_size=13,
            content_sha256="a" * 64,
            created_by="medical_manager",
            created_at=NOW,
        )
        self.repo.save_document_artifact(
            self.artifact,
            storage_relpath="safe/wref_doc_001/a.pdf",
            idempotency_key="artifact-001",
        )
        self.span = WritingReferenceExtractedSpan(
            span_id="wref_span_001",
            project_id=PROJECT_ID,
            artifact_id=self.artifact.artifact_id,
            extraction_revision="pymupdf_1.26.5_aaaaaaaaaaaaaaaa",
            physical_page=12,
            block_index=4,
            source_locator="ctgov:NCT05014438:wref_doc_001:p12:b4",
            section_heading="Study Objectives and Endpoints",
            ich_m11_anchor="objectives_endpoints",
            source_text="Participants must not receive SCS within 14 days.",
            source_text_sha256="b" * 64,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _approve_extraction(self, *, key: str) -> None:
        self.repo.record_extraction_review(
            project_id=PROJECT_ID,
            artifact_id=self.artifact.artifact_id,
            extraction_revision=self.span.extraction_revision,
            decision="approved",
            confirmed_anchor_coverage=[self.span.ich_m11_anchor],
            unresolved_structure_issues=[],
            comment="已核对原文页码、章节标题与M11结构映射，当前抽取可进入翻译审核。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key=key,
        )

    def _prepare_admissible_translation(self) -> WritingReferenceTranslationRevision:
        self.repo.save_extraction(
            WritingReferenceExtractionResult(
                artifact_id=self.artifact.artifact_id,
                project_id=PROJECT_ID,
                extraction_revision=self.span.extraction_revision,
                parser_name="PyMuPDF",
                parser_version="1.26.5",
                page_count=20,
                status="pending_visual_and_medical_structure_review",
                spans=[self.span],
            ),
            idempotency_key="extract-prerequisite",
        )
        self._approve_extraction(key="structure-review-prerequisite")
        self.repo.save_document_validation(
            WritingReferenceDocumentValidationRecord(
                validation_id="wref_validation_prerequisite",
                project_id=PROJECT_ID,
                artifact_id=self.artifact.artifact_id,
                revision=1,
                status="confirmed",
                document_sha256=self.artifact.content_sha256,
                expected_context_hash="c" * 64,
                validator_version="content_consistency_v2",
                checks=[
                    WritingReferenceDocumentValidationCheck(
                        check_code="document_type",
                        label="文件类型",
                        expected_value="protocol_sap",
                        observed_value="Protocol/SAP",
                        outcome="match",
                    )
                ],
                summary="文件内容与当前任务一致。",
                actor="system_validator",
                created_at=NOW,
            ),
            expected_revision=0,
            idempotency_key="validation-prerequisite",
        )
        translation = WritingReferenceTranslationRevision(
            translation_id="wref_translation_prerequisite",
            project_id=PROJECT_ID,
            span_id=self.span.span_id,
            source_span_revision=f"{self.span.span_id}_r1",
            document_sha256=self.artifact.content_sha256,
            glossary_version="cms_regulatory_zh_v1",
            revision=1,
            translated_text="受试者在14天内不得接受SCS。",
            rationale="保留缩写、时间窗和否定含义。",
            fidelity_status="passed",
            ai_run_id="airun_translation_prerequisite",
            created_at=NOW,
        )
        return self.repo.save_translation(
            translation,
            idempotency_key="translation-prerequisite",
        )

    def test_extraction_translation_review_and_admission_survive_restart(self) -> None:
        extraction = WritingReferenceExtractionResult(
            artifact_id=self.artifact.artifact_id,
            project_id=PROJECT_ID,
            extraction_revision=self.span.extraction_revision,
            parser_name="PyMuPDF",
            parser_version="1.26.5",
            page_count=20,
            status="pending_visual_and_medical_structure_review",
            spans=[self.span],
        )
        self.repo.save_extraction(extraction, idempotency_key="extract-001")
        self._approve_extraction(key="structure-review-001")
        self.repo.save_document_validation(
            WritingReferenceDocumentValidationRecord(
                validation_id="wref_validation_001",
                project_id=PROJECT_ID,
                artifact_id=self.artifact.artifact_id,
                revision=1,
                status="confirmed",
                document_sha256=self.artifact.content_sha256,
                expected_context_hash="c" * 64,
                validator_version="content_consistency_v2",
                checks=[
                    WritingReferenceDocumentValidationCheck(
                        check_code="document_type",
                        label="文件类型",
                        expected_value="protocol_sap",
                        observed_value="Protocol/SAP",
                        outcome="match",
                    )
                ],
                summary="文件内容与当前任务一致。",
                actor="system_validator",
                created_at=NOW,
            ),
            expected_revision=0,
            idempotency_key="validation-001",
        )

        translation = WritingReferenceTranslationRevision(
            translation_id="wref_translation_001",
            project_id=PROJECT_ID,
            span_id=self.span.span_id,
            source_span_revision=f"{self.span.span_id}_r1",
            document_sha256=self.artifact.content_sha256,
            glossary_version="cms_regulatory_zh_v1",
            revision=1,
            translated_text="受试者在14天内不得接受SCS。",
            rationale="保留缩写、时间窗和否定含义。",
            fidelity_status="passed",
            ai_run_id="airun_translation_001",
            created_at=NOW,
        )
        self.repo.save_translation(translation, idempotency_key="translation-001")
        review = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            translation_revision=1,
            decision="approved",
            comment="译文与原文医学含义一致，可作为写作参照。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="medical-review-001",
        )
        directly_admitted = self.repo.evidence_briefs(PROJECT_ID)
        self.assertEqual("author_confirmation", review.decision_type)
        self.assertEqual("admitted", review.admission_status)
        self.assertEqual([review.evidence_brief_id], [item.brief_id for item in directly_admitted])
        self.assertEqual(
            "medical_author_confirmation",
            directly_admitted[0].confirmation_type,
        )
        brief = self.repo.admit_translation(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            expected_translation_revision=1,
            medical_review_id=review.review_id,
            idempotency_key="admission-001",
        )
        replay = self.repo.admit_translation(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            expected_translation_revision=1,
            medical_review_id=review.review_id,
            idempotency_key="admission-001",
        )

        self.assertEqual("approved_current", brief.status)
        self.assertEqual(brief.model_dump(), replay.model_dump())
        restarted = WritingReferenceRepository(self.path)
        briefs = restarted.evidence_briefs(
            PROJECT_ID,
            ich_m11_anchor="objectives_endpoints",
        )
        self.assertEqual([brief.model_dump()], [item.model_dump() for item in briefs])
        self.assertEqual([], restarted.verify_audit_chain(PROJECT_ID))

        invalidated = restarted.invalidate_artifact(
            project_id=PROJECT_ID,
            artifact_id=self.artifact.artifact_id,
            reason="ClinicalTrials.gov published a replacement document version.",
            actor="system_version_monitor",
            expected_revision=1,
            idempotency_key="invalidate-001",
        )
        self.assertFalse(invalidated["source_current"])
        self.assertEqual([], restarted.evidence_briefs(PROJECT_ID, ich_m11_anchor="objectives_endpoints"))
        projected_artifact = restarted.document_artifact(PROJECT_ID, self.artifact.artifact_id)
        self.assertFalse(projected_artifact.source_current)
        self.assertEqual(2, projected_artifact.state_revision)
        self.assertEqual(
            "ClinicalTrials.gov published a replacement document version.",
            projected_artifact.invalidation_reason,
        )
        review_projection = restarted.medical_reviews(PROJECT_ID)
        self.assertEqual([review.model_dump()], [item.model_dump() for item in review_projection])
        evidence_history = restarted.evidence_brief_history(PROJECT_ID)
        self.assertEqual(1, len(evidence_history))
        self.assertEqual("invalidated_source", evidence_history[0].status)
        replayed = restarted.invalidate_artifact(
            project_id=PROJECT_ID,
            artifact_id=self.artifact.artifact_id,
            reason="ClinicalTrials.gov published a replacement document version.",
            actor="system_version_monitor",
            expected_revision=1,
            idempotency_key="invalidate-001",
        )
        self.assertTrue(replayed["replayed"])
        self.assertEqual([], restarted.verify_audit_chain(PROJECT_ID))

    def test_failed_fidelity_or_unapproved_review_cannot_enter_evidence_brief(self) -> None:
        unapproved = self._prepare_admissible_translation()
        with self.assertRaises(KeyError):
            self.repo.admit_translation(
                project_id=PROJECT_ID,
                translation_id=unapproved.translation_id,
                expected_translation_revision=unapproved.revision,
                medical_review_id="missing",
                idempotency_key="admission-unapproved",
            )

        blocked = unapproved.model_copy(
            update={
                "translation_id": "wref_translation_fidelity_blocked",
                "translated_text": "受试者在7天内可以接受SCS。",
                "fidelity_status": "blocked",
                "fidelity_failure_codes": [
                    "numeric_tokens_changed",
                    "negation_signal_missing",
                ],
                "ai_run_id": "airun_translation_fidelity_blocked",
            }
        )
        blocked = self.repo.save_translation(
            blocked,
            idempotency_key="translation-fidelity-blocked",
        )
        with self.assertRaisesRegex(ValueError, "not eligible"):
            self.repo.record_medical_review(
                project_id=PROJECT_ID,
                translation_id=blocked.translation_id,
                translation_revision=blocked.revision,
                decision="approved",
                comment="忠实度阻断时作者确认与准入必须整体回滚。",
                actor="medical_manager",
                expected_revision=0,
                idempotency_key="review-fidelity-blocked",
            )
        with self.assertRaises(KeyError):
            self.repo.current_medical_review(
                PROJECT_ID,
                blocked.translation_id,
                blocked.revision,
            )
        self.assertEqual([], self.repo.evidence_briefs(PROJECT_ID))

    def test_legacy_pending_medical_approval_is_readable_and_author_confirmable(self) -> None:
        current = self._prepare_admissible_translation()
        legacy = current.model_copy(
            update={
                "translation_id": "wref_translation_legacy_pending",
                "status": "pending_medical_approval",
                "ai_run_id": "airun_translation_legacy_pending",
            }
        )
        self.repo.save_translation(
            legacy,
            idempotency_key="translation-legacy-pending",
        )
        projected = next(
            item
            for item in self.repo.translations(PROJECT_ID)
            if item.translation_id == legacy.translation_id
        )
        self.assertEqual("pending_medical_approval", projected.status)

        confirmation = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=legacy.translation_id,
            translation_revision=legacy.revision,
            decision="approved",
            comment="历史待批准状态按兼容语义由当前医学作者确认并直接准入。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="confirm-legacy-pending",
        )
        self.assertEqual("author_confirmation", confirmation.decision_type)
        self.assertEqual("admitted", confirmation.admission_status)
        self.assertEqual(
            [confirmation.evidence_brief_id],
            [
                item.brief_id
                for item in self.repo.evidence_briefs(PROJECT_ID)
                if item.translation_id == legacy.translation_id
            ],
        )

    def test_legacy_approved_without_admission_requires_current_author_confirmation_and_preserves_history(self) -> None:
        translation = self._prepare_admissible_translation()
        legacy_review_id = "wref_review_legacy_approved_not_admitted"
        legacy_payload = {
            "review_id": legacy_review_id,
            "project_id": PROJECT_ID,
            "translation_id": translation.translation_id,
            "translation_revision": translation.revision,
            "decision": "approved",
            "comment": "历史医学审核已批准，但当时尚未建立语料准入记录。",
            "actor": "medical_manager",
            "revision": 1,
            "created_at": NOW.isoformat(),
        }
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO writing_reference_medical_review_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "kangzhe_local",
                    PROJECT_ID,
                    legacy_review_id,
                    translation.translation_id,
                    translation.revision,
                    1,
                    "approved",
                    json.dumps(legacy_payload, ensure_ascii=False),
                    NOW.isoformat(),
                ),
            )
            connection.execute(
                "INSERT INTO writing_reference_medical_review_state VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "kangzhe_local",
                    PROJECT_ID,
                    translation.translation_id,
                    translation.revision,
                    1,
                    legacy_review_id,
                    "approved",
                    NOW.isoformat(),
                ),
            )
            connection.commit()

        legacy = self.repo.current_medical_review(
            PROJECT_ID,
            translation.translation_id,
            translation.revision,
        )
        self.assertEqual("legacy_medical_review", legacy.decision_type)
        self.assertEqual("not_admitted", legacy.admission_status)
        self.assertEqual([], self.repo.evidence_briefs(PROJECT_ID))

        confirmed = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            translation_revision=translation.revision,
            decision="approved",
            comment="医学作者已对照当前原文、译文与来源版本完成确认并准入。",
            actor="medical_manager",
            expected_revision=legacy.revision,
            idempotency_key="migrate-legacy-approved-not-admitted",
        )

        self.assertEqual("author_confirmation", confirmed.decision_type)
        self.assertEqual("admitted", confirmed.admission_status)
        self.assertEqual(
            "legacy_medical_review",
            self.repo.medical_review(PROJECT_ID, legacy_review_id).decision_type,
        )
        self.assertEqual(
            confirmed.review_id,
            self.repo.current_medical_review(
                PROJECT_ID,
                translation.translation_id,
                translation.revision,
            ).review_id,
        )
        self.assertEqual(
            [confirmed.evidence_brief_id],
            [item.brief_id for item in self.repo.evidence_briefs(PROJECT_ID)],
        )
        with sqlite3.connect(self.path) as connection:
            migration_events = connection.execute(
                "SELECT COUNT(*) FROM writing_reference_audit_chain "
                "WHERE project_id=? AND event_type='legacy_translation_author_confirmation_migrated'",
                (PROJECT_ID,),
            ).fetchone()[0]
            legacy_rows = connection.execute(
                "SELECT COUNT(*) FROM writing_reference_medical_review_records "
                "WHERE project_id=? AND translation_id=?",
                (PROJECT_ID, translation.translation_id),
            ).fetchone()[0]
        self.assertEqual(1, migration_events)
        self.assertEqual(2, legacy_rows)
        self.assertEqual([], self.repo.verify_audit_chain(PROJECT_ID))

    def test_return_or_reject_of_non_current_translation_revision_is_rejected_without_audit_write(self) -> None:
        first = self._prepare_admissible_translation()
        returned = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=first.translation_id,
            translation_revision=first.revision,
            decision="returned",
            comment="先退回第一版以生成第二版译文。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="return-first-before-revision",
        )
        second = self.repo.save_translation(
            first.model_copy(
                update={
                    "revision": 2,
                    "translated_text": "受试者不得在14天内接受SCS。",
                    "ai_run_id": "airun_translation_prerequisite_r2",
                    "created_at": NOW,
                }
            ),
            expected_revision=1,
            required_current_medical_review_id=returned.review_id,
            idempotency_key="save-second-translation-revision",
        )
        self.assertEqual(2, second.revision)

        with sqlite3.connect(self.path) as connection:
            before_reviews = connection.execute(
                "SELECT COUNT(*) FROM writing_reference_medical_review_records "
                "WHERE project_id=? AND translation_id=?",
                (PROJECT_ID, first.translation_id),
            ).fetchone()[0]
            before_audits = connection.execute(
                "SELECT COUNT(*) FROM writing_reference_audit_chain WHERE project_id=?",
                (PROJECT_ID,),
            ).fetchone()[0]

        for decision in ("returned", "rejected"):
            with self.subTest(decision=decision):
                with self.assertRaisesRegex(
                    WritingReferenceStaleStateError,
                    "no longer current",
                ):
                    self.repo.record_medical_review(
                        project_id=PROJECT_ID,
                        translation_id=first.translation_id,
                        translation_revision=first.revision,
                        decision=decision,
                        comment=f"不得对历史第一版执行{decision}。",
                        actor="medical_manager",
                        expected_revision=returned.revision,
                        idempotency_key=f"reject-stale-translation-{decision}",
                    )

        with sqlite3.connect(self.path) as connection:
            after_reviews = connection.execute(
                "SELECT COUNT(*) FROM writing_reference_medical_review_records "
                "WHERE project_id=? AND translation_id=?",
                (PROJECT_ID, first.translation_id),
            ).fetchone()[0]
            after_audits = connection.execute(
                "SELECT COUNT(*) FROM writing_reference_audit_chain WHERE project_id=?",
                (PROJECT_ID,),
            ).fetchone()[0]
        self.assertEqual(before_reviews, after_reviews)
        self.assertEqual(before_audits, after_audits)
        self.assertEqual(
            "pending_author_confirmation",
            self.repo.translations(PROJECT_ID)[0].status,
        )

    def test_stale_approved_review_cannot_be_used_for_admission(self) -> None:
        translation = self._prepare_admissible_translation()
        approved = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            translation_revision=translation.revision,
            decision="approved",
            comment="译文与原文一致，可作为写作参照。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="review-approved-before-return",
        )
        self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            translation_revision=translation.revision,
            decision="returned",
            comment="复核后要求调整监管中文措辞。",
            actor="medical_director",
            expected_revision=1,
            idempotency_key="review-returned-current",
        )

        with self.assertRaisesRegex(
            WritingReferenceConflictError,
            "no longer the current review",
        ):
            self.repo.admit_translation(
                project_id=PROJECT_ID,
                translation_id=translation.translation_id,
                expected_translation_revision=translation.revision,
                medical_review_id=approved.review_id,
                idempotency_key="admission-with-stale-approved-review",
            )
        self.assertEqual([], self.repo.evidence_briefs(PROJECT_ID))

    def test_returning_an_admitted_translation_invalidates_the_current_brief(self) -> None:
        translation = self._prepare_admissible_translation()
        approved = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            translation_revision=translation.revision,
            decision="approved",
            comment="译文与原文一致，可作为写作参照。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="review-approved-before-admission-return",
        )
        self.repo.admit_translation(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            expected_translation_revision=translation.revision,
            medical_review_id=approved.review_id,
            idempotency_key="admission-before-review-return",
        )

        self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            translation_revision=translation.revision,
            decision="returned",
            comment="复核发现译文残留未翻译英文连接词，退回修订。",
            actor="medical_manager",
            expected_revision=1,
            idempotency_key="review-return-after-admission",
        )

        self.assertEqual([], self.repo.evidence_briefs(PROJECT_ID))
        history = self.repo.evidence_brief_history(PROJECT_ID)
        self.assertEqual(1, len(history))
        self.assertEqual("invalidated_review", history[0].status)
        self.assertEqual([], self.repo.verify_audit_chain(PROJECT_ID))

    def test_new_extraction_revision_invalidates_prior_translation_and_brief(self) -> None:
        translation = self._prepare_admissible_translation()
        approved = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            translation_revision=translation.revision,
            decision="approved",
            comment="译文与原文一致，可作为写作参照。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="review-before-extraction-supersession",
        )
        self.repo.admit_translation(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            expected_translation_revision=translation.revision,
            medical_review_id=approved.review_id,
            idempotency_key="admission-before-extraction-supersession",
        )
        next_span = self.span.model_copy(
            update={
                "span_id": "wref_span_002",
                "extraction_revision": "pymupdf_1.26.5_m11map_v6_aaaaaaaaaaaaaaaa",
            }
        )
        self.repo.save_extraction(
            WritingReferenceExtractionResult(
                artifact_id=self.artifact.artifact_id,
                project_id=PROJECT_ID,
                extraction_revision=next_span.extraction_revision,
                parser_name="PyMuPDF",
                parser_version="1.26.5",
                page_count=20,
                status="pending_visual_and_medical_structure_review",
                spans=[next_span],
            ),
            idempotency_key="extract-superseding-revision",
        )

        self.assertEqual([], self.repo.evidence_briefs(PROJECT_ID))
        self.assertEqual("invalidated_extraction", self.repo.evidence_brief_history(PROJECT_ID)[0].status)
        self.assertEqual("invalidated_extraction", self.repo.translations(PROJECT_ID)[0].status)
        self.assertEqual([], self.repo.verify_audit_chain(PROJECT_ID))

    def test_source_invalidated_before_admission_fails_closed(self) -> None:
        translation = self._prepare_admissible_translation()
        approved = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            translation_revision=translation.revision,
            decision="approved",
            comment="译文与原文一致，可作为写作参照。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="review-before-source-invalidation",
        )
        self.repo.invalidate_artifact(
            project_id=PROJECT_ID,
            artifact_id=self.artifact.artifact_id,
            reason="公开来源已发布替代版本，当前文件不再有效。",
            actor="system_version_monitor",
            expected_revision=1,
            idempotency_key="invalidate-before-admission",
        )

        with self.assertRaisesRegex(ValueError, "current source artifact"):
            self.repo.admit_translation(
                project_id=PROJECT_ID,
                translation_id=translation.translation_id,
                expected_translation_revision=translation.revision,
                medical_review_id=approved.review_id,
                idempotency_key="admission-after-source-invalidation",
            )
        self.assertEqual([], self.repo.evidence_briefs(PROJECT_ID))

    def test_repeated_semantic_admission_reuses_brief_and_second_review_conflicts_cleanly(self) -> None:
        translation = self._prepare_admissible_translation()
        first_review = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            translation_revision=translation.revision,
            decision="approved",
            comment="译文与原文一致，可作为写作参照。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="review-first-approved",
        )
        first = self.repo.admit_translation(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            expected_translation_revision=translation.revision,
            medical_review_id=first_review.review_id,
            idempotency_key="admission-semantic-first",
        )
        repeated = self.repo.admit_translation(
            project_id=PROJECT_ID,
            translation_id=translation.translation_id,
            expected_translation_revision=translation.revision,
            medical_review_id=first_review.review_id,
            idempotency_key="admission-semantic-second-key",
        )

        self.assertEqual(first.model_dump(), repeated.model_dump())
        self.assertEqual(1, len(self.repo.evidence_brief_history(PROJECT_ID)))
        with sqlite3.connect(self.path) as connection:
            admission_events = connection.execute(
                "SELECT COUNT(*) FROM writing_reference_audit_chain "
                "WHERE project_id=? AND event_type='translation_admitted_to_corpus'",
                (PROJECT_ID,),
            ).fetchone()[0]
            admission_keys = connection.execute(
                "SELECT COUNT(DISTINCT idempotency_key) FROM writing_reference_idempotency "
                "WHERE project_id=? AND operation='admit_translation'",
                (PROJECT_ID,),
            ).fetchone()[0]
        self.assertEqual(1, admission_events)
        self.assertEqual(3, admission_keys)

        with self.assertRaisesRegex(
            WritingReferenceConflictError,
            "already admitted under a different medical review",
        ):
            self.repo.record_medical_review(
                project_id=PROJECT_ID,
                translation_id=translation.translation_id,
                translation_revision=translation.revision,
                decision="approved",
                comment="重复作者确认不得改写既有准入确认绑定。",
                actor="medical_manager",
                expected_revision=1,
                idempotency_key="review-second-approved",
            )
        self.assertEqual([], self.repo.verify_audit_chain(PROJECT_ID))


if __name__ == "__main__":
    unittest.main()
