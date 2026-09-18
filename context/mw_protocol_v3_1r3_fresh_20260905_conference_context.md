# Conference Context: mw_protocol_v3_1r3_fresh_20260905

Created: 2026-09-05 18:19:55 CST
Objective: Fresh independent verification of Task1R.3 real SQLite/API integration tests and two minimal error-response fixes; verify actual transaction/replay/backup/unknown-outcome coverage, no product models or services, no security-specialist additions, no live writes. Read-only review; do not claim full repository or final product acceptance.
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

- Linked execution task: `mw_protocol_v3_1r3_integration_20260905`
- Execution evidence status: `linked`
- Excluded provider/model nodes: `opencode-go/muse-spark-1.3-contributor`
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Read current plans/mw_protocol_v3_review_amendment_20260905.md and .trellis/tasks/09-05-protocol-v3-1r3/{prd,design}.md; immutable ../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md Task1R.3 only.
- Review tests/protocol_v3/integration/*.py, tests/protocol_v3/test_unknown_operation_response.py, tests/protocol_v3/test_commit_acknowledgement_loss.py; product services/api/app/protocol_workflow/{storage/sqlite.py,application/service.py,api/router.py,api/composition.py} and adjacent typed contracts as needed. Independently inspect source, not worker reasoning.
- Do not add production paths unless the user explicitly authorized reading them for this task.

## Scope

- In scope: fresh read-only assessment of persistence, transaction rollback, restart/replay, WAL-consistent backup, idempotency, HTTP error behavior and coverage sufficiency. Identify concrete missing cases or false claims. Run focused tests using exact environment below. Test-only injection replacing commit may bypass real cleanup; distinguish artificial test mechanics from product defects. Postcommit acknowledgement-loss check must genuinely commit before failure.
- Out of scope: new security engineering/testing, models/OCR/translation/network/Word, live workbench/monitoring, external SOPs, installs, services, source edits, cleanup, archives or task closure. Existing full-repository debt is outside this bounded verdict and remains open before P1R-G1. No test count substitutes whole-product acceptance.
- Allowed writes: new pytest tmp databases and new review evidence under runs/mw_protocol_v3_1r3_fresh_20260905/ only; runner owns its report/log. Do not edit tests/product/config. Never run start_stable_backend.zsh or an unconfigured app.main import. Existing actual-main tests configure isolated runtime; legacy sweeper is baseline, not a new v3 worker.
- Test command: env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=services/api:packages:. WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/integration tests/protocol_v3/test_unknown_operation_response.py tests/protocol_v3/test_commit_acknowledgement_loss.py -q -p no:cacheprovider
- Current Codex broad receipt runs/mw_protocol_v3_1r_integration_20260905/1r3_final_codex_regression.xml exists; verify independently rather than trust summary. No need rerun full repository (known unrelated collection errors).

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

- 2026-09-05 18:19:55 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
