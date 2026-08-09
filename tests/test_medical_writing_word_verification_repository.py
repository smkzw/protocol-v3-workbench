from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.api.app.medical_writing_word_verification_repository import (
    MedicalWritingWordVerificationRepository,
    WordVerificationReceiptIdempotencyConflict,
    WordVerificationReceiptStaleError,
)
from tests.test_medical_writing_word_verification import _document, _receipt


def test_receipt_repository_is_idempotent_and_survives_restart(tmp_path):
    document = _document()
    db_path = tmp_path / "word_receipts.sqlite3"
    repository = MedicalWritingWordVerificationRepository(db_path)
    receipt = _receipt(document)

    first = repository.save(
        receipt,
        expected_source_snapshot_sha256=receipt.source_snapshot_sha256,
        expected_docx_sha256=receipt.docx_sha256,
        actor="medical_manager",
    )
    replay = repository.save(
        receipt,
        expected_source_snapshot_sha256=receipt.source_snapshot_sha256,
        expected_docx_sha256=receipt.docx_sha256,
        actor="another_worker",
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.request_id == first.request_id
    assert replay.audit_id == first.audit_id
    assert replay.receipt.model_dump() == first.receipt.model_dump()
    assert repository.get(document.project_id, document.document_id) == receipt
    assert len(repository.audit_events(document.project_id, document.document_id)) == 1

    restarted = MedicalWritingWordVerificationRepository(db_path)
    assert restarted.get(document.project_id, document.document_id) == receipt
    assert len(restarted.audit_events(document.project_id, document.document_id)) == 1


def test_repository_rejects_conflicting_keys_and_stale_identity(tmp_path):
    document = _document()
    repository = MedicalWritingWordVerificationRepository(tmp_path / "word.sqlite3")
    receipt = _receipt(document)
    repository.save(
        receipt,
        expected_source_snapshot_sha256=receipt.source_snapshot_sha256,
        expected_docx_sha256=receipt.docx_sha256,
        actor="medical_manager",
    )

    same_key_different_payload = receipt.model_copy(
        update={"verification_id": "word-check-002"}
    )
    with pytest.raises(WordVerificationReceiptIdempotencyConflict):
        repository.save(
            same_key_different_payload,
            expected_source_snapshot_sha256=receipt.source_snapshot_sha256,
            expected_docx_sha256=receipt.docx_sha256,
            actor="medical_manager",
        )
    different_key_same_id = receipt.model_copy(
        update={"idempotency_key": "word-check-002-idempotent"}
    )
    with pytest.raises(WordVerificationReceiptIdempotencyConflict):
        repository.save(
            different_key_same_id,
            expected_source_snapshot_sha256=receipt.source_snapshot_sha256,
            expected_docx_sha256=receipt.docx_sha256,
            actor="medical_manager",
        )
    with pytest.raises(WordVerificationReceiptStaleError):
        repository.save(
            receipt,
            expected_source_snapshot_sha256="a" * 64,
            expected_docx_sha256=receipt.docx_sha256,
            actor="medical_manager",
        )
    with pytest.raises(WordVerificationReceiptStaleError):
        repository.save(
            receipt,
            expected_source_snapshot_sha256=receipt.source_snapshot_sha256,
            expected_docx_sha256="a" * 64,
            actor="medical_manager",
        )
    with pytest.raises(WordVerificationReceiptStaleError):
        repository.get(
            document.project_id,
            document.document_id,
            expected_source_snapshot_sha256="a" * 64,
        )


def test_repository_same_key_concurrency_writes_one_receipt(tmp_path):
    document = _document()
    db_path = tmp_path / "word-concurrent.sqlite3"
    receipt = _receipt(document)

    def worker():
        repository = MedicalWritingWordVerificationRepository(db_path)
        return repository.save(
            receipt,
            expected_source_snapshot_sha256=receipt.source_snapshot_sha256,
            expected_docx_sha256=receipt.docx_sha256,
            actor="worker",
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: worker(), range(6)))
    assert sum(result.replayed is False for result in results) == 1
    assert {result.audit_id for result in results} == {results[0].audit_id}
    repository = MedicalWritingWordVerificationRepository(db_path)
    assert len(repository.audit_events(document.project_id, document.document_id)) == 1


def test_repository_receipt_and_audit_rows_are_immutable(tmp_path):
    document = _document()
    db_path = tmp_path / "word-immutable.sqlite3"
    repository = MedicalWritingWordVerificationRepository(db_path)
    receipt = _receipt(document)
    repository.save(
        receipt,
        expected_source_snapshot_sha256=receipt.source_snapshot_sha256,
        expected_docx_sha256=receipt.docx_sha256,
        actor="medical_manager",
    )

    with sqlite3.connect(db_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE medical_writing_word_verification_receipts SET status = 'word_verified'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM medical_writing_word_verification_audit")
