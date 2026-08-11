# Conference Context: mw_protocol_v3_phase2_task21_acceptance_20260812

Created: 2026-08-12 06:27:12
Objective: Fresh-context independent acceptance of Protocol v3 Task 2.1 immutable typed case contracts, deterministic fakes, three clinical design graphs and fail-closed recovery/isolation evidence; read-only, no security tests
Task type: `high_risk_contradiction_review`
Risk: `high`
Conference mode: `parallel`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

    - Visual/design/HTML/PPT tasks use a Codex-led panel with no sub-venue chair: Pi/Oh My Pi `kimi-code/k3-256k` (high). If unavailable, the runner tries Grok Build `grok-4.5`, then the distinct Cursor `cursor-grok-4.5-high` route, then the distinct Pi/OpenCode Go `gpt-5.6-luna` (max) route. The Codex subAgent Luna route remains a separate native/CLI compatibility path.
- Chinese labels or Chinese sentence review is handled directly by Codex and does not start a conference.
    - Other complex tasks use a Codex-chaired panel with no sub-venue chair. Participant 1 is Pi/Alibaba `qwen3.8-max` (xhigh) during the Beijing 22:00-07:00 window. Outside that window its exact Qwen Max node is replaced by Pi/OpenCode Go `deepseek-v4-flash` (max); during the night window, every exact Pi/cms-smk `deepseek-v4-flash` node is replaced by the same Pi/OpenCode Go route. Its remaining fallbacks are Pi/cms-smk `deepseek-v4-flash` (max), Pi/OpenCode Go `deepseek-v4-flash` (max), and Pi/DeepSeek `deepseek-v4-flash` (max), with effective-route deduplication. Participant 2 is Grok Build `grok-4.5`, with the distinct Cursor `cursor-grok-4.5-high` and Pi/cms-router `minimax-m3` as fallbacks. Codex remains the final authority. The explicit Luna native/CLI compatibility route remains available for execution roles that declare Codex subAgent.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Source Of Truth

- Frozen plan: `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 2.1 only (lines 838-861); SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`.
- Design context: `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, only sections needed for the three high-risk cases, gates, owner boundaries and idempotency.
- Current artifact tree, exactly seven Python files: `pocs/protocol_v3/orchestrator/__init__.py`, `fakes.py`, `cases/__init__.py`, `cases/eligibility.py`, `cases/objective_estimand_endpoint.py`, `cases/sample_size.py`, `tests/test_case_contracts.py`.
- Anchors to reproduce, not trust: focused suite 71 tests; existing `tests/protocol_v3` functional regression 1226 tests + 101 subtests; graph material hashes are pinned by the focused suite.
- Verifier isolation: do not read worker, manager, or other participant reports before reaching an independent verdict. Current filesystem is final truth.

## Scope

- In scope: read-only inspection/execution of the seven files; independently falsify closure, cycles/unknown dependencies, parallel typed-edge ordering, deterministic hash, missing clinical links, five injection declarations, deep immutability, project/branch isolation, duplicate/restart/concurrent/old-version semantics represented through deterministic fakes, and no product/scheduler/provider/storage imports.
- In scope: structural adequacy of eligibility evidence/QC/decision; objective-estimand-endpoint linkage/QC/decision; sample-size targets/assumptions/calculation/statistical review/decision, with synthetic assumptions and no invented numeric clinical defaults.
- Out of scope: security testing and frozen Task 1.11; services, live databases/providers, scheduler/LangGraph/MAF, product wiring, UI, OCR, translation, Word, medical-monitoring, production migration and release.
- Out of scope: editing. Participants may veto/request a precise repair but may not silently rewrite.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No production path is read or modified; Codex retains final acceptance.
- Both test anchors reproduce or divergence is explained from current files.
- Every Task 2.1 micro-step is grounded by source plus a non-LLM check; key fail-closed claims have direct counterexamples.
- Verdict is `TASK21_READY` only when no blocker remains, otherwise `TASK21_NOT_READY` with severity, reproducer, affected file/contract and smallest owning-session repair.

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
- Phase-1 did not complete user-excluded security Task 1.11; no result here implies security, product, release or P2-G2 completion.
- Distinguish injection-point declarations from recovery behavior actually exercised by Task 2.1 fakes; Task 2.2 remains future work.

## Loop Log

- 2026-08-12 06:27:12: Conference initialized by `hermes_workflow_guard.py init-conference`.
