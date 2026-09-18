# Conference Context: mw_protocol_v3_1r4_storage_fresh_20260905

Created: 2026-09-05 18:59:46 CST
Objective: Independently verify only Task1R.4 storage consolidation and reservation result projection against current source and original requirements. Check real SQLite migration, history, received versus consumed, duplicate effects, standalone compatibility and result API compatibility; no closure of full1R.4, no security-specialist scope, no writes to product, no model/Word/OCR/translation/live calls. Read current source not worker reasoning.
Task type: `code_open_audit`
Risk: `high`
Conference mode: `parallel`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`general_single_object`) with no sub-venue chair. Its effective `CST` route chain is `xai/grok-4.6:high -> cursor/default -> cms-router/cms-model:high -> openai-codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_protocol_v3_1r4_storage_impl_20260905`
- Execution evidence status: `linked`
- Excluded provider/model nodes: `opencode-go/muse-spark-1.3-contributor`
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Read plans/mw_protocol_v3_review_amendment_20260905.md, .trellis/tasks/09-05-protocol-v3-1r4/prd.md, services/api/app/protocol_workflow/storage/sqlite.py, runtime/reservations.py (same protocol_workflow root), ports/repositories.py, events/inbox.py and events/outbox.py, tests/protocol_v3/test_result_storage_consolidation.py, test_reservation_result_projection.py, test_execution_reservations.py, test_sqlite_product_storage.py, test_protocol_v3_1r2_mount.py. Inspect related current source as needed; do not read worker reports/reasoning.
- Do not add production paths unless the user explicitly authorized reading them for this task.

## Scope

- In scope: independent source review and real synthetic SQLite tests of paired receipt/consumption, standalone results, pre-v3 history preservation, repeated migration, hash conflict, crash/replay and no duplicate effects. Review result projection single-source truth and necessary constructor/read compatibility. Stage schema assertions have user-authorized upgrade to3/15columns; underlying rejection and history checks must remain. Report actual defects with source locations and reproductions, not speculative security architecture.
- Run focused tests using exact env: env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=services/api:packages:. WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_result_storage_consolidation.py tests/protocol_v3/test_reservation_result_projection.py tests/protocol_v3/test_execution_reservations.py -q -p no:cacheprovider. Synthetic additional probes may write only temporary test data or new evidence under runs/mw_protocol_v3_1r4_storage_fresh_20260905/. All product/test source readonly. Runner owns final report.
- Out of scope: contract-hash compaction still pending (not a failure of this bounded review), full1R.4/P1R acceptance, security-specialist engineering/tests, live/monitoring/global/SOP/readonly plan-upgrade changes, product model/OCR/translation/Word/network/service calls, installs, cleanup/archive. Current Codex edits are frozen during review. No task closure by reviewer.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No production path is read or modified; Codex retains final acceptance.

## Parallel Work Rule

For logic-heavy, rigor-sensitive, or artifact-heavy tasks, each participant independently runs the whole bounded workflow and writes a separate output. Leads compare after all available participant outputs are in or explicitly marked pending.

## Timeout Policy

- Participant soft wait: 60 minutes.
- Large-task participant wait: 120 minutes.
- Chair hard wait: 120 minutes.
- Failure rule: Do not fail a model for slow response alone; fail only on terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no useful progress after the high-budget same-session recovery loop. A catalog/auth/transport health preflight timeout or malformed response is diagnostic and must still allow one live route attempt; explicit user routes also proceed when the catalog is stale or incomplete, while a genuinely missing CLI or native transport boundary may block. If a resumable session exists after a step/size boundary, continue it before fallback; repeated identical output/tool evidence triggers the no-progress breaker.
- Pass/turn boundary: one conference prompt is one conference pass. The
  `--max-turns` value controls internal Agent tool-calling turns and is never
  set to 1 for substantive conference execution; generated participant and
  chair commands use the route budgets recorded by the guard.

## Risk Boundaries

- External Agents are advisory; Codex remains final authority.
- Codex owns visual/browser/PPT/PDF/rendered checks, live authority checks, final clinical/regulatory conclusions, and production writes.
- Do not mark a slow model failed solely due to latency.

## Loop Log

- 2026-09-05 18:59:46 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
