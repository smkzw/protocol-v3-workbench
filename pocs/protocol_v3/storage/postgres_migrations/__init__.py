"""PostgreSQL 18 migration for the Protocol v3 storage PoC — Task 1.8.

Idempotent, auditable DDL for the task-local disposable PostgreSQL 18 cluster.
It creates the persisted families exercised by the database-neutral common
contract suite (``pocs/protocol_v3/storage/contract_suite.py``):

* ``aggregate_revision``  — versioned canonical aggregates + revision CAS
* ``event_stream``        — append-only event chain (PK on (project, stream, seq),
  UNIQUE on domain_event_id, NOT NULL chain hash)
* ``outbox_message``      — transactional outbox (UNIQUE (project, logical_key))
* ``inbox_result``        — idempotent inbox (UNIQUE (project, logical_key))
* ``execution_reservation``— exactly-once reservations with two UNIQUE partials
* ``read_chapter_coverage`` / ``read_decision_graph`` / ``read_workflow_run_status``
  — CQRS read-model projections
* ``checkpoint_record``   — persisted checkpoint namespace (PK (project, run))
* ``quarantine_record``   — explicit quarantine store (PK (family, source_key))
* ``schema_version``      — auditable migration ledger

Concurrency is enforced by database CAS/unique constraints, not by an
application-wide serialization lock:

* CAS: CAS semantics are guarded by the ``MAX(revision)`` read inside the
  transaction plus the composite PRIMARY KEY ``(aggregate_kind, project_id,
  aggregate_id, revision)`` — two writers cannot persist the same revision.
* Event chain: ``PRIMARY KEY (project_id, stream_id, sequence)`` and
  ``UNIQUE (project_id, stream_id, domain_event_id)`` prevent duplicate
  sequences and duplicate event ids.
* Transaction + outbox atomicity: the adapter commits the CAS save and the
  outbox enqueue in the ONE PostgreSQL transaction (no application lock).

The migration is idempotent: every ``CREATE TABLE IF NOT EXISTS`` is safe to
re-run, and the ledger row is upserted.  It is a PoC migration — it is NOT a
product or deployment migration (those are owned by Worker 03 / Codex after
selection).
"""

from __future__ import annotations

#: Migration ledger version.  Bumped when the schema changes.
SCHEMA_VERSION = 1

