# Task Context: mw_protocol_v3_1r4_result_storage_20260905

Created: 2026-09-05 18:44:48
Objective: Implement only Task1R.4 durable result-store consolidation with legacy compatibility in isolated product SQLite and dedicated tests. Preserve historical rows and identifiers, distinguish received from consumed, support standalone results without inventing dispatch requests, no dual-write authority. Read Trellis1R.4 and current amendments. No security-specialist work, no product calls, no live writes or cleanup. Remaining reservation/hash changes are separate work.
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `opencode-go` / `muse-spark-1.3-contributor` / `xhigh`

## Trigger Reason

Codex selected a bounded execution or review unit under the applicable task contract. Record the concrete delegation benefit or independent-review requirement; step count and file format alone are not triggers.

## Source Of Truth

- Read .trellis/tasks/09-05-protocol-v3-1r4/{prd,design,implement}.md, plans/mw_protocol_v3_review_amendment_20260905.md, storage/sqlite.py and related ports/events tests.1R.3 accepted in reviews/codex_conference_mw_protocol_v3_1r3_fresh_20260905_review.md.
- Do not add production paths unless the user has explicitly authorized reading them for this task.

## Scope

- In scope: result-store consolidation only. Allowed source edits services/api/app/protocol_workflow/storage/sqlite.py; new tests/protocol_v3/test_result_storage_consolidation.py; new evidence under runs/mw_protocol_v3_1r4_result_storage_20260905/. Everything else read-only. Report any needed extra source change, do not improvise ownership.
- Use additive outbox result storage for paired results, retain compatibility port. Preserve standalone result compatibility without fake dispatch metadata. Preserve historical inbox rows unchanged as evidence; do not dual-write competing authorities. Explain chosen minimal representation. Received and consumed remain distinct. New reads/updates must respect migrated state. No deletes/drops/renames of history.
- Out of scope: contracts/reservations/hash changes, new security tests, live/monitoring/externalSOP/global changes, model/OCR/translation/Word/network calls, services, installs, cleanup/archive, task closure. Do not modify legacy tests/fixtures or expected values; report stage/schema assertion failures for Codex disposition.

## Success Criteria

- Write real failing tests first, implement minimal SQLite change, validate migration repeatability, preserved IDs/rows, paired and standalone results, hash conflict, consumed restart replay and no duplicate effects. Preserve existing port behavior; no extra platform.
- Run focused new tests then tests/protocol_v3. Use exact env: env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=services/api:packages:. WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_result_storage_consolidation.py -q -p no:cacheprovider
- Do not run full repository (known historical collection debt). No actual model calls. Synthetic temp DBs only. Read existing tests for schema fingerprint/migration expectations; do not hide failures. Report exact source changes, red/green receipts, remaining incompatibilities; worker cannot accept own task.

## Risk Boundaries

- Do not write to production paths until Codex review gate passes and writable paths are explicit.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, malformed output, or a stale/incomplete catalog must be recorded and followed by one real route attempt. Explicit user-selected routes are not blocked merely because the catalog does not list them; only a missing executable or native transport boundary may stop before that attempt.

## Loop Log

- 2026-09-05 18:44:48: Task initialized by `tools/hermes_workflow_guard.py init-task`.
