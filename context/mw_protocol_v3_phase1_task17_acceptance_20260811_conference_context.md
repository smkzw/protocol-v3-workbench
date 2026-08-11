# Conference Context: mw_protocol_v3_phase1_task17_acceptance_20260811

Created: 2026-08-11 15:05:36
Objective: Fresh-context read-only acceptance of Protocol v3 Task 1.7 Role/Skill/Harness Registry against frozen plan and deterministic runtime evidence
Task type: `complex_delivery_conference`
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

- Frozen plan `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, especially Task 1.7.
- Task contract `context/mw_protocol_v3_phase1_task17_20260811_context.md`.
- Canonical `SkillDefinition` / `NodeExecutionContract` in `packages/contracts/workbench_contracts/protocol_v3.py` and accepted Task 1.6 reservation/idempotency runtime.
- Current Task 1.7 registries, strict loader, Harness, four adapters and focused tests under their declared paths.
- Direct local CLI help is authority for Codex/OMP command syntax. Current filesystem and executed tests are final truth.
- Existing worker/manager/conference reports are excluded from the verifier read set to preserve fresh-context isolation.

## Scope

- In scope: read-only spec compliance, code quality and adversarial functional-contract review of Task 1.7; deterministic test execution; plan-hash and medical-monitoring isolation checks; P0-P4 findings and READY/NOT_READY verdict.
- Out of scope: edits, service startup, live provider/model/OCR/translation calls, credentials, security testing, frontend/UI, legacy storage, Task 1.8+, medical-monitoring files, release/promotion.

## Success Criteria

- Four product roles and nine Skills are strict, versioned, credential-free and bound to canonical contracts; thinking is configurable only for LLM/support.
- Harness cannot dispatch an unvalidated Role/Skill/artifact/schema/region request; preflight/probe/gate/lease/session/receipt/fallback semantics fail closed with accurate `dispatched` classification.
- Direct API, local oMLX, Codex and OMP adapters require explicit probes, never fabricate runtime identity or typed receipt fields, preserve same-session recovery, and do not emit forbidden one-turn/no-tools flags.
- OCR/translation share the common workload gate and real lease. Current GLM OCR vs declared Paddle remains a pre-dispatch mismatch; Hy-MT2 translation identity must match exactly.
- Codex schema URI resolves to an existing local JSON file and the CLI never receives the URI as `--output-schema`.
- Focused pair, full Protocol v3 suite, Ruff/format/compile, frozen-plan hash and zero medical-monitoring diff independently pass.
- READY requires P0=P1=P2=P3=P4=0. Any finding must name severity, exact path/line, reproduction/evidence and bounded remediation.
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
- Failure rule: Do not fail a model for slow response alone; fail only on terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no useful progress after the high-budget same-session recovery loop. A catalog/auth/transport health preflight timeout or malformed response is diagnostic and must still allow one live route attempt; only a missing CLI or an explicitly invalid, retired, or unlisted model may block before live dispatch. If a resumable session exists after a step/size boundary, continue it before fallback; repeated identical output/tool evidence triggers the no-progress breaker.
- Pass/turn boundary: one conference prompt is one conference pass. The
  `--max-turns` value controls internal Agent tool-calling turns and is never
  set to 1 for substantive conference execution; generated participant and
  chair commands use the route budgets recorded by the guard.

## Risk Boundaries

- External Agents are advisory; Codex remains final authority.
- Codex owns visual/browser/PPT/PDF/rendered checks, live authority checks, final clinical/regulatory conclusions, and production writes.
- Do not mark a slow model failed solely due to latency.
- Do not perform security testing. Review only product correctness and fail-closed workflow semantics required by Task 1.7.

## Loop Log

- 2026-08-11 15:05:36: Conference initialized by `hermes_workflow_guard.py init-conference`.
- 2026-08-11: Pi and Grok independent reports were collected. Their functional findings drove bounded repairs; historical NOT_READY verdicts remain preserved as evidence rather than overwritten.
- 2026-08-11: Native Luna capability probe rejected `gpt-5.6-luna` because only Sol/Terra selectors were exposed. The declared CLI compatibility route started session `019fefbf-636b-7462-9720-2b4629f83a80`; all functional follow-ups reused that session.
- 2026-08-11: A follow-up that expanded into same-process hostile introspection was interrupted because the user explicitly excluded security testing. The final functional-only follow-up returned `READY`, `P0=P1=P2=P3=P4=0`.
- 2026-08-11: Codex independently ran the full deterministic suite and static/isolation checks. Conference acceptance is `PASS` for the Task 1.7 functional contract.
