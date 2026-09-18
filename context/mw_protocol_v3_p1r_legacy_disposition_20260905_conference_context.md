# Conference Context: mw_protocol_v3_p1r_legacy_disposition_20260905

Created: 2026-09-05 21:09:09 CST
Objective: Independently review maintained legacy regression disposition and scoped fixture/product repairs. Identify whether repaired tests conceal real defects, and distinguish blockers to offline2R construction from release obligations. Source-only offline review, no network/models/services/credential reads, no production or monitoring edits; bounded context contains exact files.
Task type: `code_open_audit`
Risk: `medium`
Conference mode: `parallel`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`general_single_object`) with no sub-venue chair. Its effective `CST` route chain is `zcode/glm-5.3-flash:max -> opencode-go/muse-spark-1.3-contributor:xhigh -> codebuddy-cli/deepseek-v4-flash:max -> openai-codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_protocol_v3_p1r_legacy_disposition_20260905`
- Execution evidence status: `no linked execution packet`
- Excluded provider/model nodes: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Read plans/mw_protocol_v3_review_amendment_20260905.md and
  .trellis/tasks/09-05-protocol-v3-p1r-integration/prd.md.
- Primary runtime evidence: runs/mw_protocol_v3_1r_integration_20260905/
  maintained_legacy_complete_20260905.xml (7420pass167fail18error1skip1217.08s).
  Parse XML bounded by classname/test/message; DO NOT dump huge React tracebacks.
- Current scoped diffs (git diff only these): tests/test_ai_route_freeze.py,
  test_contracts.py,test_document_pipeline_round8.py,
  test_medical_writing_direct_ai_policy.py,test_medical_writing_durable_job_integration.py,
  test_medical_writing_study_binding_backend.py,test_medical_writing_chapter_projection.py,
  test_medical_writing_dynamic_section_matrix.py (all under tests), and
  services/api/app/medical_writing_competitor_triage.py.
- Read corresponding current source functions to challenge changed expectations:
  ai_role_runtime_settings._isolate_binding_profile; ai_execution_policy route policies;
  main.writing_reference_translation_ai_status; models.RevisionAcceptAndApplyRequest;
  medical_writing_repository._substantive_body_gaps; writing_reference_translation_batch
  structural failure recovery; medical_writing_protocol_template typed readiness;
  medical_writing_competitor_triage._sanitize_reason.
- Missing historical assets may be verified via test source and path existence:
  test_mw_final_4x3_harness.py,test_mw_final_5x3_harness.py,
  test_phase1_corpus_source_boundaries.py,test_omlx_workload_gate_contract.py.
  No external/global files or credentials permitted.

## Scope

- In scope: independent defect/obligation review, classify failures by root cause,
  verify fixture upgrades do not hide product defects; assess whether remaining
  legacy/monitoring/history failures should block offline2R construction or remain
  explicit release obligations. Codex has NOT declared full repositoryPASS.
- Run only focused synthetic tests of above changes; no fulllegacyrerun. Use
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest -q
  -p no:cacheprovider --tb=short with env -i PATH=/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/
  LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api:packages:.
  WORKBENCH_RUNTIME_DIR set to a new mktemp isolated directory. Do not inherit
  any provider/role settings. Evidence only runs/mw_protocol_v3_p1r_legacy_disposition_20260905/.
- Out of scope: source/test edits; live/monitoring mutations; new security tests;
  realmodel/network/service/translation/OCR calls; historicalbatchrecreation;
  cleanup/archive; rawcredential/logreads. Runner owns final report. No worker
  reasoning input; verify actual currentfiles independently. Codex owns acceptance.
- Important scope:1R.6 already independently accepted,1521v3tests passed andsingle
  minimal GLMprobe succeeded. Do not repeatprobe/reviewimplementation. Proposed
  sequencing must preserve scientific/source/bodycompleteness and record deferred
  issues; do not inventclinicalapproval or simply turnfailedcasesintoexpectedPASS.

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

- 2026-09-05 21:09:09 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
