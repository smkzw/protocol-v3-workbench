from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from services.api.app.writing_reference import (
    evaluate_document_content,
    extract_pdf_sections,
)
from services.api.app.writing_reference_repository import (
    WritingReferenceRepository,
    WritingReferenceStaleStateError,
)
from tests.test_writing_reference_extraction import artifact, pdf_fixture
from tests.test_writing_reference_repository import PROJECT_ID, snapshot


class WritingReferenceDocumentValidationTests(unittest.TestCase):
    def _seed_validation_with_warning(self, repo: WritingReferenceRepository):
        source_snapshot = snapshot()
        repo.save_search_snapshot(source_snapshot, idempotency_key="stale-search")
        payload = pdf_fixture()
        source = artifact(hashlib.sha256(payload).hexdigest()).model_copy(
            update={"actual_size": len(payload), "source_status": "user_uploaded"}
        )
        repo.save_document_artifact(
            source,
            storage_relpath="safe/stale-source.pdf",
            idempotency_key="stale-artifact",
        )
        extraction = extract_pdf_sections(payload, source)
        repo.save_extraction(extraction, idempotency_key="stale-extraction-r1")
        publication_spans = [
            span.model_copy(
                update={
                    "source_text": "Abstract Journal article DOI:10.1000/example References",
                    "source_text_sha256": hashlib.sha256(
                        b"Abstract Journal article DOI:10.1000/example References"
                    ).hexdigest(),
                }
            )
            for span in extraction.spans
        ]
        validation = evaluate_document_content(
            snapshot=source_snapshot,
            artifact=source,
            spans=publication_spans,
            actor="system_validator",
        )
        repo.save_document_validation(
            validation,
            expected_revision=0,
            idempotency_key="stale-validation",
        )
        warning_codes = sorted(
            check.check_code
            for check in validation.checks
            if check.outcome in {"warning", "mismatch"}
        )
        return source, extraction, warning_codes

    def test_protocol_content_is_checked_against_study_indication_and_document_type(self) -> None:
        payload = pdf_fixture()
        source = artifact(hashlib.sha256(payload).hexdigest()).model_copy(
            update={"actual_size": len(payload)}
        )
        extraction = extract_pdf_sections(payload, source)

        validation = evaluate_document_content(
            snapshot=snapshot(),
            artifact=source,
            spans=extraction.spans,
            actor="system_validator",
        )

        self.assertIn(validation.status, {"confirmed", "needs_review"})
        self.assertEqual(
            {"study_identifier", "indication", "document_type", "source_metadata", "document_version_date"},
            {check.check_code for check in validation.checks},
        )
        document_type = next(
            check for check in validation.checks if check.check_code == "document_type"
        )
        self.assertEqual("match", document_type.outcome)

    def test_publication_mismatch_can_only_be_overridden_with_full_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = WritingReferenceRepository(Path(tmp) / "writing_reference.sqlite3")
            source_snapshot = snapshot()
            repo.save_search_snapshot(source_snapshot, idempotency_key="search-001")
            payload = pdf_fixture()
            source = artifact(hashlib.sha256(payload).hexdigest()).model_copy(
                update={
                    "actual_size": len(payload),
                    "source_status": "user_uploaded",
                }
            )
            repo.save_document_artifact(
                source,
                storage_relpath="safe/source.pdf",
                idempotency_key="artifact-001",
            )
            extraction = extract_pdf_sections(payload, source)
            repo.save_extraction(extraction, idempotency_key="publication-extraction")
            publication_spans = [
                span.model_copy(
                    update={
                        "source_text": "Abstract Journal article DOI:10.1000/example References",
                        "source_text_sha256": hashlib.sha256(
                            b"Abstract Journal article DOI:10.1000/example References"
                        ).hexdigest(),
                    }
                )
                for span in extraction.spans
            ]
            validation = evaluate_document_content(
                snapshot=source_snapshot,
                artifact=source,
                spans=publication_spans,
                actor="system_validator",
            )
            self.assertEqual("mismatch", validation.status)
            repo.save_document_validation(
                validation,
                expected_revision=0,
                idempotency_key="validation-001",
            )
            warning_codes = sorted(
                check.check_code
                for check in validation.checks
                if check.outcome in {"warning", "mismatch"}
            )

            with self.assertRaisesRegex(ValueError, "all current"):
                repo.override_document_validation(
                    project_id=PROJECT_ID,
                    artifact_id=source.artifact_id,
                    reason="医学经理已核对原文，确认该文件适用于当前方案任务。",
                    acknowledged_warning_codes=[],
                    actor="medical_manager",
                    expected_revision=1,
                    idempotency_key="override-incomplete",
                )

            overridden = repo.override_document_validation(
                project_id=PROJECT_ID,
                artifact_id=source.artifact_id,
                reason="医学经理已核对原文，确认该文件适用于当前方案任务。",
                acknowledged_warning_codes=warning_codes,
                actor="medical_manager",
                expected_revision=1,
                idempotency_key="override-complete",
            )
            self.assertEqual("user_overridden", overridden.status)
            self.assertEqual(2, overridden.revision)
            self.assertEqual(warning_codes, overridden.acknowledged_warning_codes)
            with self.assertRaisesRegex(ValueError, "current validation warnings"):
                repo.override_document_validation(
                    project_id=PROJECT_ID,
                    artifact_id=source.artifact_id,
                    reason="医学经理再次确认沿用当前文件，但该记录已经完成确认。",
                    acknowledged_warning_codes=warning_codes,
                    actor="medical_manager",
                    expected_revision=2,
                    idempotency_key="override-repeat",
                )
            self.assertEqual([], repo.verify_audit_chain(PROJECT_ID))

    def test_confirmed_document_cannot_be_changed_to_overridden_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = WritingReferenceRepository(Path(tmp) / "writing_reference.sqlite3")
            source_snapshot = snapshot()
            repo.save_search_snapshot(source_snapshot, idempotency_key="search-confirmed")
            payload = pdf_fixture()
            source = artifact(hashlib.sha256(payload).hexdigest()).model_copy(
                update={"actual_size": len(payload)}
            )
            repo.save_document_artifact(
                source,
                storage_relpath="safe/confirmed.pdf",
                idempotency_key="artifact-confirmed",
            )
            extraction = extract_pdf_sections(payload, source)
            repo.save_extraction(extraction, idempotency_key="confirmed-extraction")
            validation = evaluate_document_content(
                snapshot=source_snapshot,
                artifact=source,
                spans=extraction.spans,
                actor="system_validator",
            ).model_copy(update={"status": "confirmed"})
            repo.save_document_validation(
                validation,
                expected_revision=0,
                idempotency_key="validation-confirmed",
            )

            with self.assertRaisesRegex(ValueError, "current validation warnings"):
                repo.override_document_validation(
                    project_id=PROJECT_ID,
                    artifact_id=source.artifact_id,
                    reason="医学经理确认文件内容与当前研究和预期文件类型一致。",
                    acknowledged_warning_codes=[],
                    actor="medical_manager",
                    expected_revision=1,
                    idempotency_key="override-confirmed",
                )

    def test_protocol_sap_role_boundaries_do_not_treat_one_file_type_as_the_other(self) -> None:
        payload = pdf_fixture()
        base = artifact(hashlib.sha256(payload).hexdigest()).model_copy(
            update={"actual_size": len(payload), "source_status": "user_uploaded"}
        )
        extraction = extract_pdf_sections(payload, base)

        protocol_only_spans = [
            span
            for span in extraction.spans
            if "Statistical Analysis Plan" not in span.source_text
            and "Missing data and multiplicity" not in span.source_text
        ]
        declared_sap = evaluate_document_content(
            snapshot=snapshot(),
            artifact=base.model_copy(update={"document_type": "sap"}),
            spans=protocol_only_spans,
            actor="system_validator",
        )
        sap_type = next(check for check in declared_sap.checks if check.check_code == "document_type")
        self.assertEqual("mismatch", sap_type.outcome)
        self.assertIn("疑似Protocol", sap_type.observed_value)

        declared_combined = evaluate_document_content(
            snapshot=snapshot(),
            artifact=base.model_copy(update={"document_type": "protocol_sap"}),
            spans=protocol_only_spans,
            actor="system_validator",
        )
        combined_type = next(
            check
            for check in declared_combined.checks
            if check.check_code == "document_type"
        )
        self.assertEqual("match", combined_type.outcome)
        self.assertIn("仅按Protocol语料使用", combined_type.observed_value)

        sap_only_spans = [
            span.model_copy(update={"ich_m11_anchor": "statistics"})
            for span in extraction.spans
            if span.physical_page == 2
        ]
        declared_protocol = evaluate_document_content(
            snapshot=snapshot(),
            artifact=base.model_copy(update={"document_type": "protocol"}),
            spans=sap_only_spans,
            actor="system_validator",
        )
        protocol_type = next(
            check for check in declared_protocol.checks if check.check_code == "document_type"
        )
        self.assertEqual("mismatch", protocol_type.outcome)
        self.assertIn("疑似SAP", protocol_type.observed_value)

    def test_ctgov_declared_sap_is_not_reclassified_from_protocol_references(self) -> None:
        payload = pdf_fixture()
        source_snapshot = snapshot()
        candidate = source_snapshot.candidates[0]
        public_sap = candidate.public_documents[0].model_copy(
            update={
                "document_type": "sap",
                "label": "Statistical Analysis Plan",
                "filename": "SAP_001.pdf",
                "download_url": (
                    "https://clinicaltrials.gov/ProvidedDocs/38/"
                    "NCT05014438/SAP_001.pdf"
                ),
            }
        )
        source_snapshot = source_snapshot.model_copy(
            update={
                "candidates": [
                    candidate.model_copy(update={"public_documents": [public_sap]})
                ]
            }
        )
        source = artifact(hashlib.sha256(payload).hexdigest()).model_copy(
            update={
                "actual_size": len(payload),
                "source_document_id": public_sap.document_id,
                "document_type": "sap",
                "filename": public_sap.filename,
                "requested_url": public_sap.download_url,
                "final_url": public_sap.download_url,
                "source_status": "downloaded",
            }
        )
        extraction = extract_pdf_sections(payload, source)

        validation = evaluate_document_content(
            snapshot=source_snapshot,
            artifact=source,
            spans=extraction.spans,
            actor="system_validator",
        )

        document_type = next(
            check
            for check in validation.checks
            if check.check_code == "document_type"
        )
        self.assertEqual("match", document_type.outcome)
        self.assertIn("ClinicalTrials.gov登记为SAP", document_type.observed_value)

    def test_manual_upload_does_not_admit_a_clear_publication_substitution(self) -> None:
        payload = pdf_fixture()
        source_snapshot = snapshot()
        source = artifact(hashlib.sha256(payload).hexdigest()).model_copy(
            update={
                "actual_size": len(payload),
                "source_status": "user_uploaded",
            }
        )
        extraction = extract_pdf_sections(payload, source)
        publication_spans = [
            span.model_copy(
                update={
                    "source_text": (
                        "Abstract Journal article DOI:10.1000/example References"
                    ),
                    "source_text_sha256": hashlib.sha256(
                        b"Abstract Journal article DOI:10.1000/example References"
                    ).hexdigest(),
                    "ich_m11_anchor": "unmapped",
                }
            )
            for span in extraction.spans
        ]

        validation = evaluate_document_content(
            snapshot=source_snapshot,
            artifact=source,
            spans=publication_spans,
            actor="system_validator",
        )

        document_type = next(
            check
            for check in validation.checks
            if check.check_code == "document_type"
        )
        self.assertEqual("mismatch", document_type.outcome)
        self.assertIn("Publication", document_type.observed_value)

    def test_ctgov_binding_records_other_cited_nct_without_forcing_review(self) -> None:
        payload = pdf_fixture()
        source = artifact(hashlib.sha256(payload).hexdigest()).model_copy(
            update={"actual_size": len(payload), "source_status": "downloaded"}
        )
        extraction = extract_pdf_sections(payload, source)
        cited_spans = [
            span.model_copy(
                update={
                    "source_text": (
                        f"{span.source_text}\nBackground study NCT03313570."
                    ),
                    "source_text_sha256": hashlib.sha256(
                        (
                            f"{span.source_text}\nBackground study NCT03313570."
                        ).encode()
                    ).hexdigest(),
                }
            )
            for span in extraction.spans
        ]

        validation = evaluate_document_content(
            snapshot=snapshot(),
            artifact=source,
            spans=cited_spans,
            actor="system_validator",
        )

        study_identifier = next(
            check
            for check in validation.checks
            if check.check_code == "study_identifier"
        )
        self.assertEqual("match", study_identifier.outcome)
        self.assertIn("正文另见引用 NCT03313570", study_identifier.observed_value)

    def test_ctgov_binding_covers_indication_when_body_omits_exact_name(self) -> None:
        payload = pdf_fixture()
        source = artifact(hashlib.sha256(payload).hexdigest()).model_copy(
            update={"actual_size": len(payload), "source_status": "downloaded"}
        )
        extraction = extract_pdf_sections(payload, source)
        without_indication = [
            span.model_copy(
                update={
                    "source_text": span.source_text.replace(
                        "Atopic Dermatitis", "target disease"
                    ),
                    "source_text_sha256": hashlib.sha256(
                        span.source_text.replace(
                            "Atopic Dermatitis", "target disease"
                        ).encode()
                    ).hexdigest(),
                }
            )
            for span in extraction.spans
        ]

        validation = evaluate_document_content(
            snapshot=snapshot(),
            artifact=source,
            spans=without_indication,
            actor="system_validator",
        )

        indication = next(
            check for check in validation.checks if check.check_code == "indication"
        )
        self.assertEqual("match", indication.outcome)
        self.assertIn("与检索快照绑定", indication.observed_value)

    def test_override_rejects_validation_after_source_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = WritingReferenceRepository(Path(tmp) / "writing_reference.sqlite3")
            source, _, warning_codes = self._seed_validation_with_warning(repo)
            repo.invalidate_artifact(
                project_id=PROJECT_ID,
                artifact_id=source.artifact_id,
                reason="该来源已被新的正式版本替代。",
                actor="medical_manager",
                expected_revision=1,
                idempotency_key="stale-invalidate",
            )

            with self.assertRaisesRegex(
                WritingReferenceStaleStateError,
                "document source is no longer current",
            ):
                repo.override_document_validation(
                    project_id=PROJECT_ID,
                    artifact_id=source.artifact_id,
                    reason="医学经理已复核，但旧来源状态不应允许继续确认。",
                    acknowledged_warning_codes=warning_codes,
                    actor="medical_manager",
                    expected_revision=1,
                    idempotency_key="stale-override-invalidated",
                )

    def test_override_rejects_validation_after_new_extraction_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = WritingReferenceRepository(Path(tmp) / "writing_reference.sqlite3")
            source, extraction, warning_codes = self._seed_validation_with_warning(repo)
            revision = "manual_reparse_r2"
            newer = extraction.model_copy(
                update={
                    "extraction_revision": revision,
                    "spans": [
                        span.model_copy(
                            update={
                                "span_id": f"{span.span_id}_{revision}",
                                "extraction_revision": revision,
                            }
                        )
                        for span in extraction.spans
                    ],
                }
            )
            repo.save_extraction(newer, idempotency_key="stale-extraction-r2")

            with self.assertRaisesRegex(
                WritingReferenceStaleStateError,
                "document extraction changed after validation",
            ):
                repo.override_document_validation(
                    project_id=PROJECT_ID,
                    artifact_id=source.artifact_id,
                    reason="医学经理已复核，但旧解构版本不应允许继续确认。",
                    acknowledged_warning_codes=warning_codes,
                    actor="medical_manager",
                    expected_revision=1,
                    idempotency_key="stale-override-reparsed",
                )


if __name__ == "__main__":
    unittest.main()
