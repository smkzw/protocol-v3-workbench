# Conference Context: mw_protocol_v3_phase1_task19_acceptance_20260812

Created: 2026-08-12 00:39:01
Objective: 独立反证验收 Task 1.9 application service、Agent⑤ authority、API/client 合同与医学监查隔离
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

- Frozen Task 1.9 in `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md` (expected SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`).
- Approved design §§5.1, 5.3, 5.4, 17.2, 18 and 19 in `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`.
- Current filesystem implementation:
  - `services/api/app/protocol_workflow/application/`
  - `services/api/app/protocol_workflow/agent5/`
  - `services/api/app/protocol_workflow/api/`
  - `frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs`
  - the three Task 1.9 tests under `tests/protocol_v3/`.
- Adjacent accepted contracts/reducers/events/ports/storage/errors/registries are read-only comparison authority.
- Current filesystem and executed tests outrank worker/manager reports. Participants must not read other participant outputs or Worker/manager reasoning reports; verifier isolation requires independent inspection.

## Scope

- In scope: read-only contradiction review of storage-neutral commands/queries/UoW atomicity; Agent⑤ authority and immutable manifest; API/client project isolation, public error contract, fresh snapshot behavior, deterministic OpenAPI; product-storage fail-closed state; shared main.py and medical-monitoring isolation.
- Out of scope: edits/remediation, Task 1.10 migration, Task 1.11 security, service startup, live AI/OCR/translation, browser/visual E2E, later Protocol phases, legacy routes, medical-monitoring implementation.

## Success Criteria

- Each participant independently returns `READY` or `NOT_READY` for bounded Task 1.9 with exact code/test evidence and no edits.
- Re-run the three focused tests and full `tests/protocol_v3/`; verify Node client execution is not skipped, plan hash, current product storage `not_ready`, main.py unmounted, and medical-monitoring/shared changed-path delta zero.
- Attempt to falsify: exact replay/idempotency and atomic rollback; query zero-write behavior; retained authority-handle leakage; empty/duplicate source lineage; unregistered work/cycles; Gate/severity/QC/submission override surfaces; stale Agent⑤ snapshots; path/body mismatch before service; client-supplied exception fabrication; public/audit leakage; non-deterministic/English-jargon OpenAPI; client silent-error success.
- READY only if no functional P0/P1/P2/P3/P4 defect remains inside Task 1.9 and all decisive deterministic checks pass. Later-phase absence, deliberate main.py non-mount and product SQLite `not_ready` are not defects unless current code falsely claims otherwise.
- No source or test file is modified. Codex retains final acceptance.

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

- 2026-08-12 00:39:01: Conference initialized by `hermes_workflow_guard.py init-conference`.
- 2026-08-12 01:02 CST: Participant 1 Qwen session `019ff1b3-340c-7000-b05f-1f11891c5a2d` completed as `READY` with direct full-suite and Node execution.
- 2026-08-12 01:06 CST: Participant 2 Grok session `0f34c5e2-0370-4b70-82c3-40e4d8decb71` exhausted two same-session recoveries; all tool work remained cancelled/incomplete, satisfying the declared fallback condition.
- 2026-08-12 01:10 CST: Cursor fallback session `5efa0f36-3e9f-4bf9-97dd-550f54591e75` completed a static no-defect pass but returned `NOT_READY` solely because runner Ask mode blocked Shell.
- 2026-08-12 01:13 CST: The same Cursor session resumed with Shell enabled; 115 focused and 1001 full tests, Node, SHA, storage and isolation checks passed; final `READY`.
- 2026-08-12 01:19 CST: Codex independently reproduced decisive evidence and accepted Task 1.9. No source/test edits were made by conference participants.
