# Conference Context: mw_protocol_v3_engineering_crossreview_20260905

Created: 2026-09-05 12:52:26 CST
Objective: 独立审查 Protocol v3 Plan v2 的工程完整性与 Phase R 实际修复，反证 API/存储/恢复/模板/前端用户流程；仅只读源码和离线测试，不调用产品模型或服务。用户已明确允许工程审阅 Agent。
Task type: `high_risk_contradiction_review`
Risk: `high`
Conference mode: `parallel`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`general_single_object`) with no sub-venue chair. Its effective `CST` route chain is `cursor/default -> opencode-go/muse-spark-1.3-contributor:xhigh -> cms-router/minimax-m3:xhigh -> google-antigravity/gemini-3.8-flash-high:high -> openai-codex/gpt-5.6-luna:max`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_protocol_v3_engineering_crossreview_20260905`
- Execution evidence status: `no linked execution packet`
- Excluded provider/model nodes: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- SAME-SESSION ROUND 2: First review has terminally completed and remains immutable. Review the added R.1 checkpoint runs/mw_protocol_v3_phaseR_r1_20260905.md and R.2 disposition runs/mw_protocol_v3_phaseR_r2_semantic_disposition_20260905.md against the current diff and sources. Check whether these actually close your missing-evidence findings. No product source changed after first review. Review plans/mw_protocol_v3_review_amendment_20260905.md: user explicitly approved simplifying implementation while preserving safety semantics and legacy compatibility; product model prohibition still excludes engineering Agents. Current runner context/plans/prompts/reviews/metrics/conference/runs/logs are declared Phase R review evidence, not unexplained product edits; none may be cleaned. Legacy baseline file has current LIVE source-only meaning as Plan R.2 requires, historical exact bytes retained.
- No subdelegation: first report mentioned attempted workers/scouts despite this prohibition. In this continuation do all work yourself; identify whether any nested attempt actually started, and report the boundary deviation honestly. Do not launch other Agents, enumerate unrelated sessions, or inspect credential material. No need to repeat unchanged full suites unless a new counterexample warrants it.

- Isolated working directory is the only implementation workspace. Read Plan v2 and design v1.3 in ../plan-upgrade-20260905/ in full; this directory is read-only. Read runs/MW_PROTOCOL_V3_TASK21_NO_LOSS_PAUSE_20260812_0708.md and reviews/codex_mw_protocol_v3_p1g1_functional_gate_20260812_review.md. Frozen plan .hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md is inherited only where v2 does not amend it.
- Read current Phase R diff (git diff plus named untracked files), scripts/qc/protocol_v3/{authority_locator_amendment,reconcile_source_drift,build_frozen_authority_manifest,apply_repository_hygiene}.py; config/medical_writing/protocol_v3/authority_amendment_20260905.json; tests/protocol_v3/test_{authority_locator_amendment,source_drift_reconciliation,repository_hygiene_mutator,frozen_authority_manifest}.py. Historical baseline copy must reproduce original 32e274b4 hash; old immutable manifest/rules bytes unchanged.
- Backend design review reads services/api/app/protocol_workflow/, packages/contracts/workbench_contracts/protocol_v3.py and pocs/protocol_v3/{storage,orchestrator}/; frontend source review focuses frontend/src/features/medical-writing/ and protocolWorkspaceApi.mjs. Read imports/callers as necessary. Do not merely count lines.
- Additional read-only sources allowed: ../workbench source files ONLY for drift review; SOP assets expressly listed in authority_amendment_20260905.json for hashing ONLY. Do not inspect live runtime/dbs/credentials/private sessions. No web needed: Codex owns regulatory source verification.
- Deterministic evidence: 13/13 relocated CMSS assets SHA match; 8 additive assets. Focused Phase R 183 passed. Full tests/protocol_v3 1240 passed, 101 subtests passed, 2 warnings in 17.89 seconds. New tests were red first. Do not treat these claims as acceptance without reproducing decisive checks.
- runs/mw_protocol_v3_phaseR_20260905/source_drift.json: live head d2daef1, isolated head 3d6772f. 313 differences by path triage: 129 monitoring, 127 writing, 57 shared. Only changed (both-tree) writing-class path is tests/test_medical_writing_study_schema.py; presence differences and shared files need careful interpretation. Original worktree clean before task. No product-source change made during Phase R.

## Scope

- In scope: independent counterexample review of Phase R for H-R recommendation, plus concrete backend/architecture plan corrections before Phase 1R. Review domain/repository interfaces against PoC SQLite; identify what cannot simply be copied, what simplification would break delivery/replay/immutability, and any user burden or requirement conflicts. Return source file:line and concrete evidence for each finding. Component map should distinguish implemented offline kernel from runtime/stubs/planned components.
- Out of scope: all source edits, commits, any product service/model/OCR/translation/Word/browser automation, cleanup, production activation, monitoring/live mutation, plan-upgrade edits, external communications. Tests restricted to tests/protocol_v3 and pocs/protocol_v3/orchestrator/tests with PYTHONDONTWRITEBYTECODE=1, PYTHONPATH=services/api:packages:., /opt/homebrew/bin/python3.12, -p no:cacheprovider. Tests may write only their task-owned temporary directories. Do not run whole-repo pytest or import main.py without isolation analysis.
- User explicitly clarified that engineering review Agent calls are allowed, while the product-call ban remains. Review output stays in runner-managed report only; no subdelegation or additional conference.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No production path modified; allowed source-only reads above. Codex retains final acceptance.
- Provide H-R recommendation READY/NOT_READY with counterexamples; separately list engineering review gaps and recommended Plan v2 amendments with task order/affected files/testing criteria. No product/clinical release verdict.

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

- 2026-09-05 12:52:26 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
