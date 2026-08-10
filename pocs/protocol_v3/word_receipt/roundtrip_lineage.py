"""Immutable Task 0.8 staging for a real external Word wording edit.

This module does not edit Word files itself.  It prepares a task-owned copy for
the human-visible Word edit, records the imported bytes as a new artifact, and
creates the exact lineage manifest consumed by the Word receipt producer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from pocs.protocol_v3.word_receipt.contract import validate_receipt
from pocs.protocol_v3.word_receipt.producers.base import (
    ProducerFunctionalError,
    atomic_write_json_once,
    sha256_file,
)


PREPARED_MANIFEST = "001-roundtrip-prepared.json"
LINEAGE_MANIFEST = "002-lineage-manifest.json"
SOURCE_EXPORT = "source-export.docx"
EXTERNAL_EDIT = "external-word-edit.docx"
REIMPORTED = "reimported.docx"
REEXPORTED = "reexport.docx"


def _atomic_copy_once(source: Path, target: Path) -> None:
    if target.exists():
        raise ProducerFunctionalError("WR_ARTIFACT_EXISTS", str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary_path = Path(temporary)
    try:
        with source.open("rb") as input_stream, os.fdopen(handle, "wb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        os.link(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)


def prepare_roundtrip(source_run_dir: Path, roundtrip_dir: Path) -> dict[str, Any]:
    """Create immutable source and task-owned edit copies from a final receipt."""

    receipt_path = source_run_dir / "receipt.json"
    saved_path = source_run_dir / "word-saved.docx"
    if not receipt_path.is_file() or not saved_path.is_file():
        raise ProducerFunctionalError(
            "WR_ROUNDTRIP_SOURCE", "a finalized receipt and Word-saved DOCX are required"
        )
    receipt = validate_receipt(json.loads(receipt_path.read_text(encoding="utf-8")))
    saved_hash = sha256_file(saved_path)
    if saved_hash != receipt["saved_docx_sha256"]:
        raise ProducerFunctionalError(
            "WR_ROUNDTRIP_SOURCE", "source receipt no longer binds the Word-saved DOCX"
        )
    roundtrip_dir.mkdir(parents=True, exist_ok=True)
    source_copy = roundtrip_dir / SOURCE_EXPORT
    edit_copy = roundtrip_dir / EXTERNAL_EDIT
    prepared_path = roundtrip_dir / PREPARED_MANIFEST
    if prepared_path.exists():
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        if (
            source_copy.is_file()
            and edit_copy.is_file()
            and sha256_file(source_copy) == prepared.get("source_artifact_sha256")
        ):
            return {**prepared, "status": "replayed"}
        raise ProducerFunctionalError(
            "WR_UNKNOWN_OUTCOME", "prepared roundtrip artifacts are incomplete or changed"
        )
    _atomic_copy_once(saved_path, source_copy)
    _atomic_copy_once(saved_path, edit_copy)
    prepared = {
        "status": "prepared_for_external_word_edit",
        "source_receipt_id": receipt["receipt_id"],
        "source_receipt_sha256": sha256_file(receipt_path),
        "source_artifact_id": receipt["saved_artifact_id"],
        "source_artifact_sha256": saved_hash,
        "source_export_path": str(source_copy),
        "external_edit_path": str(edit_copy),
    }
    atomic_write_json_once(prepared_path, prepared)
    return prepared


def stage_reimport(
    roundtrip_dir: Path,
    *,
    merged_semantic_revision: str,
) -> dict[str, Any]:
    """Freeze edited, reimported and re-export handoff artifacts plus lineage."""

    prepared_path = roundtrip_dir / PREPARED_MANIFEST
    if not prepared_path.is_file():
        raise ProducerFunctionalError("WR_ROUNDTRIP_NOT_PREPARED", str(roundtrip_dir))
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    source_path = roundtrip_dir / SOURCE_EXPORT
    edited_path = roundtrip_dir / EXTERNAL_EDIT
    reimported_path = roundtrip_dir / REIMPORTED
    reexported_path = roundtrip_dir / REEXPORTED
    lineage_path = roundtrip_dir / LINEAGE_MANIFEST
    if lineage_path.exists():
        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
        if (
            source_path.is_file()
            and edited_path.is_file()
            and reimported_path.is_file()
            and reexported_path.is_file()
            and sha256_file(source_path) == lineage.get("source_artifact_sha256")
            and sha256_file(edited_path) == lineage.get("edited_artifact_sha256")
            and sha256_file(reimported_path) == lineage.get("reimported_artifact_sha256")
            and sha256_file(reexported_path) == lineage.get("reexport_artifact_sha256")
            and lineage.get("merged_semantic_revision") == merged_semantic_revision.strip()
        ):
            return {"status": "replayed", "lineage": lineage}
        if (
            source_path.is_file()
            and edited_path.is_file()
            and reimported_path.is_file()
            and reexported_path.is_file()
            and sha256_file(source_path) == lineage.get("source_artifact_sha256")
            and sha256_file(edited_path) == lineage.get("edited_artifact_sha256")
            and sha256_file(reimported_path) == lineage.get("reimported_artifact_sha256")
            and sha256_file(reexported_path) == lineage.get("reexport_artifact_sha256")
        ):
            raise ProducerFunctionalError(
                "WR_LINEAGE_STALE",
                "staged lineage does not match the requested semantic revision",
            )
        raise ProducerFunctionalError(
            "WR_UNKNOWN_OUTCOME", "staged roundtrip artifacts are incomplete or changed"
        )
    source_hash = sha256_file(source_path)
    if source_hash != prepared.get("source_artifact_sha256"):
        raise ProducerFunctionalError("WR_SOURCE_CHANGED", "roundtrip source changed")
    edited_hash = sha256_file(edited_path)
    if edited_hash == source_hash:
        raise ProducerFunctionalError(
            "WR_EXTERNAL_EDIT_MISSING", "external Word edit did not change the DOCX bytes"
        )
    if not merged_semantic_revision.strip():
        raise ProducerFunctionalError("WR_LINEAGE_REVISION", "merged revision is required")
    _atomic_copy_once(edited_path, reimported_path)
    _atomic_copy_once(reimported_path, reexported_path)
    reimported_hash = sha256_file(reimported_path)
    reexported_hash = sha256_file(reexported_path)
    lineage = {
        "mode": "edit_reimport_export",
        "source_artifact_id": prepared["source_artifact_id"],
        "source_artifact_sha256": source_hash,
        "edited_artifact_id": f"word-external-edit-{edited_hash[:20]}",
        "edited_artifact_sha256": edited_hash,
        "reimported_artifact_id": f"word-reimport-{reimported_hash[:20]}",
        "reimported_artifact_sha256": reimported_hash,
        "merged_semantic_revision": merged_semantic_revision.strip(),
        "reexport_artifact_id": f"word-input-{reexported_hash[:20]}",
        "reexport_artifact_sha256": reexported_hash,
    }
    if len(
        {
            lineage["source_artifact_id"],
            lineage["edited_artifact_id"],
            lineage["reimported_artifact_id"],
            lineage["reexport_artifact_id"],
        }
    ) != 4:
        raise ProducerFunctionalError(
            "WR_LINEAGE_IMMUTABILITY", "roundtrip artifact identities must be distinct"
        )
    atomic_write_json_once(lineage_path, lineage)
    return {
        "status": "staged_for_word_verification",
        "reexport_path": str(reexported_path),
        "lineage_manifest": str(lineage_path),
        "lineage": lineage,
    }
