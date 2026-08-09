from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from packages.contracts.workbench_contracts import (
    AiTaskSourceRef,
    MedicalWritingSynopsisSource,
)
from services.api.app.medical_writing_synopsis_import import (
    MedicalWritingSynopsisImportService,
)


PROJECT_ID = "proj_merge_integrity"
IDEMPOTENCY_KEY = "merge-integrity"
ROUTE_IDENTITY_HASH = "d" * 64


def _source_ref(
    source_id: str,
    *,
    locator: str,
    text_preview: str,
) -> AiTaskSourceRef:
    return AiTaskSourceRef(
        source_id=source_id,
        source_type="protocol_synopsis",
        title="跨分块方案摘要",
        locator=locator,
        text_preview=text_preview,
        project_id=PROJECT_ID,
        module="medical_writing",
    )


def _chunk_output(*, evidence_spans: list[dict] | None = None) -> dict:
    return {
        "study_definition": {
            "framing": {},
            "picos": {},
            "synopsis_text": "",
            "missing_fields": [],
            "conflict_notes": [],
            "field_evidence_span_ids": {},
        },
        "evidence_spans": evidence_spans or [],
    }


def _protocol_source() -> MedicalWritingSynopsisSource:
    return MedicalWritingSynopsisSource(
        source_id="protocol_source",
        original_filename="跨分块方案摘要.docx",
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        actual_size=128,
        content_sha256="a" * 64,
        extraction_revision="docx_v1",
        parser_name="test",
        source_role_status="matched",
        indication_status="not_assessed",
        validation_warnings=[],
        imported_at="2026-07-25T00:00:00+08:00",
        imported_by="medical_manager",
    )


def _insert_done_chunks(
    service: MedicalWritingSynopsisImportService,
    chunks: list[tuple[dict, list[AiTaskSourceRef]]],
) -> None:
    assert len(chunks) == 2
    with service._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO medical_writing_synopsis_imports(
                project_id,
                idempotency_key,
                request_sha256,
                status,
                payload_json,
                created_at,
                route_identity_hash
            )
            VALUES (?, ?, ?, 'running', '', ?, ?)
            """,
            (
                PROJECT_ID,
                IDEMPOTENCY_KEY,
                "a" * 64,
                "2026-07-25T00:00:00+08:00",
                ROUTE_IDENTITY_HASH,
            ),
        )
        for chunk_index, (output, sources) in enumerate(chunks):
            connection.execute(
                """
                INSERT INTO medical_writing_synopsis_import_chunks(
                    project_id,
                    idempotency_key,
                    chunk_index,
                    status,
                    started_at,
                    output_json,
                    chunk_sources_json,
                    route_identity_hash
                )
                VALUES (?, ?, ?, 'done', ?, ?, ?, ?)
                """,
                (
                    PROJECT_ID,
                    IDEMPOTENCY_KEY,
                    chunk_index,
                    "2026-07-25T00:00:00+08:00",
                    json.dumps(output, ensure_ascii=False),
                    json.dumps(
                        [source.model_dump(mode="json") for source in sources],
                        ensure_ascii=False,
                    ),
                    ROUTE_IDENTITY_HASH,
                ),
            )
        connection.commit()


def _merge(
    service: MedicalWritingSynopsisImportService,
):
    return service._merge_chunks(
        project_id=PROJECT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        source_id="protocol_source",
        source=_protocol_source(),
        expected_indication="",
        chunk_total=2,
    )


@pytest.fixture
def service():
    with tempfile.TemporaryDirectory() as temporary_directory:
        synopsis_service = MedicalWritingSynopsisImportService(
            Path(temporary_directory) / "artifacts",
            ai_task_runner=object(),
        )
        yield synopsis_service
        synopsis_service.shutdown(timeout=2.0)


def test_cross_chunk_merge_materializes_version_with_unique_source_bound_evidence(
    service: MedicalWritingSynopsisImportService,
) -> None:
    version_source = _source_ref(
        "source_version",
        locator="docx:paragraph:4",
        text_preview="方案版本号\t1.3",
    )
    second_chunk_source = _source_ref(
        "source_secondary",
        locator="docx:paragraph:5",
        text_preview="申办方：康哲药业",
    )
    _insert_done_chunks(
        service,
        [
            (_chunk_output(), [version_source]),
            (_chunk_output(), [second_chunk_source]),
        ],
    )

    result = _merge(service)

    assert result.proposed_framing.version == "V1.3"
    span_ids = [span.span_id for span in result.evidence_spans]
    assert len(span_ids) == len(set(span_ids))

    version_evidence_ids = result.field_evidence_span_ids["framing.version"]
    assert len(version_evidence_ids) == 1
    evidence_by_id = {span.span_id: span for span in result.evidence_spans}
    version_quote = evidence_by_id[version_evidence_ids[0]].source_text
    assert version_quote
    assert version_quote in version_source.text_preview


def test_cross_chunk_merge_rejects_duplicate_evidence_span_ids(
    service: MedicalWritingSynopsisImportService,
) -> None:
    version_source = _source_ref(
        "source_version",
        locator="docx:paragraph:4",
        text_preview="方案版本号\t1.3",
    )
    second_chunk_source = _source_ref(
        "source_secondary",
        locator="docx:paragraph:5",
        text_preview="申办方：康哲药业",
    )
    duplicate_span_id = "duplicate_span"
    _insert_done_chunks(
        service,
        [
            (
                _chunk_output(
                    evidence_spans=[
                        {
                            "span_id": duplicate_span_id,
                            "source_id": version_source.source_id,
                            "locator": version_source.locator,
                            "quote": version_source.text_preview,
                        }
                    ]
                ),
                [version_source],
            ),
            (
                _chunk_output(
                    evidence_spans=[
                        {
                            "span_id": duplicate_span_id,
                            "source_id": second_chunk_source.source_id,
                            "locator": second_chunk_source.locator,
                            "quote": second_chunk_source.text_preview,
                        }
                    ]
                ),
                [second_chunk_source],
            ),
        ],
    )

    with pytest.raises(RuntimeError, match="duplicate evidence span_id"):
        _merge(service)


def test_cross_chunk_merge_rejects_quote_not_present_in_original_source(
    service: MedicalWritingSynopsisImportService,
) -> None:
    version_source = _source_ref(
        "source_version",
        locator="docx:paragraph:4",
        text_preview="方案版本号\t1.3",
    )
    second_chunk_source = _source_ref(
        "source_secondary",
        locator="docx:paragraph:5",
        text_preview="申办方：康哲药业",
    )
    _insert_done_chunks(
        service,
        [
            (
                _chunk_output(
                    evidence_spans=[
                        {
                            "span_id": "fabricated_version_span",
                            "source_id": version_source.source_id,
                            "locator": version_source.locator,
                            "quote": "方案版本号\tV9.9",
                        }
                    ]
                ),
                [version_source],
            ),
            (_chunk_output(), [second_chunk_source]),
        ],
    )

    with pytest.raises(
        RuntimeError,
        match="merged evidence quote is not present in source",
    ):
        _merge(service)
