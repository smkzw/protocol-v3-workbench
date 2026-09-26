"""G3 coverage probe (READ-ONLY, evidence script — stays out of product code).

Opens the isolated runtime writing_reference.sqlite3 in SQLite URI mode=ro
and classifies every fidelity_blocked translation item by the NEW binding
chain (item.translation_id/translation_revision ->
WritingReferenceTranslationRevision.chapter_integration_result_id ->
chapter integration row -> completed chunks with unit targets).

It NEVER writes and never executes the phase-2 flip path (red line 2/3):
classification only, counts only.

Usage: python3 g3_coverage_probe.py <sqlite-path>
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

TENANT_ID = "t_en9KvlkaGoWdDGJyqCXQfD"  # not used for ro classification


def classify(item: dict, cur: sqlite3.Cursor, tenant_id: str) -> tuple[str, str]:
    generation_status = item.get("generation_status")
    if generation_status != "fidelity_blocked":
        return ("skip_not_blocked", "")

    translation_id = str(item.get("translation_id") or "")
    revision = int(item.get("translation_revision") or 0)
    if not translation_id or not revision:
        return ("data_missing", "no_translation_link_on_item")

    row = cur.execute(
        """
        SELECT payload_json FROM writing_reference_translation_records
        WHERE tenant_id=? AND project_id=? AND translation_id=? AND revision=?
        """,
        (tenant_id, item.get("project_id"), translation_id, revision),
    ).fetchone()
    if row is None:
        return ("data_missing", "translation_revision_row_missing")
    revision_payload = json.loads(row["payload_json"])
    integration_id = str(
        revision_payload.get("chapter_integration_result_id") or "")
    if not integration_id:
        return ("data_missing", "no_chapter_integration_result_id_on_revision")

    irow = cur.execute(
        """
        SELECT payload_json FROM writing_reference_chapter_integration_results
        WHERE tenant_id=? AND project_id=? AND integration_id=?
        """,
        (tenant_id, item.get("project_id"), integration_id),
    ).fetchone()
    if irow is None:
        return ("data_missing", "integration_row_missing")

    integration = json.loads(irow["payload_json"])
    if str(integration.get("blocked_raw_provider_output") or "").strip():
        return ("data_missing", "hy_blocked_raw_fragment")
    chunk_ids = list(integration.get("chunk_ids") or [])
    if not chunk_ids:
        return ("data_missing", "integration_chunk_list_empty")

    missing_chunks = 0
    missing_targets = 0
    incomplete_chunks = 0
    for chunk_id in chunk_ids:
        crow = cur.execute(
            """
            SELECT payload_json FROM writing_reference_translation_chunks
            WHERE tenant_id=? AND project_id=? AND chunk_id=?
            """,
            (tenant_id, item.get("project_id"), chunk_id),
        ).fetchone()
        if crow is None:
            missing_chunks += 1
            continue
        chunk = json.loads(crow["payload_json"])
        if chunk.get("status") != "completed":
            incomplete_chunks += 1
            continue
        if not str(chunk.get("source_text") or "").strip() or not str(
                chunk.get("translated_text") or "").strip():
            incomplete_chunks += 1
            continue
        if not chunk.get("unit_targets"):
            missing_targets += 1
    if missing_chunks:
        return ("data_missing", "chunk_row_missing")
    if incomplete_chunks:
        return ("data_missing", "chunk_incomplete")
    if missing_targets:
        return ("data_missing", "unit_targets_incomplete")
    return ("reevaluable", "chain_complete")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: g3_coverage_probe.py <sqlite-path>")
        return 2
    db_path = Path(sys.argv[1])
    uri = f"file:{db_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    # guard: this connection must stay read-only
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS _ro_probe(x)")
        print("ERROR: connection is writable; aborting")
        return 3
    except sqlite3.OperationalError:
        pass

    tenant_row = connection.execute(
        "SELECT tenant_id FROM writing_reference_translation_batch_items LIMIT 1"
    ).fetchone()
    tenant_id = tenant_row["tenant_id"] if tenant_row else ""

    rows = connection.execute(
        """
        SELECT payload_json FROM writing_reference_translation_batch_items
        WHERE tenant_id=? AND generation_status='fidelity_blocked'
        ORDER BY project_id, batch_id, item_id
        """,
        (tenant_id,),
    ).fetchall()

    summary: dict[str, int] = {}
    reasons: dict[str, int] = {}
    batches: dict[str, int] = {}
    for row in rows:
        item = json.loads(row["payload_json"])
        state, reason = classify(item, connection, tenant_id)
        summary[state] = summary.get(state, 0) + 1
        if state == "data_missing":
            reasons[reason] = reasons.get(reason, 0) + 1
        batches[item.get("batch_id", "?")] = batches.get(item.get("batch_id", "?"), 0) + 1

    total_rows = connection.execute(
        """
        SELECT COUNT(*) FROM writing_reference_translation_batch_items
        WHERE tenant_id=? AND generation_status='fidelity_blocked'
        """,
        (tenant_id,),
    ).fetchone()[0]

    print(json.dumps({
        "db": str(db_path),
        "read_only": True,
        "fidelity_blocked_total": total_rows,
        "classification": summary,
        "data_missing_reasons": reasons,
        "batches": batches,
    }, ensure_ascii=False, indent=2))
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
