# Conference Context: mw_protocol_v3_phase1_task14_acceptance_20260810

Created: 2026-08-10 15:08:46
Objective: 独立验收 Protocol v3 Task 1.4 canonical reducers、CAS、StudyDefinition 唯一事实源与 SemanticDocument revision-bound 投影；仅功能合同，不做安全性测试

## Source Of Truth And Scope

- Frozen plan `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 1.4, expected SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`.
- Approved design `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, especially Sections 6, 10, 14 and 15.
- Actual artifacts under `services/api/app/protocol_workflow/canonical/` and the three Task 1.4 functional tests under `tests/protocol_v3/`.
- Scope is read-only contradiction review of Task 1.4. Do not review or modify medical-monitoring, legacy medical-writing, runtime services, APIs, UI, OCR, translation or model configuration.

## Success And Veto Criteria

- Same full CAS triple plus identical payload is idempotent and returns the recorded decision/effect; conflicting payload, stale state and unrelated lineage fail closed with typed errors.
- StudyDefinition is the only fact authority, carries exact revision lineage, preserves prior facts and prevents unaccepted/frozen fact replacement.
- SemanticDocument is a revision-bound projection: its header uses the shared StudyDefinition revision hash; paragraph, protocol summary, schedule of activities, tables and figures reference fact paths rather than carrying a second fact store.
- Same-result and later-descendant replays prove lineage instead of trusting aggregate ID plus revision number alone.
- `fact_or_uncertain` produces a deeply immutable fact proposal and no document revision.
- Deterministic functional tests, compilation, Ruff and frozen-plan hash pass; no medical-monitoring path changes.
- Any reproducible P0/P1/P2 defect, missing required contract, or unverifiable claim yields `NOT_READY`. This review is only Task 1.4 acceptance and does not count as future end-to-end P0-P4 clearance.

## Risk Boundaries

- Read-only review. No file edits, service starts, package installs, browser/model/OCR/translation calls or production/runtime writes.
- Do not run security, adversarial, permission, path, symlink, TOCTOU, malicious-input, destructive-state or penetration tests. Functional CAS invalid-state counterexamples are required and permitted.
- Do not read worker/manager reports or their reasoning. Review the frozen requirements, source, tests and actual command evidence independently.
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

- TODO: Add authoritative local files, extracts, datasets, screenshots, URLs, or user-provided materials.
- Do not add production paths unless the user explicitly authorized reading them for this task.

## Scope

- In scope: TODO
- Out of scope: TODO

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

- 2026-08-10 15:08:46: Conference initialized by `hermes_workflow_guard.py init-conference`.
- 2026-08-10: Native Luna capability had already been rejected in the current App session; the declared CLI compatibility route ran model `gpt-5.6-luna` at `max`, session `019fea82-aefc-7913-b520-dbb4f0e38905`.
- 2026-08-10: Round 1 independently returned `NOT_READY` with reproducible replay, exact-hash, frozen-`None`, and proposal-immutability defects. No worker/manager/Codex reasoning was read.
- 2026-08-10: After Codex remediation, the same session repeated the original probes and returned `READY`, P0–P4 all none. The verdict remains limited to Task 1.4.