#: Ordered list of ``(filename, SQL)`` migration steps.  The runner applies
#: each step inside its own transaction and records it in ``schema_version``.
#: Splitting into separate files would be over-engineering for a single-version
#: PoC schema; the single auditable module is kept here for clarity.
MIGRATION_STEPS: list[tuple[str, str]] = [
    (
        "001_base_schema",
        """
        CREATE TABLE IF NOT EXISTS aggregate_revision (
            aggregate_kind   TEXT    NOT NULL,
            project_id       TEXT    NOT NULL,
            aggregate_id     TEXT    NOT NULL,
            revision         INTEGER NOT NULL,
            body_json        TEXT    NOT NULL,
            previous_revision_sha256 TEXT,
            PRIMARY KEY (aggregate_kind, project_id, aggregate_id, revision)
        );

        CREATE TABLE IF NOT EXISTS event_stream (
            project_id       TEXT    NOT NULL,
            stream_id        TEXT    NOT NULL,
            sequence         INTEGER NOT NULL,
            domain_event_id  TEXT    NOT NULL,
            body_json        TEXT    NOT NULL,
            previous_event_sha256 TEXT,
            event_sha256     TEXT    NOT NULL,
            PRIMARY KEY (project_id, stream_id, sequence),
            UNIQUE (project_id, stream_id, domain_event_id)
        );

        CREATE TABLE IF NOT EXISTS outbox_message (
            outbox_message_id TEXT    NOT NULL PRIMARY KEY,
            project_id        TEXT    NOT NULL,
            workflow_run_id   TEXT    NOT NULL,
            side_effect_kind  TEXT    NOT NULL,
            logical_key       TEXT    NOT NULL,
            payload_sha256    TEXT    NOT NULL,
            status            TEXT    NOT NULL,
            created_at        TEXT    NOT NULL,
            dispatched_at     TEXT,
            completed_at      TEXT,
            attempt           INTEGER NOT NULL DEFAULT 0,
            error_detail      TEXT,
            UNIQUE (project_id, logical_key)
        );

        CREATE TABLE IF NOT EXISTS inbox_result (
            inbox_result_id TEXT    NOT NULL PRIMARY KEY,
            project_id      TEXT    NOT NULL,
            logical_key     TEXT    NOT NULL,
            result_sha256   TEXT    NOT NULL,
            status          TEXT    NOT NULL,
            received_at     TEXT    NOT NULL,
            consumed_at     TEXT,
            UNIQUE (project_id, logical_key)
        );

        CREATE TABLE IF NOT EXISTS execution_reservation (
            execution_reservation_id TEXT    NOT NULL PRIMARY KEY,
            project_id               TEXT    NOT NULL,
            node_execution_contract_id TEXT NOT NULL,
            logical_call_id          TEXT    NOT NULL,
            idempotency_key          TEXT    NOT NULL,
            input_sha256             TEXT    NOT NULL,
            attempt                  INTEGER NOT NULL,
            transport_attempts       INTEGER NOT NULL DEFAULT 0,
            provider_session_id      TEXT,
            status                   TEXT    NOT NULL,
            terminal_state           TEXT,
            output_sha256            TEXT,
            error_code               TEXT,
            reserved_at              TEXT    NOT NULL,
            updated_at               TEXT    NOT NULL,
            UNIQUE (project_id, logical_call_id, idempotency_key),
            UNIQUE (project_id, logical_call_id, attempt)
        );

        CREATE TABLE IF NOT EXISTS read_chapter_coverage (
            project_id              TEXT NOT NULL,
            semantic_document_revision_id TEXT NOT NULL,
            semantic_node_id        TEXT NOT NULL,
            chapter_contract_sha256 TEXT,
            substantive_content_contract_sha256 TEXT,
            semantic_block_sha256   TEXT,
            is_locked               INTEGER NOT NULL,
            has_substantive_content INTEGER NOT NULL,
            evidence_admitted       INTEGER NOT NULL,
            PRIMARY KEY (project_id, semantic_document_revision_id, semantic_node_id)
        );

        CREATE TABLE IF NOT EXISTS read_decision_graph (
            project_id        TEXT NOT NULL,
            study_definition_id TEXT NOT NULL,
            decision_key      TEXT NOT NULL,
            decision_record_id TEXT,
            state_revision    INTEGER,
            selected_option_id TEXT,
            canonical_state   TEXT,
            PRIMARY KEY (project_id, study_definition_id, decision_key)
        );

        CREATE TABLE IF NOT EXISTS read_workflow_run_status (
            project_id       TEXT NOT NULL,
            workflow_run_id  TEXT NOT NULL,
            status           TEXT NOT NULL,
            display_progress REAL NOT NULL,
            journey_counter  INTEGER NOT NULL,
            PRIMARY KEY (project_id, workflow_run_id)
        );

        CREATE TABLE IF NOT EXISTS checkpoint_record (
            project_id      TEXT NOT NULL,
            run_id          TEXT NOT NULL,
            stream_id       TEXT NOT NULL,
            checkpoint_seq  INTEGER NOT NULL,
            checkpoint_sha  TEXT NOT NULL,
            state           INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (project_id, run_id)
        );

        CREATE TABLE IF NOT EXISTS quarantine_record (
            family       TEXT NOT NULL,
            source_key   TEXT NOT NULL,
            reason_code  TEXT NOT NULL,
            body_hash    TEXT NOT NULL,
            body         TEXT NOT NULL,
            PRIMARY KEY (family, source_key)
        );
        """,
    ),
    (
        "002_migration_ledger",
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER NOT NULL PRIMARY KEY,
            applied_at  TEXT    NOT NULL,
            note        TEXT
        );
        """,
    ),
]