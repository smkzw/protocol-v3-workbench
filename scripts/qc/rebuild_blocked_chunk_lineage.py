#!/usr/bin/env python3
"""Zero-model offline tooling for fidelity-blocked translation chunk lineage.

Context (A110/A111): chapters blocked by the deterministic Hy-MT2 fidelity
gate historically persisted only the integration-level diagnostics
(``blocked_aligned_output`` / ``blocked_raw_provider_output``) — the
per-chunk alignment-unit lineage rows (``writing_reference_translation_chunks``)
were never written for the blocked chunk, which keeps the batch re-evaluation
channel fail-closed (``data_missing``) by design.  The blocked model output
IS persisted, so the alignment-unit lineage can be rebuilt offline with zero
model calls, deterministically, append-only.

Subcommands (all require explicit ``--db`` and ``--project``; the tool never
touches a default/live database):

``rebuild``
    For every blocked chapter integration: replay the persisted document
    plan + source spans through the deterministic chunker, match the blocked
    chunk against the ``translating_hy_mt2_blocked`` stage-ledger
    ``input_hash`` (sha256 of the chunk source text), derive the failed unit
    ordinals from the stored ``unit_N:`` fidelity codes, parse/normalize the
    persisted aligned output with the SAME shared helper the write-side
    landing uses, and persist the ``:blocked`` lineage row via the standard
    immutable repository path.  Every locator/parse mismatch fails closed as
    ``data_missing`` and lands nothing.

``reeval-evidence``
    Evidence-only unit-level re-judgment over blocked integrations:
    ``confirmed`` (the current deterministic checker still rejects the
    rebuilt unit target), ``overturned`` (it no longer rejects), or
    ``unverifyable`` (lineage gap — reported, never guessed).  Appends a
    ``blocked_fidelity_reeval_evidence`` audit event.  NEVER flips any
    ``generation_status`` — the batch admit channel stays untouched and
    disposition remains a human medical gate.

``medical-queue``
    Read-only (SQLite ``immutable=1``) summary of every
    ``generation_status='fidelity_blocked'`` item — the pending medical
    disposition queue.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_REPO_ROOT / "services" / "api"), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from packages.contracts.workbench_contracts import (  # noqa: E402
    WritingReferenceExtractedSpan,
)
from packages.contracts.workbench_contracts.models import (  # noqa: E402
    ChapterIntegrationResult,
    TranslationChunkRecord,
)
from services.api.app.chapter_translation_pipeline import (  # noqa: E402
    HY_MT2_MODEL_ID,
    HY_MT2_PROMPT_VERSION,
    TRANSLATION_CONTRACT_FINGERPRINT,
    DocumentPlanResult,
    build_chunks_from_plan,
    evaluate_translation_fidelity_aligned_units,
    split_source_into_units,
    _sha256 as _pipeline_sha256,
)
from services.api.app.writing_reference_repository import (  # noqa: E402
    TENANT_ID,
    WritingReferenceRepository,
)
from services.api.app.writing_reference_translation_batch import (  # noqa: E402
    _blocked_lineage_unit_targets,
)

UNIT_CODE_RE = re.compile(r"^unit_(\d+):")
BLOCKED_STAGE = "translating_hy_mt2_blocked"
BLOCKED_LINEAGE_STRATEGY = "rebuilt_offline_blocked_lineage"


def _failed_ordinals(codes: list[str]) -> list[int]:
    """Sorted unit ordinals named by ``unit_N:``-prefixed fidelity codes."""
    return sorted({
        int(match.group(1))
        for match in (UNIT_CODE_RE.match(str(code)) for code in codes)
        if match is not None
    })


def _load_blocked_integrations(
    repo: WritingReferenceRepository,
    project_id: str,
    integration_ids: list[str] | None = None,
) -> list[ChapterIntegrationResult]:
    query = (
        "SELECT payload_json FROM writing_reference_chapter_integration_results"
        " WHERE tenant_id=? AND project_id=? AND fidelity_status='blocked'"
    )
    params: list[Any] = [TENANT_ID, project_id]
    if integration_ids:
        query += " AND integration_id IN (%s)" % ",".join(
            "?" * len(integration_ids))
        params.extend(integration_ids)
    query += " ORDER BY integration_id"
    with repo._connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        ChapterIntegrationResult.model_validate_json(row["payload_json"])
        for row in rows
    ]


def _blocked_stage_input_hash(
    repo: WritingReferenceRepository,
    project_id: str,
    plan_id: str,
    chapter_id: str,
) -> str | None:
    """The (single, distinct) blocked-stage input hash for plan+chapter."""
    with repo._connect() as connection:
        rows = connection.execute(
            "SELECT payload_json FROM writing_reference_composite_pipeline_runs"
            " WHERE tenant_id=? AND project_id=? AND plan_id=? AND chapter_id=?",
            (TENANT_ID, project_id, plan_id, chapter_id),
        ).fetchall()
    hashes: set[str] = set()
    for row in rows:
        run = json.loads(row["payload_json"])
        for stage in run.get("stages", []):
            if stage.get("stage") == BLOCKED_STAGE and stage.get("input_hash"):
                hashes.add(str(stage["input_hash"]))
    if len(hashes) != 1:
        return None
    return next(iter(hashes))


def _replay_plan_chunks(
    repo: WritingReferenceRepository,
    project_id: str,
    plan_id: str,
    chapter_id: str,
) -> tuple[list[Any] | None, str | None]:
    """Deterministically replay plan+spans into the chapter's chunk specs.

    Mirrors the verified zero-model replay (runs/…t17_round20 evidence):
    persisted plan row + source span rows -> ``build_chunks_from_plan``.
    Returns ``(specs, None)`` or ``(None, data_missing_reason)``.
    """
    with repo._connect() as connection:
        plan_row = connection.execute(
            "SELECT payload_json FROM writing_reference_document_structure_plans"
            " WHERE tenant_id=? AND project_id=? AND plan_id=?",
            (TENANT_ID, project_id, plan_id),
        ).fetchone()
    if plan_row is None:
        return None, "document_structure_plan_row_missing"
    plan_payload = json.loads(plan_row["payload_json"])
    with repo._connect() as connection:
        span_rows = connection.execute(
            "SELECT payload_json FROM writing_reference_source_spans"
            " WHERE tenant_id=? AND project_id=? AND artifact_id=?"
            " AND extraction_revision=?",
            (
                TENANT_ID,
                project_id,
                plan_payload.get("artifact_id", ""),
                plan_payload.get("extraction_revision", ""),
            ),
        ).fetchall()
    if not span_rows:
        return None, "source_span_rows_missing"
    spans = sorted(
        (
            WritingReferenceExtractedSpan.model_validate_json(row["payload_json"])
            for row in span_rows
        ),
        key=lambda s: (s.artifact_id, s.physical_page, s.block_index, s.span_id),
    )
    plan_result = DocumentPlanResult(
        flash_plan=None,  # type: ignore[arg-type]
        chapters=tuple(
            (
                chapter["chapter_id"],
                chapter["title"],
                chapter.get("ich_m11_anchor", ""),
                tuple(chapter["source_span_ids"]),
            )
            for chapter in plan_payload["chapters"]
        ),
        document_role=plan_payload["document_role"],
        ambiguity_codes=tuple(plan_payload.get("ambiguity_codes", ())),
    )
    for entry in build_chunks_from_plan(plan_result, tuple(spans)):
        for key, chapter_chunks in entry.items():
            if key[0] == chapter_id:
                return list(chapter_chunks), None
    return None, "chapter_not_in_replayed_plan"


def _lineage_row(
    repo: WritingReferenceRepository,
    project_id: str,
    chunk_id: str,
) -> TranslationChunkRecord | None:
    with repo._connect() as connection:
        row = connection.execute(
            "SELECT payload_json FROM writing_reference_translation_chunks"
            " WHERE tenant_id=? AND project_id=? AND chunk_id=?",
            (TENANT_ID, project_id, chunk_id),
        ).fetchone()
    if row is None:
        return None
    return TranslationChunkRecord.model_validate_json(row["payload_json"])


def _missing(entry: dict, reason: str) -> dict:
    entry["outcome"] = "data_missing"
    entry["reason"] = reason
    return entry


def _locate_blocked_spec(
    repo: WritingReferenceRepository,
    project_id: str,
    integration: ChapterIntegrationResult,
) -> tuple[Any | None, str | None, str | None]:
    """Resolve the blocked chunk spec + stage input hash, fail-closed."""
    ledger_hash = _blocked_stage_input_hash(
        repo, project_id, integration.plan_id, integration.chapter_id)
    if not ledger_hash:
        return None, None, "blocked_stage_ledger_missing_or_ambiguous"
    specs, reason = _replay_plan_chunks(
        repo, project_id, integration.plan_id, integration.chapter_id)
    if reason is not None:
        return None, None, reason
    for spec in specs:
        if hashlib.sha256(spec.source_text.encode("utf-8")).hexdigest() == (
            ledger_hash
        ):
            return spec, ledger_hash, None
    return None, None, "blocked_chunk_not_replayable_from_plan"


def rebuild_blocked_lineage(
    repo: WritingReferenceRepository,
    project_id: str,
    *,
    integration_ids: list[str] | None = None,
    actor: str = "offline_lineage_rebuild",
) -> dict:
    """Rebuild ``:blocked`` lineage rows from persisted blocked outputs.

    Append-only: only NEW lineage rows are inserted (idempotency key is
    fully deterministic, so re-running is a no-op replay); no existing row
    is ever modified.  Any locator/parse mismatch is reported as
    ``data_missing`` and lands nothing for that integration.
    """
    del actor  # lineage provenance rides on translation_strategy; kept for CLI symmetry
    integrations = _load_blocked_integrations(repo, project_id, integration_ids)
    summary: dict[str, Any] = {
        "command": "rebuild",
        "project_id": project_id,
        "scanned": len(integrations),
        "rebuilt": 0,
        "already_present": 0,
        "data_missing": 0,
        "integrations": [],
    }
    for integration in integrations:
        entry: dict[str, Any] = {
            "integration_id": integration.integration_id,
            "plan_id": integration.plan_id,
            "chapter_id": integration.chapter_id,
        }
        aligned = (integration.blocked_aligned_output or "").strip()
        if not aligned:
            summary["integrations"].append(
                _missing(entry, "blocked_aligned_output_empty"))
            summary["data_missing"] += 1
            continue
        codes = list(integration.fidelity_failure_codes or [])
        failed_ordinals = _failed_ordinals(codes)
        if not failed_ordinals:
            summary["integrations"].append(
                _missing(entry, "no_unit_scoped_failure_codes"))
            summary["data_missing"] += 1
            continue
        spec, ledger_hash, reason = _locate_blocked_spec(
            repo, project_id, integration)
        if reason is not None:
            summary["integrations"].append(_missing(entry, reason))
            summary["data_missing"] += 1
            continue
        units = split_source_into_units(spec.source_text)
        unit_ordinals = {unit.ordinal for unit in units}
        targets = _blocked_lineage_unit_targets(units, aligned, codes)
        if not targets:
            summary["integrations"].append(
                _missing(entry, "blocked_aligned_output_unparseable"))
            summary["data_missing"] += 1
            continue
        outside = sorted(set(targets) - unit_ordinals)
        if outside:
            summary["integrations"].append(
                _missing(entry, f"unit_targets_outside_chunk_units:{outside}"))
            summary["data_missing"] += 1
            continue
        blocked_chunk_id = f"{spec.chunk_id}:blocked"
        blocked_fingerprint = f"{spec.chunk_fingerprint}:blocked"
        existing = _lineage_row(repo, project_id, blocked_chunk_id)
        record = TranslationChunkRecord(
            chunk_id=blocked_chunk_id,
            plan_id=integration.plan_id,
            project_id=project_id,
            artifact_id=integration.artifact_id,
            chapter_id=spec.chapter_id,
            chunk_order=spec.chunk_order,
            source_span_ids=list(spec.source_span_ids),
            source_text=spec.source_text,
            source_text_sha256=spec.source_text_sha256,
            adjacent_context_sha256=spec.adjacent_context_sha256,
            table_header_prefix=spec.table_header_prefix,
            chunk_fingerprint=blocked_fingerprint,
            hy_mt2_model=HY_MT2_MODEL_ID,
            hy_mt2_prompt_version=HY_MT2_PROMPT_VERSION,
            hy_mt2_input_hash=ledger_hash,
            translated_text=integration.blocked_aligned_output,
            translated_text_sha256=_pipeline_sha256(
                integration.blocked_aligned_output),
            unit_targets={
                str(ordinal): targets[ordinal]
                for ordinal in sorted(targets)
            },
            translation_strategy=BLOCKED_LINEAGE_STRATEGY,
            status="blocked",
            # The blocked event's own persisted time — deterministic across
            # rebuild runs, so the payload (and its hash) is reproducible.
            created_at=integration.created_at,
        )
        repo.save_translation_chunk(
            record,
            idempotency_key=(
                f"chunk:{integration.plan_id}:{blocked_chunk_id}:"
                f"{blocked_fingerprint[:16]}:"
                f"{TRANSLATION_CONTRACT_FINGERPRINT[:12]}"
            ),
        )
        entry.update({
            "outcome": "already_present" if existing is not None else "rebuilt",
            "chunk_id": blocked_chunk_id,
            "failed_unit_ordinals": failed_ordinals,
            "unit_target_ordinals": sorted(targets),
        })
        summary["integrations"].append(entry)
        if existing is not None:
            summary["already_present"] += 1
        else:
            summary["rebuilt"] += 1
    return summary


def _blocked_lineage_rows_for_integration(
    repo: WritingReferenceRepository,
    project_id: str,
    integration: ChapterIntegrationResult,
) -> list[TranslationChunkRecord]:
    """Blocked-status lineage rows bound to one integration's chapter.

    Evaluation reads the row's OWN stored source_text (identity was
    established when the row landed), so evidence stays replayable even
    after the deterministic chunker changes (round23 truncation fix
    re-split the over-limit single-paragraph branch).
    """
    rows = [
        chunk
        for chunk in repo.translation_chunks_for_plan(
            project_id, integration.plan_id
        )
        if chunk.status == "blocked"
        and chunk.chapter_id == integration.chapter_id
    ]
    if len(rows) == 1:
        return rows
    if not rows:
        # Research-scoped chapters may carry a span/batch suffix on the
        # integration chapter id while the lineage row keeps the base id.
        rows = [
            chunk
            for chunk in repo.translation_chunks_for_plan(
                project_id, integration.plan_id
            )
            if chunk.status == "blocked"
            and integration.chapter_id.startswith(
                chunk.chapter_id
            )
        ]
    return rows


def reeval_evidence(
    repo: WritingReferenceRepository,
    project_id: str,
    *,
    integration_ids: list[str] | None = None,
    actor: str = "offline_lineage_reeval",
) -> dict:
    """Unit-level confirmed/overturned/unverifyable evidence — report only.

    Never flips any ``generation_status``; the only write is the append-only
    ``blocked_fidelity_reeval_evidence`` audit event per integration.
    Units are re-derived from the lineage row's OWN stored source_text with
    the unchanged unit splitter, so stored ``unit_N:`` code ordinals keep
    their meaning even if the chunk splitter changes later.
    """
    integrations = _load_blocked_integrations(repo, project_id, integration_ids)
    report: dict[str, Any] = {
        "command": "reeval-evidence",
        "project_id": project_id,
        "scanned": len(integrations),
        "unit_verdict_totals": {"confirmed": 0, "overturned": 0, "unverifyable": 0},
        "integrations": [],
    }
    for integration in integrations:
        entry: dict[str, Any] = {
            "integration_id": integration.integration_id,
            "plan_id": integration.plan_id,
            "chapter_id": integration.chapter_id,
            "stored_codes": list(integration.fidelity_failure_codes or []),
        }
        codes = list(integration.fidelity_failure_codes or [])
        failed_ordinals = _failed_ordinals(codes)
        verdicts: dict[str, str] = {}
        replayed_codes: set[str] = set()
        unit_reasons: dict[str, str] = {}
        lineage_chunk_id = ""
        lineage_strategy = ""
        if not failed_ordinals:
            entry["outcome"] = "unverifyable"
            entry["reason"] = "no_unit_scoped_failure_codes"
        else:
            rows = _blocked_lineage_rows_for_integration(
                repo, project_id, integration)
            if len(rows) != 1:
                entry["outcome"] = "unverifyable"
                entry["reason"] = (
                    "blocked_lineage_row_missing" if not rows
                    else "ambiguous_blocked_lineage_rows")
            else:
                row = rows[0]
                lineage_chunk_id = row.chunk_id
                lineage_strategy = row.translation_strategy
                if row.hy_mt2_input_hash and row.hy_mt2_input_hash != (
                    hashlib.sha256(
                        (row.source_text or "").encode("utf-8")).hexdigest()
                ):
                    entry["outcome"] = "unverifyable"
                    entry["reason"] = "lineage_source_identity_mismatch"
                else:
                    units = split_source_into_units(row.source_text or "")
                    unit_by_ordinal = {unit.ordinal: unit for unit in units}
                    for ordinal in failed_ordinals:
                        key = str(ordinal)
                        unit = unit_by_ordinal.get(ordinal)
                        if unit is None:
                            verdicts[key] = "unverifyable"
                            unit_reasons[key] = (
                                "failed_ordinal_outside_lineage_source")
                            continue
                        target = (row.unit_targets or {}).get(key, "")
                        if not target.strip():
                            verdicts[key] = "unverifyable"
                            unit_reasons[key] = "unit_target_missing_in_lineage"
                            continue
                        unit_codes = list(
                            evaluate_translation_fidelity_aligned_units(
                                (unit,), {ordinal: target}
                            )
                        )
                        if unit_codes:
                            verdicts[key] = "confirmed"
                            replayed_codes.update(unit_codes)
                        else:
                            verdicts[key] = "overturned"
                    entry["outcome"] = (
                        "evidence_produced" if verdicts else "unverifyable")
                    if not verdicts:
                        entry["reason"] = "no_verdictable_failed_units"
        entry.update({
            "lineage_chunk_id": lineage_chunk_id,
            "lineage_strategy": lineage_strategy,
            "unit_verdicts": verdicts,
            "unit_reasons": unit_reasons,
            "replayed_codes": sorted(replayed_codes),
        })
        for verdict in verdicts.values():
            report["unit_verdict_totals"][verdict] += 1
        if verdicts:
            with repo._connect() as connection:
                repo._append_audit(
                    connection,
                    project_id,
                    "blocked_fidelity_reeval_evidence",
                    integration.integration_id,
                    actor,
                    {
                        "lineage_chunk_id": lineage_chunk_id,
                        "lineage_strategy": lineage_strategy,
                        "stored_codes": entry["stored_codes"],
                        "replayed_codes": entry["replayed_codes"],
                        "unit_verdicts": verdicts,
                        "evidence_only": True,
                        "generation_status_flipped": False,
                    },
                )
                connection.commit()
        report["integrations"].append(entry)
    return report


def medical_queue(db_path: Path, project_id: str | None = None) -> dict:
    """Read-only fidelity_blocked disposition queue (SQLite immutable=1)."""
    connection = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        query = (
            "SELECT payload_json FROM writing_reference_translation_batch_items"
            " WHERE tenant_id=? AND generation_status='fidelity_blocked'"
        )
        params: list[Any] = [TENANT_ID]
        if project_id:
            query += " AND project_id=?"
            params.append(project_id)
        query += " ORDER BY project_id, batch_id, item_id"
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()
    items = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        items.append({
            "item_id": payload.get("item_id", ""),
            "project_id": payload.get("project_id", ""),
            "batch_id": payload.get("batch_id", ""),
            "nct_id": payload.get("nct_id", ""),
            "artifact_id": payload.get("artifact_id", ""),
            "chapter_id": payload.get("chapter_id", ""),
            "attempt": payload.get("attempt"),
            "translation_id": payload.get("translation_id", ""),
            "translation_revision": payload.get("translation_revision"),
            "fidelity_failure_codes": list(
                payload.get("fidelity_failure_codes") or []),
        })
    by_project: dict[str, int] = {}
    for item in items:
        by_project[item["project_id"]] = by_project.get(item["project_id"], 0) + 1
    return {
        "command": "medical-queue",
        "db": str(db_path),
        "project_id": project_id,
        "read_only": True,
        "count": len(items),
        "by_project": dict(sorted(by_project.items())),
        "items": items,
    }


def _emit(payload: dict, output: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if output is not None:
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Zero-model blocked-chunk lineage rebuild / evidence / queue")
    parser.add_argument(
        "command",
        choices=["rebuild", "reeval-evidence", "medical-queue"])
    parser.add_argument(
        "--db", required=True, type=Path,
        help="writing_reference.sqlite3 path (explicit; no default target)")
    parser.add_argument(
        "--project", required=True, help="project_id scope")
    parser.add_argument(
        "--integration-id", action="append", default=None,
        help="restrict rebuild/reeval to specific integration ids (repeatable)")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--actor", default="offline_lineage_tool")
    args = parser.parse_args(argv)

    if args.command == "medical-queue":
        payload = medical_queue(args.db, args.project)
        _emit(payload, args.output)
        return 0

    if not args.db.exists():
        parser.error(f"--db does not exist: {args.db}")
    repo = WritingReferenceRepository(args.db)
    if args.command == "rebuild":
        payload = rebuild_blocked_lineage(
            repo, args.project,
            integration_ids=args.integration_id, actor=args.actor)
    else:
        payload = reeval_evidence(
            repo, args.project,
            integration_ids=args.integration_id, actor=args.actor)
    _emit(payload, args.output)
    return 2 if payload.get("data_missing") or payload.get("scanned") == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
