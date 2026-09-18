# Conference Context: mw_protocol_v3_1r4_contract_fresh_20260905

Created: 2026-09-05 19:34:55 CST
Objective: Fresh independent review of Task1R.4 explicit minor-version dependency compaction only: four contract types, legacy byte/hash identity, real harness binding, document revision and replay. No product source edits. Do not review concurrent SQLite/reservation work. No security-specialist scope, no real models/OCR/translation/Word/live calls or cleanup.
Task type: `code_open_audit`
Risk: `high`
Conference mode: `parallel`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`general_single_object`) with no sub-venue chair. Its effective `CST` route chain is `zcode/glm-5.3-flash:max -> opencode-go/muse-spark-1.3-contributor:xhigh -> codebuddy-cli/deepseek-v4-flash:max -> openai-codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_protocol_v3_1r4_contract_fresh_20260905`
- Execution evidence status: `no linked execution packet`
- Excluded provider/model nodes: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Read plans/mw_protocol_v3_review_amendment_20260905.md (current1R.4 requirements), .trellis/tasks/09-05-protocol-v3-1r4/prd.md; current packages/contracts/workbench_contracts/protocol_v3.py, services/api/app/protocol_workflow/runtime/harness.py and canonical/document.py; tests/protocol_v3/test_compact_dependency_contract.py, test_contract_models.py, test_harness_policy.py, test_semantic_document_reducer.py. For old byte/hash comparison use git show HEAD:packages/contracts/workbench_contracts/protocol_v3.py (readonly historical source), not other reviewer reports or Codex reasoning.
- Do not add production paths unless the user explicitly authorized reading them for this task.

## Scope

- In scope: fresh verify explicit v1->v1.1 conversion across SemanticDocumentRevision, ChapterLockSnapshot, NodeExecutionContract, SubmissionEvidencePackage; raw v1 model_dump and material hashes unchanged; new representation binds exact ordered dependency content, does not silently ignore conflicting tuples/digests; no immutable event mutation. Verify actual harness build_request and document reducer/replay, nested material semantics, legacy negative fixtures, missing/duplicate/reordered/substituted inputs and chapter changes. Check whether the change truly removes redundant representation instead of merely adding unused classes. 2R.1 adoption is a documented downstream requirement, not yet complete. Report source-backed defects and actual repros, not speculative new security systems.
- Product source and existing tests readonly. May write synthetic probes/new evidence only under runs/mw_protocol_v3_1r4_contract_fresh_20260905/. Runner owns report. No worker reasoning is provided; contract implementation is by main Codex, independent of concurrent ZCode storage executor. Do not inspect or judge that other slice.
- Exact env: env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=services/api:packages:. WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_compact_dependency_contract.py tests/protocol_v3/test_contract_models.py tests/protocol_v3/test_harness_policy.py tests/protocol_v3/test_semantic_document_reducer.py -q -p no:cacheprovider. No full suite while other executor owns reservation/SQLite tests. No installs/services/models/OCR/translation/Word/network/live/global/monitoring/SOP writes, no cleanup/archive/security-specialist tests/task closure.
- Out of scope: SQLite/reservation lifecycle and superseded migration, 1R.5 security-specialist work, full1R.4/P1R/clinical/Word acceptance, full-repository legacy debt. Frozen source hashes: protocol_v3.py928d2549c97b012b0639e7003c8883ce2b2033c59d48cb57d98b69816dcd5799; harness.py263aae74e1813781579881fb9993bc801bce610e11a7a83019ad326e6a20b44f; document.pye752920557ddd412d4da3a29c8f7d570a072d9c474f3c4cce48a7bff1fceca65.

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

- 2026-09-05 19:34:55 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
