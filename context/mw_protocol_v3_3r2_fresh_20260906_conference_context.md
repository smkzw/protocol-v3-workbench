# Conference Context: mw_protocol_v3_3r2_fresh_20260906

Created: 2026-09-06 02:32:21 CST
Objective: Independent read-only acceptance review of Task3R.2 explicit v2 chapter contracts against original PRD and unchanged v1 serialization. Verify substantive non-vacuity, conditional applicability, Word/object/evidence requirements, and compatibility; no product calls or edits.
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

- Linked execution task: `mw_protocol_v3_3r2_contracts_20260906`
- Execution evidence status: `linked`
- Excluded provider/model nodes: `zcode/glm-5.3-flash`
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Read fully .trellis/tasks/09-06-protocol-v3-3r2/prd.md, design.md, implement.md.
- Read the current packages/contracts/workbench_contracts/protocol_v3.py v2 section
  and all relevant base/v1 definitions, and FULL tests/protocol_v3/test_chapter_contract_schema.py.
- Original requirements: .hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md
  Task3.2 only. The PRD is the current additive-v2 clarification preserving v1.
- Existing tests/protocol_v3/test_contract_models.py and downstream reducer/repository
  tests; runs/mw_protocol_v3_3r2_contracts_20260906/v1_fixtures_before.json and
  v1_fixtures_after.json are serialization/schema evidence, not acceptance opinions.
- Do not read worker reports, private reasoning, other reviews or production.

## Scope

- In scope: independent schema and compatibility review of the two changed files.
  Test positive AND negative obligations, non-vacuity, conditional contradictions,
  object/cell detail coverage, source roles and metadata provenance, lifecycle,
  dependency/repair, CtQ and patient-participation schema usefulness for reusable
  chapter contracts. Distinguish static contract schema from actual document QC.
- Out of scope: implementation, security features, frontend, model probes, credentials,
  OCR/translation, live services, task closure, native Word/clinical acceptance.
- Return ACCEPT or REVISE with exact file/line/reproduction and minimal remedies.
  Submodule imports are acceptable; root reexports are not required for this task.
  Patient-participation is approved product traceability, not a claim of a literal
  ICH mandate to record nonparticipation reasons. No arbitrary reason length.
- Allowed deterministic test command (no services/network):
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_contract_schema.py tests/protocol_v3/test_contract_models.py
  tests/protocol_v3/test_semantic_document_reducer.py tests/protocol_v3/test_repository_contract.py
  tests/protocol_v3/test_repository_backends.py -q -p no:cacheprovider --tb=short
  (Join as one shell command.) Read-only in-memory counterexample scripts allowed.

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

- 2026-09-06 02:32:21 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
