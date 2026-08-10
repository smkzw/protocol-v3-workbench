# Conference Context: mw_protocol_v3_phase1_task15_final_acceptance_20260810

Created: 2026-08-10 18:46:30
Objective: 独立验收 Protocol v3 Task 1.5 最终 checkpoint 全前缀双重 replay 修复及既有事件/outbox/inbox 权威合同无回归
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

- Frozen implementation plan Task 1.5: `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`.
- Design authority section 18: `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`.
- Current filesystem, limited to `packages/contracts/workbench_contracts/protocol_v3.py` DomainEvent, `services/api/app/protocol_workflow/events/`, the repository/UoW ports and in-memory reference adapter, and the three named Task 1.5 tests.
- Prior isolated Luna review found the last remaining P2: checkpoint reconciliation accepted an unreplayable predecessor and a pairwise-stable stateful upcaster. Current source now replays the complete evidence prefix twice before acceptance. Prior reports are decision history for Codex, not participant input.

## Scope

- In scope: independently falsify the complete-prefix double-replay checkpoint fix; check that the event envelope migration identity, outbox lifecycle precheck, state-transition contracts, canonical revision hashes, UoW atomicity, and honest at-least-once crash semantics did not regress.
- Out of scope: implementation edits, services, browser, network, package installation, runtime/production data, all security/adversarial/hygiene/source-baseline tests, later Task 1.6+, frontend/Word work, and every medical-monitoring file.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No production path is read or modified; Codex retains final acceptance.
- Both participants return READY only when no P0-P4 remains inside Task 1.5. Each may run only `tests/protocol_v3/test_event_replay.py`, `test_event_outbox_atomicity.py`, and `test_repository_contract.py` together or narrower with `PYTHONPATH=services/api:packages:. -W error -p no:cacheprovider`.
- Decisive checkpoint counterexamples must quarantine: unknown-schema predecessor before a valid backing event; pairwise-equal stateful upcaster whose first migrated hash matches; exact event/artifact/node/stream mismatch. Passing a persisted PENDING outbox message must invoke neither handler nor inbox write.

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
- Do not run or propose security tests; do not read or alter the medical-monitoring subsystem.

## Loop Log

- 2026-08-10 18:46:30: Conference initialized by `hermes_workflow_guard.py init-conference`.
- 2026-08-10: Participant 1 effective daytime route was `pi/cms-smk/cms-model` (session `019feb4a-8bda-7000-a4d5-96c056acac8c`), completed in 724.58 s, ran 153 focused tests and returned `READY` for the checkpoint fix.
- 2026-08-10: Grok Build session `ddd0dfb6-2cf0-4cce-ad90-947864b3d5c3` returned only progress narration in the initial pass and two same-session completion passes (295/245/140 characters). The recorded no-progress breaker was therefore exhausted before fallback.
- 2026-08-10: Declared participant-2 fallback `cursor-cli/cursor-grok-4.5-high`, session `f09678ec-2a43-452d-a0d2-bd74ef62602e`, found P3 no-handler recovery misclassification, then P4 stale public documentation. Codex repaired both. The final same-session round returned `READY`, no open P0–P4.
- 2026-08-10: Main-venue final anchors: 2 targeted tests, 155 focused tests, 376 integrated functional tests, Ruff check/format, compile and diff checks pass. Final conference disposition is `READY`.
