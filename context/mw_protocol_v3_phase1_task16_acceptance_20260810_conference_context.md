# Conference Context: mw_protocol_v3_phase1_task16_acceptance_20260810

Created: 2026-08-10 22:50:32
Objective: 隔离反证验收 Protocol v3 Task 1.6 ExecutionReservation 的预留先行、终态不确定恢复、显式 retry decision 追加谱系与 fallback 最小重打包；不做安全性测试
Task type: `high_risk_contradiction_review`
Risk: `high`
Conference mode: `parallel`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

    - Visual/design/HTML/PPT tasks use a Codex-led panel with no sub-venue chair: Pi/Oh My Pi `kimi-code/k3-256k` (high). If unavailable, the runner tries Grok Build `grok-4.5`, then Cursor CLI `cursor-grok-4.5-high`, then Pi/OpenCode Go `gpt-5.6-luna` (max), then Pi/Kimi `k3-256k` (high).
- Chinese labels or Chinese sentence review is handled directly by Codex and does not start a conference.
    - Other complex tasks use a Codex-chaired panel with no sub-venue chair. Participant 1 is Pi/Alibaba `qwen3.8-max` (xhigh) during the Beijing 22:00-07:00 window, and outside that window its exact Qwen Max node is replaced by Pi/cms-smk `cms-model` (high); its remaining fallbacks are Pi/cms-smk `cms-model` (high), Pi/cms-smk `deepseek-v4-flash` (max), Pi/OpenCode Go `deepseek-v4-flash` (max), and Pi/DeepSeek `deepseek-v4-flash` (max). Participant 2 is Grok Build `grok-4.5`, with Cursor CLI `cursor-grok-4.5-high` and Pi/cms-router `minimax-m3` as fallbacks. Codex remains the final authority. The explicit Luna native/CLI compatibility route remains available for execution roles that declare Codex subAgent.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Source Of Truth

- Frozen plan `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, Task 1.6.
- Approved design `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, sections 17.2 and 18.
- Current implementation only:
  - `packages/contracts/workbench_contracts/protocol_v3.py` (`ExecutionReservation`, `NodeExecutionContract`);
  - `services/api/app/protocol_workflow/runtime/{idempotency,reservations,__init__}.py`;
  - `services/api/app/protocol_workflow/ports/repositories.py` (`ExecutionReservationRepository` and typed errors);
  - `services/api/app/protocol_workflow/storage/memory.py` (`InMemoryExecutionReservationRepository`);
  - `tests/protocol_v3/test_execution_reservations.py` and the reservation-specific part of `tests/protocol_v3/test_repository_contract.py`.
- Do not read worker, manager, prior review, conference participant, metrics, run or raw-log outputs. The verifier receives artifacts and criteria, not worker reasoning.

## Scope

- In scope: functional contradiction review of persist-before-preflight, atomic RUNNING ownership before physical dispatch, terminal persistence failure discovery/reconciliation without redispatch, completed reuse, timeout/no receipt unknown outcome, same-session recovery, explicit retry-decision append-only attempts, concurrent duplicate behavior, contract revalidation, and cross-provider canonical-source repackaging.
- Out of scope: implementation edits, live providers/models/CLI/OCR/translation/download/export, services/databases/browser/frontend/UI, LangGraph/registry work after Task 1.6, legacy medical-writing changes, all medical-monitoring files, and all security/adversarial/path/permission/hygiene/source-baseline tests.

## Success Criteria

- Each participant independently attempts to falsify the current contract using source analysis and only the two named functional test files or narrower non-destructive probes.
- Every physical side effect has a persisted reservation; the row is RUNNING with one transport attempt before dispatch; restart never automatically redispatches RESERVED/RUNNING/UNKNOWN work.
- Terminal persistence failure remains discoverable through `find_unresolved` and can be reconciled on the same provider session without a new transport call.
- Completed same input is reused; explicit retry requires a durable decision identity, duplicate decisions create no duplicate call/row, distinct decisions append attempts even for unchanged input, and old attempts remain immutable.
- Fallback uses canonical source only, rejects nested forbidden fragments, and authorizes targets only through explicit provider/region allowlists rather than string heuristics.
- Contract transitions are closed and revalidated before commit; invalid terminal data cannot be persisted.
- READY requires no open P0-P4 in Task 1.6. Any finding includes an executable functional counterexample or exact source path/line reasoning and a minimal remediation.

## Parallel Work Rule

For logic-heavy, rigor-sensitive, or artifact-heavy tasks, each participant independently runs the whole bounded workflow and writes a separate output. Leads compare after all available participant outputs are in or explicitly marked pending.

## Timeout Policy

- Participant soft wait: 60 minutes.
- Large-task participant wait: 120 minutes.
- Chair hard wait: 120 minutes.
- Failure rule: Do not fail a model for slow response alone; fail only on terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no useful progress after the high-budget same-session recovery loop. A catalog/auth/transport health preflight timeout or malformed response is diagnostic and must still allow one live route attempt; only a missing CLI or an explicitly invalid, retired, or unlisted model may block before live dispatch. If a resumable session exists after a step/size boundary, continue it before fallback; repeated identical output/tool evidence triggers the no-progress breaker.
- Pass/turn boundary: one conference prompt is one conference pass. The
  `--max-turns` value controls internal Agent tool-calling turns and is never
  set to 1 for substantive conference execution; generated participant and
  chair commands use the route budgets recorded by the guard.

## Risk Boundaries

- External Agents are advisory; Codex remains final authority.
- Codex owns visual/browser/PPT/PDF/rendered checks, live authority checks, final clinical/regulatory conclusions, and production writes.
- Do not mark a slow model failed solely due to latency.
- Do not run or propose security testing. Functional crash, restart, concurrency and malformed ordinary state-transition probes are in scope only when they directly test Task 1.6 behavior.

## Loop Log

- 2026-08-10 22:50:32: Conference initialized by `hermes_workflow_guard.py init-conference`.
- 2026-08-10: Codex completed the execution-manager pass, then closed its sole P3 by adding `find_unresolved` for RESERVED/RUNNING/UNKNOWN recovery discovery. Current main-venue anchors before conference: 35 runtime tests and 72 repository-contract tests; final integrated recount remains Codex-owned.
- 2026-08-10/11: Participant 1 Qwen initial pass found F1-F5 (two P3, three P4). Codex reproduced and repaired all five as functional or explicitly pinned contracts. Same Qwen session `019fec2a-bb00-7000-8b5c-fe54956ba568` then returned READY after independently running 112 tests and 31 probes.
- 2026-08-11: Participant 2 native Grok Build session `6fe64da8-28d6-4f82-8cd8-b82519ce070c` returned terminal `cancelled` on its initial pass and both permitted same-session recovery passes, each with only a progress sentence. No Grok output was accepted as review evidence.
- 2026-08-11: After Grok recovery exhaustion, declared fallback Cursor CLI `cursor-grok-4.5-high`, session `d9b5af7b-caf7-463d-b6f7-c12a7fb6d6cb`, returned READY by isolated static falsification. Its Ask-mode shell gate blocked independent pytest, so the executable acceptance anchors remain Qwen's 112/112 and Codex's 423/423.
- 2026-08-11: Codex final review found no open P0-P4. Conference result READY; no security, service, browser, model, OCR, translation, download, export or medical-monitoring test was run.
