# Conference Context: mw_protocol_v3_hr_fresh_20260905

Created: 2026-09-05 13:17:02 CST
Objective: Fresh H-R验收：只读核查Phase R权威路径、23项共享差异语义处置、离线测试和用户批准的兼容式计划修订。读取当前文件，禁止subdelegation、服务及产品模型，不重复旧会商文字。
Task type: `high_risk_contradiction_review`
Risk: `high`
Conference mode: `parallel`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`evidence_single_object`) with no sub-venue chair. Its effective `CST` route chain is `zcode/glm-5.3:max -> xai/grok-4.6:high -> xai/grok-4.6:high -> openai-codex/gpt-6-astra:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_protocol_v3_hr_fresh_20260905`
- Execution evidence status: `no linked execution packet`
- Excluded provider/model nodes: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Read current files using tools; do not infer their absence from history. Read ../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md in full (SHA040eb6ad323047737e8be6a3a23344fdb719dc85230ef7994b96c9af29257607; directory read-only), plus plans/mw_protocol_v3_review_amendment_20260905.md. User explicitly approved 1R.4 compatibility-preserving simplification, and engineering Agent calls are allowed.
- Read runs/mw_protocol_v3_phaseR_r1_20260905.md and runs/mw_protocol_v3_phaseR_r2_semantic_disposition_20260905.md. Check facts against git diff, config/medical_writing/protocol_v3/authority_amendment_20260905.json, scripts/qc/protocol_v3/{authority_locator_amendment,reconcile_source_drift,build_frozen_authority_manifest,apply_repository_hygiene}.py and their four tests.
- Read baseline evidence in runs/mw_protocol_v3_phaseR_20260905/source_drift.json, live_source_observation.json and isolated_source_observation.json. Old mutable_source_baseline_20260809.json must preserve SHA32e274b47ec14a40f0bcaa280b4e8b81ccf06f61b3ee0c0606055d4d54f27d67. New mutable_source_baseline.json intentionally means current LIVE source-only supersession under Plan R.2, not isolated tree equality.
- Additional allowed read-only sources: ../workbench SOURCE FILES ONLY for verifying the named 23 shared changed items; external SOP files explicitly listed in authority_amendment only for hashing. No live runtime/database/credential/session reads. No need for web, Word or browser.
- Read runs/MW_PROTOCOL_V3_TASK21_NO_LOSS_PAUSE_20260812_0708.md, verify seven preserved file hashes. Do not read any other reviewer output; this is a fresh verifier of the actual artifact, not a vote on another model.

## Scope

- In scope: H-R independent recommendation READY/NOT_READY, exact file/line/command counterexamples; check protected hash preservation, path amendment, shared-drift assumptions, injectable lsof tests and scope isolation. tests/protocol_v3 and pocs/protocol_v3/orchestrator/tests may run with PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api:packages:. /opt/homebrew/bin/python3.12 -m pytest -q -p no:cacheprovider; test-owned tmp only. No need to retest unchanged counts without a decisive concern.
- Out of scope: product code edits, commits, any service, product model/OCR/translation/Word/browser, live writes, monitoring writes, any recursive Agent/scout dispatch, cleanup/archive or modifying upgrade/old evidence. Return only the runner-owned report. Treat runner/context/plans/prompts/reviews/metrics/conference/runs/logs for this user-requested review as DECLARED Phase R evidence overlay; not a reason to delete or disallow these files.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No production path modified; expressly allowed SOURCE-only reads above. Codex retains final acceptance.
- H-R is re-anchor/test-readiness only; missing product SQLite/router/UI are Phase1R+ scope and cannot be mistaken for current product PASS, but their planned absence alone is not H-R failure. Validate whether the documented R.2 impacts are adequately dispositioned without merging live. Need exact materially unresolved prerequisite, not cosmetic process padding.

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

- 2026-09-05 13:17:02 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
