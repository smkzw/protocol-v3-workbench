# Conference Context: mw_protocol_v3_2r1_fresh_20260905

Created: 2026-09-05 22:57:23 CST
Objective: Fresh read-only review of frozen Task2R.1 typed runtime, actual three-case recovery and concurrent decision semantics; identify concrete functional defects and minimal repairs. No product calls or source writes.
Task type: `code_open_audit`
Risk: `high`
Conference mode: `parallel`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`general_single_object`) with no sub-venue chair. Its effective `CST` route chain is `opencode-go/muse-spark-1.3-contributor:xhigh -> codebuddy-cli/deepseek-v4-flash:max -> openai-codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_protocol_v3_2r1_typed_facade_20260905`
- Execution evidence status: `linked`
- Excluded provider/model nodes: `zcode/glm-5.3-flash`
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Read .trellis/tasks/09-05-protocol-v3-2r1/{prd,design,implement}.md and the
  2R.1 section of plans/mw_protocol_v3_review_amendment_20260905.md.
- Frozen artifacts: services/api/app/protocol_workflow/graph/*.py,
  pocs/protocol_v3/orchestrator/typed_facade.py, the accepted cases/fakes,
  tests/protocol_v3/test_graph_runtime{,_recovery}.py and
  pocs/protocol_v3/orchestrator/tests/test_typed_facade.py.
- Read existing storage/sqlite.py, runtime/reservations.py, contracts/protocol_v3.py
  and relevant product ports as needed. Do not read worker reports or private
  reasoning. Code/test artifacts are the review object.

## Scope

- In scope: independent functional correctness review, synthetic temporary-SQLite
  repros, actual process-death/concurrency fidelity, identity/context isolation,
  content-hash integrity and usable recovery. No new security-engineering scope.
- Out of scope: source edits, production/live reads or writes, main import,
  services, real models/OCR/translation/network, dependencies, cleanup, dispatch.
- Tests may write only fresh temporary directories and optional new evidence in
  runs/mw_protocol_v3_2r1_fresh_20260905/. Runner owns the final report.
- Use env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin
  HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/
  LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
  PYTHONPATH=tests/protocol_v3:services/api:packages:. and explicit fresh temporary
  WORKBENCH_RUNTIME_DIR. Python runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python.
  pytest -p no:cacheprovider; do not run historical unrelated full legacy suite.
- Judge three accepted cases, not only a probe graph. Detect whether race tests
  actually overlap operations and whether recovery reaches usable content. A
  fresh human decision event is not by itself proof of independent Agent4 QC.
- Return concrete file/line, reproduction/result, impact and minimal fix. Separate
  actual defects, untested paths and later router activation obligations.

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

- 2026-09-05 22:57:23 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
