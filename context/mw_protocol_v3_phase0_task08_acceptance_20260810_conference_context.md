# Conference Context: mw_protocol_v3_phase0_task08_acceptance_20260810

Created: 2026-08-10 10:26:26
Objective: 独立只读验收Protocol v3 Task 0.8 Word原生producer功能闭环、失败阻断、不可变回导lineage和逐页证据；禁止任何安全、对抗、权限、路径、符号链接、竞态、恶意输入或破坏性测试
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

- `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 0.7–0.8.
- `pocs/protocol_v3/word_receipt/contract.py`, `producers/`, `roundtrip_lineage.py`,
  `run_matrix.py`, tests, `README.md` and `decision.md`.
- Final receipts and page evidence under ignored task-owned results:
  - `results/CMS-UC-301-e692a28e51ed/`
  - `results/CMS-UC-301-wording-roundtrip/`
  - `results/CMS-UC-301-wording-roundtrip-r2-18dc202605c6/`
  - `results/CMS-UC-301-wording-roundtrip-current-908726e34525/`
- Failed-path evidence:
  - `results/D017-synopsis-import-70376ada005a/`
  - `results/TP-MA-07-dc6dfe33f78d/`
- Current task context and deterministic output from 67 focused functional tests.
- Original external sample files are not in the reviewer read set. Their exact hashes are already
  recorded in `decision.md`; Codex separately verified them against the originals.

## Scope

- In scope: read-only contract/code review, final receipt validation, event/replay reasoning,
  lineage identity checks, failed-path classification, and inspection of existing page PNG/contact
  sheets. Running the existing focused Word-receipt functional test directory is allowed.
- Out of scope: edits, Word invocation, service/browser/OCR/translation startup, product/API work,
  Phase 1+, and all medical-monitoring files.
- Explicitly prohibited: any security, adversarial, permission, path, symlink, TOCTOU,
  malicious-input or destructive-state test. Do not propose one as an acceptance condition.

## Success Criteria

- Each participant independently returns `READY`, `READY_WITH_RESIDUALS`, or `NOT_READY`, with
  exact paths/fields/tests supporting the verdict.
- Confirm or refute that at least one producer satisfies the frozen receipt contract including
  external wording edit → reimport → re-export, source preservation, deterministic recovery and
  page evidence.
- Treat TP page-2 clipping and D017 missing stable business bookmark as intentional blockers,
  not producer-wide success evidence.
- No file is modified and no prohibited test is run. Codex retains final visual and gate acceptance.

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
- Reviewers must not inspect each other's output. The chair compares terminal reports.
- This is functional acceptance only; no security concern or security hardening is in scope.

## Loop Log

- 2026-08-10 10:26:26: Conference initialized by `hermes_workflow_guard.py init-conference`.
- 2026-08-10 10:28: Source packet narrowed to immutable receipts, code, tests and existing page
  evidence. Both roles are read-only and explicitly barred from security testing.
- 2026-08-10 10:28: Pi effective route rewritten by Beijing policy to
  `pi/cms-smk/cms-model:high`; Grok used native `grok-build/grok-4.5`.
- 2026-08-10 10:34: Pi completed session `019fe981-3e54-7000-a68e-ae2c4ff8afaa`
  with `READY` and no fallback.
- 2026-08-10 10:29–10:39: Grok session `a68dc987-6507-4370-8685-c40785e76a12`
  returned two cancelled progress-only outputs after tool/output interruption; Codex reused the same
  session for both allowed recovery passes. Final pass ended normally with
  `READY_WITH_RESIDUALS`; no fallback.
- 2026-08-10 10:40: Codex accepted the panel, resolved lineage/producer-pin objections and set
  `P0-WORD_TECHNICAL_PASS_WITH_RESIDUALS`.
- 2026-08-10 10:49–10:52: After Codex strengthened provenance/replay lineage checks and produced
  a fresh current-identity Word receipt, participant 1 resumed the same Pi session
  `019fe981-3e54-7000-a68e-ae2c4ff8afaa`. It independently reran 67 functional tests, recomputed
  producer/receipt/artifact/page/OOXML identities and returned `READY`; no fallback or prohibited
  test occurred. The durable participant report records sources and checks; metrics retain the
  43-tool-call count and route/session evidence.
