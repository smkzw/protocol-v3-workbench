# Conference Context: mw_protocol_v3_1r4_durable_fresh_20260905

Created: 2026-09-05 19:54:41 CST
Objective: Independent readonly review of committed SQLite reservation durability and local cross-process ownership after Codex repair; preserve scientific and functional semantics, no security-specialist work, no product model/service calls. Read task context for exact scope.
Task type: `code_open_audit`
Risk: `medium`
Conference mode: `parallel`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`general_single_object`) with no sub-venue chair. Its effective `CST` route chain is `opencode-go/muse-spark-1.3-contributor:xhigh -> codebuddy-cli/deepseek-v4-flash:max -> openai-codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_protocol_v3_1r4_durable_dispatch_20260905`
- Execution evidence status: `linked`
- Excluded provider/model nodes: `zcode/glm-5.3-flash`
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- services/api/app/protocol_workflow/storage/sqlite.py (committed-operation repository/factory and underlying reservation semantics).
- services/api/app/protocol_workflow/runtime/reservations.py (coordinator/projection).
- services/api/app/protocol_workflow/ports/repositories.py and packages/contracts/workbench_contracts/protocol_v3.py as readonly interface references.
- tests/protocol_v3/test_durable_reservation_dispatch.py, test_sqlite_reservation_lifecycle.py, test_execution_reservations.py, test_execution_reservations_adversarial.py, test_result_storage_consolidation.py, test_superseded_result_migration.py, test_reservation_result_projection.py. Inspect filenames before invoking a test; missing optional tests are not permission to broaden scope.
- Do not add production paths unless the user explicitly authorized reading them for this task.

## Scope

- In scope: independent correctness review of durable pre-dispatch claim, active ownership across real local processes/threads, genuine orphan recovery, unknown outcome non-redispatch, explicit retry history, repository close/terminal cleanup and business UoW atomicity. Evaluate current source directly, not worker narrative. Paired result consolidation is already reviewed separately; only inspect if shared changes affect it.
- Out of scope: security-specialist engineering/tests, network/models/OCR/translation, services, full repository suite, live/monitoring/production paths, immutable history edits, Git commits or cleanup. Do not read other runner reports or private execution reasoning. Do not change product or existing tests.
- Product composition is still a future typed facade task: no production coordinator entrypoint currently exists. Judge correctness of the actual committed factory, not fictitious application wiring. Raw UoW is deliberately transaction-scoped and must not autocommit caller data.
- You may create bounded synthetic probes ONLY under runs/mw_protocol_v3_1r4_durable_fresh_20260905/ using apply_patch; temp SQLite databases/processes may use the system temp directory. Process waits must be bounded and event-driven; do not launch services or call models. No runner-owned report writes.
- Run focused tests with this environment: env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=services/api:packages:.:tests/protocol_v3 WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest <scoped files> -q -p no:cacheprovider.
- Source is frozen for your pass. One reviewer only, no manager or recursive dispatch. Compare claimed behavior with actual separate-process behavior and file/connection lifecycle. Report precise remaining limitations without inventing a distributed deployment requirement; this is a local personal macOS system.

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

- 2026-09-05 19:54:41 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
