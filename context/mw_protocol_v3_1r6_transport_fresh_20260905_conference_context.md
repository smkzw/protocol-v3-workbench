# Conference Context: mw_protocol_v3_1r6_transport_fresh_20260905

Created: 2026-09-05 20:38:08 CST
Objective: Independent offline review of Protocol v3 Task 1R.6 GLM product transport, default/confirmed alternative profiles and read-only omp credential resolver. Verify actual implementation and focused tests; no network/model calls, no credential store reads, no product edits, no services. Report concrete functional defects and scope limitations. Source and allowed evidence paths in conference context.
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

- Linked execution task: `mw_protocol_v3_1r6_glm_transport_20260905`
- Execution evidence status: `linked`
- Excluded provider/model nodes: `zcode/glm-5.3-flash`
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Read .trellis/tasks/09-05-protocol-v3-1r6/{prd,design,implement}.md.
- Read services/api/app/protocol_workflow/runtime/adapters/{direct_api,zhipu_api}.py,
  runtime/{omp_credentials,product_profiles,harness}.py, registries/loader.py
  (runtime and registries relative to services/api/app/protocol_workflow).
- Read config/medical_writing/protocol_v3/role_registry{,.deepseek}.json and
  tests/protocol_v3/test_{zhipu_product_transport,product_profiles,omp_credential_binding,registry_loading,harness_policy}.py.
- Source-only review: do not read worker reports/reasoning or credential stores.
  No internet is needed. Official endpoint/effort references are in design.md;
  actual product probe remains Codex-owned and has not run.

## Scope

- In scope: functional composition, first-use probe, request material completeness,
  output receipt semantics, default versus explicitly selected alternative,
  synthetic readonly credential selection, typed failures and tests.
- Run focused offline pytest using runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python;
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin
  HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/
  LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
  PYTHONPATH=services/api:packages:. WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false.
  Disable pytest cache. Synthetic extra probes/evidence may be written only under
  runs/mw_protocol_v3_1r6_transport_fresh_20260905/; never write runner report.
- Out of scope: all product source/test edits, full legacy regression, services,
  network/model/OCR/translation calls, global credential/config access, monitoring,
  production, sibling workbench/plan-upgrade, new security engineering or tests.
- Do not close the task. Distinguish real functional blockers from optional cleanup
  and later2R facade/prompt materialization integration obligations. Fresh context;
  no persuasive worker report input. Codex retains acceptance.

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

- 2026-09-05 20:38:08 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
