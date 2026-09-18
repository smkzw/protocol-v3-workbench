# Conference Context: mw_protocol_v3_3r4a_review_20260912

Created: 2026-09-12 23:54:18 CST
Objective: Fresh read-only review of Task 3R.4A frozen fact transport and canonical binding implementation, against Plan v3 and current chapter sources. Identify concrete correctness failures, type fidelity loss, misleading aliases, and missing acceptance evidence. Product code is read-only; no product model, services, OCR, translation, cleanup or recursive delegation.
Task type: `code_scoped_patch_plan`
Risk: `high`
Conference mode: `serial`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`general_single_object`) with no sub-venue chair. Its effective `CST` route chain is `opencode-go/muse-spark-1.3-contributor:xhigh -> codebuddy-cli/deepseek-v4-flash:max -> openai-codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_protocol_v3_3r4a_fact_inventory_20260912`
- Execution evidence status: `linked`
- Excluded provider/model nodes: `zcode/glm-5.3-flash`
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Frozen implementation, tests, Plan and PRD: runs/mw_protocol_v3_3r4a_20260912/frozen_review/source_hashes.json and listed relative files beneath frozen_review. Read full affected definitions.
- Current source contracts: config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts; canonical StudyDefinition: packages/contracts/workbench_contracts/protocol_v3.py and services/api/app/protocol_workflow/canonical/study_definition.py.
- Functional test logs: runs/mw_protocol_v3_3r4a_20260912/empty_structures_green.log, catalog_rebuild_green_final.log. Sources and test behavior outrank test counts. Do not read prior worker/private owner reasoning reports.
- Do not add production paths unless the user explicitly authorized reading them for this task.

## Scope

- In scope: 3R.4A only: typed I/O, canonical literal keys and projections, legacy conversion, source version binding and output fact equality, reproducible catalog. Verify each mapping against source, distinguish implemented helper from integration promised in D/V1. Report severity and exact path/line with reproducer.
- Out of scope: B applicability execution, C graph propagation, D adoption and V1 product wiring are not implemented yet and must not be called complete. No product source edits, model calls, network, services, OCR/translation, secrets, cleanup/archive or recursion. You may run bounded read-only Python probes with PYTHONDONTWRITEBYTECODE=1 using runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python and PYTHONPATH=tests/protocol_v3:services/api:packages:. Return findings via runner only.

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

- 2026-09-12 23:54:18 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
