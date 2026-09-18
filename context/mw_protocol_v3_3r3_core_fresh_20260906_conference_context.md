# Conference Context: mw_protocol_v3_3r3_core_fresh_20260906

Created: 2026-09-06 03:21:48 CST
Objective: Independently review only the new chapter registry core and its CLI/functional fixtures against Task 3R.3; distinguish deterministic completeness from clinical authorship and find reproducible false acceptance or false rejection. No product calls or writes to source.
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

- Linked execution task: `mw_protocol_v3_3r3_registry_core_20260906`
- Execution evidence status: `linked`
- Excluded provider/model nodes: `zcode/glm-5.3-flash`
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Read .trellis/tasks/09-06-protocol-v3-3r3/{prd,design,implement}.md for original task boundaries.
- Read accepted v2 schema in packages/contracts/workbench_contracts/protocol_v3.py
  (all v2 types); registries/loader.py for existing conventions.
- Review services/api/app/protocol_workflow/registries/chapters.py and
  scripts/qc/protocol_v3/lint_chapter_registry.py completely.
- Read tests/protocol_v3/test_all_chapter_contracts.py and
  runs/mw_protocol_v3_3r3_registry_core_20260906/test_codex_registry_obligations.py.
- Accepted source identity/coverage: config/medical_writing/protocol_v3/templates/tp_ma_07_v2/
  {template,node_tree,v1_to_v2_mapping}.json, read only. Derive coverage, do not
  substitute legacy leaf counts. Cover carrier is v2_front_block in accepted mapping.
- Do not read worker reports or other reviewers' reasoning. Form an independent
  judgment of current code. Main and worker changes are both subject to review.
- Do not add production paths unless the user explicitly authorized reading them for this task.

## Scope

- In scope: typed loader/skill I/O, deterministic content evaluation, cross-registry
  consistency, CLI fixture-oracle behavior, sufficient minimal reusable core for
  later chapter authoring. Find reproducible wrong acceptance/rejection, not
  stylistic preferences. Return ACCEPT or REVISE for this infrastructure only.
- Out of scope: authoring111 actual carriers/clinical examples, model calls,
  server/network use, external files, source edits, security features/tests,
  actual clinical or native Word acceptance. Missing actual registry batches are
  known remaining3R3 work, not falsely completed by this subtask.
- You may create NEW diagnostic tests/evidence only under
  runs/mw_protocol_v3_3r3_core_fresh_20260906/ or temporary pytest directories.
  No editing/deleting existing source/tests/evidence. No main.py imports, services,
  installation, credentials or runtime DB access. Preserve all previous artifacts.
- Run focused tests in the existing venv only, with a sanitized environment:
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
  PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_all_chapter_contracts.py
  tests/protocol_v3/test_chapter_contract_schema.py
  tests/protocol_v3/test_registry_loading.py
  runs/mw_protocol_v3_3r3_registry_core_20260906/test_codex_registry_obligations.py
  -q -p no:cacheprovider --tb=short
- User requires continuous implementation; your result does not close3R3 or pause
  the Goal. No need to request routine implementation decisions from the user.

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

- 2026-09-06 03:21:48 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.

## Same-session follow-up request after REVISE

Continue in the same reviewer session; return the same complete report schema.
Re-read current chapters.py, CLI, worker test and the two Codex test files below;
no source edits. Main froze these after the following correction; review the
implementation independently and reproduce your findings against the changed
code. Your previous report remains immutable, not overwritten.

Decisions resolved by original PRD, no new user choice required:
- Full completion requires all four fixture families per carrier. Partial mode
  permits absent families but rejects invalid present fixtures. LintReport owns
  the result; --check-fixtures is display only, never a validation bypass.
- missing_control expectation derives from the contract's actual required facts,
  claims, evidence and object/cell obligations. wrong_source needs an actual
  source-floor diagnostic, not merely an unrelated missing fact.
- Conditional rules can themselves declare conditional requirements, so requiring
  a duplicate unconditional requirement is not intended. Their references must
  resolve in vocabulary and remain noncontradictory; semantic activation is
  explicitly deferred, not declared evaluated by this infrastructure. Chapter
  authorship/runtime QC must still implement applicable project behavior.

New review target: runs/mw_protocol_v3_3r3_registry_core_20260906/test_codex_fixture_acceptance.py
Five red probes reproduced fixtureless/poisoned/defaultCLI/controlclaim defects
and an additional arbitrary-cover-ID false acceptance. Current code resolves the
real cover from the accepted mapping, and always evaluates fixtures in the library.
The previously fixtureless synthetic full-positive tests now contain actual four-
family control fixtures and relevant synthetic project-control evidence. Existing
assertions/expected values are unchanged; no negative fixture was removed. Verify
the helper remains honest and these positive cases still test what they claim.

Run the previously instructed four test files plus this new fifth file. Main's
latest result is96passed3.43s, but do not substitute that result for your review.
No actual clinical chapter authoring or source promotion is claimed; disposition
is for the reusable core only. No new security features/tests or product calls.
