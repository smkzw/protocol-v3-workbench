# Conference Context: mw_protocol_v3_phase1_task15_acceptance_20260810

Created: 2026-08-10 17:40:42
Objective: 独立反证验收 Protocol v3 Task 1.5 的事件权威、确定性重放、事务性 outbox/inbox 与真实重启恢复；不做安全性测试
Task type: `high_risk_contradiction_review`
Risk: `high`
Conference mode: `serial`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

    - Visual/design/HTML/PPT tasks use a Codex-led panel with no sub-venue chair: Pi/Oh My Pi `kimi-code/k3-256k` (high). If unavailable, the runner tries Grok Build `grok-4.5`, then Cursor CLI `cursor-grok-4.5-high`, then Pi/OpenCode Go `gpt-5.6-luna` (max), then Pi/Kimi `k3-256k` (high).
- Chinese labels or Chinese sentence review is handled directly by Codex and does not start a conference.
    - Other complex tasks use a Codex-chaired panel with no sub-venue chair. Participant 1 is Pi/Alibaba `qwen3.8-max` (xhigh) during the Beijing 22:00-07:00 window, and outside that window its exact Qwen Max node is replaced by Pi/cms-smk `cms-model` (high); its remaining fallbacks are Pi/cms-smk `cms-model` (high), Pi/cms-smk `deepseek-v4-flash` (max), Pi/OpenCode Go `deepseek-v4-flash` (max), and Pi/DeepSeek `deepseek-v4-flash` (max). Participant 2 is Grok Build `grok-4.5`, with Cursor CLI `cursor-grok-4.5-high` and Pi/cms-router `minimax-m3` as fallbacks. Codex remains the final authority. The explicit Luna native/CLI compatibility route remains available for execution roles that declare Codex subAgent.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Source Of Truth

- `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, frozen SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, especially Task 1.5.
- `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, especially section 18.
- Current filesystem implementation under `services/api/app/protocol_workflow/events/`, the Task 1.4 canonical reducers, repository ports/reference memory adapter, and focused functional tests named in the acceptance prompt.
- Current git status and diff. Worker, manager, prior Codex, review, metrics, run and log conclusions are deliberately excluded from the verifier's read set.

## Scope

- In scope: read-only contradiction review of event authority, schema/upcaster determinism, exact canonical revision hashing, checkpoint/event reconciliation, transactional outbox/inbox, restart discovery, idempotency and public composition APIs.
- Out of scope: source edits, services, packages, network calls, production/runtime data, browser/UI, broad directory tests, security/adversarial/hygiene/source-baseline tests, medical-monitoring files, and later Protocol phases.

## Success Criteria

- A fresh isolated verifier returns an auditable `READY` or `NOT_READY`, P0-P4 findings, exact evidence and remediation.
- Every material acceptance claim has a non-LLM anchor: current source, focused executed test or a minimal read-only counterexample.
- Unknown event types/versions fail closed; nondeterministic upcasters cannot silently yield divergent materialization; replay returns the Task 1.4 authoritative revision hash.
- Restart recovery discovers durable DISPATCHED work without retaining pre-crash Python objects; replay/checkpoint direction mismatches fail closed.
- Inbox semantics do not overclaim exactly-once when an external semantic effect and the consumed marker cannot be committed atomically; any required idempotent-handler contract is explicit and tested.
- No prohibited tests, services, source writes, package installs or medical-monitoring changes occur. Codex retains final acceptance.

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

## Loop Log

- 2026-08-10 17:40:42: Conference initialized by `hermes_workflow_guard.py init-conference`.
- 2026-08-10: The current App session had already explicitly rejected the native `gpt-5.6-luna` child capability. Per the global route contract, this acceptance uses the labeled Codex CLI compatibility route with a fresh context, max effort, tools preserved and a 120-minute hard wait; no model substitution is permitted.
- 2026-08-10: Luna session `019feb0d-3b97-7081-80ff-1b47f5b170ae` completed an initial pass plus two targeted same-session follow-ups (1341.21 s, 839.26 s, 246.48 s). Verdicts were `NOT_READY`, `NOT_READY`, `NOT_READY`; each produced decisive counterexamples and progressively narrowed the remaining scope.
- 2026-08-10: The final Luna finding was checkpoint acceptance without full-prefix replay stability. Codex repaired it with complete-prefix double replay; no new Luna session was created after the permitted same-session recovery passes were exhausted. Final independent acceptance moved to a new guard-initialized conference.
