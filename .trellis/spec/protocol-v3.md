# Protocol v3 project constraints

## Pre-development

Read current global AGENTS, project AGENTS, immutable design v1.3 / Plan v2 /
handoff in ../plan-upgrade-20260905 and current additive Plan in plans/.
Read the active task PRD/design/implement and frozen acceptance evidence.
The current user Goal authorizes continuous implementation; Trellis is management,
not a second route engine. Use current workflow guard for bounded engineering
workers and fresh verifiers. No auto cleanup, archival, journal commits or push.

## Scope and contracts

Only this isolated checkout is writable. LIVE workbench, monitoring, 8910,
external SOPs and plan-upgrade are protected. Historical evidence stays in place.
SQLite is the product backend; memory is explicit test-only. Product imports must
not depend on pocs. Preserve CAS, same-transaction event/outbox, logical-key
deduplication, stale-input checks, unknown-outcome reconciliation and old rows.
Task 1R.4 simplifies implementation while retaining those functional semantics.

## Quality check

Write failing tests before changes; do not hide real defects with changed expected
values or xfail. User approves superseding obsolete no-main-mount and schema-v1
stage assertions. Other obsolete constraints may be retired after recording their
scientific/functional impact and replacement check; no repeated approval needed.
Task 1R.5 security engineering/tests are USER_EXCLUDED, not PASS. No new security
specialist gates, engineering or tests; these are not implementation stop points.
Do not relabel that excluded work as functional correctness to reintroduce it.
Keep historical evidence and existing fixtures. Validate real entrypoint with temporary runtime paths and sanitized child
environment: inherited AI/role/eligibility paths can escape WORKBENCH_RUNTIME_DIR.
Never use start_stable_backend.zsh (LIVE target). Importing old main has side
effects: test with real isolated paths, distinguish baseline from new side effects.
Product models/OCR/translation/Word remain prohibited before 1R.6.
1R.6 allows the declared single minimal GLM probe; secrets remain memory-only.
No raw SQL/path/credentials in HTTP errors. Unknown outcome cannot imply safe retry.

## User-facing and document acceptance

User-approved current hard limits: <=20 critical clicks, <=5 mandatory free-text
fields, body >=14px, UI >=12px. Count applicable high-risk and native-dialog actions.
Recommended choices are preselected, not confirmed. Eight high-risk choices need
individual human confirmation bound to content; never impose arbitrary reason length.
Controlled semantic editor + readonly preview + native Word roundtrip, not a Word
layout engine in browser. TP-MA-07 clean v2.0 is II/III authority; leaf obligations,
cross-chapter consistency, source traceability and native Word receipts remain gates.
Real browser/Word/product acceptance is separate from deterministic test results.
Stop for Task 3R.6, production activation, real cutover or material unresolved choice.

## Evidence

Accepted 1R.1: reviews/codex_mw_protocol_v3_1r1_storage_gate_20260905.md.
Historical checkpoint: runs/MW_PROTOCOL_V3_1R1_NO_LOSS_DECISION_WAIT_20260905_1540.md.
PyMuPDF decision there is superseded: user permits personal local use.
Next task 1R.2 mounts actual main router default-off with durable project allowlist.
Do not repeat accepted R/1R.1 except relevant drift or new regression concerns.
