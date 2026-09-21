# Conference Context: mw_r11_human_reconfirmation_review_20260921

Created: 2026-09-21 21:03:51 CST
Objective: 独立审阅Protocol v3既有竞品篮子按当前医学条件人工复核与受控重绑实现，验证不会重复AI、检索、下载、OCR或翻译，并检查状态一致性、审计链、API与前端交互。
Task type: `C01`
Risk: `high`
Conference mode: `serial`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`general_single_object`) with no sub-venue chair. Its effective `CST` route chain is `zcode/zcode/glm-5.3-flash:max -> codebuddy/codebuddy-cli/deepseek-v4.1-flash:max -> codex-subagent/codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_r11_human_reconfirmation_review_20260921`
- Execution evidence status: `no linked execution packet`
- Excluded route identities: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. The complete agent/provider/model boundary is retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Current git diff against `HEAD` for the files below; unrelated dirty runtime files are outside review scope.
- `packages/contracts/workbench_contracts/models.py`
- `packages/contracts/workbench_contracts/__init__.py`
- `services/api/app/medical_writing_authoring_journey.py`
- `services/api/app/medical_writing_competitor_triage.py`
- `services/api/app/main.py`
- `frontend/src/features/writing-reference/WritingReferencePanel.jsx`
- `frontend/src/features/writing-reference/triagePresentationState.mjs`
- `frontend/src/styles.css`
- `tests/test_medical_writing_competitor_triage.py`
- `tests/test_medical_writing_triage_recovery_api.py`
- `frontend/src/features/writing-reference/triagePresentationState.test.mjs`
- `.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md`
- Prior accepted fix commit: `3676ac2145fe1872f9dcb8e1ab3be92334971f16`.
- Concentrated verification before review: 450 relevant backend tests pass; frontend official inventory 15 Vitest files/110 tests plus 48 Node files/65 tests passes; production build transforms 1971 modules; `git diff --check` passes.

## Scope

- In scope: correctness and minimum completeness of the new human re-review/rebind path; immutable snapshot reuse; stale/fresh identity; confirmation lineage and idempotency; projection retry; endpoint behavior; concise AI-lead frontend; regression-test adequacy; over-engineering that should be removed.
- Required invariant: no AI provider, registry search, download, OCR, translation, or parent research-pipeline advance from the re-confirm action.
- Required behavior: current medical triage criteria are visible as bullets; all prior human classifications are preselected; user can optionally adjust and confirm once; a new human confirmation records lineage and rebinds the unchanged snapshot.
- Out of scope: modifying files, running external model/product workflows, live Study A mutation, browser/visual acceptance, formal clinical approval, unrelated runtime files and prior untracked evidence.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No file is modified; Codex retains final acceptance.

## Conference Pass Rule

This packet uses one serial Codex-led conference object. Each declared role receives one complete prompt and may use multiple internal tool turns. Codex decides whether a same-session follow-up is needed after reviewing the result; follow-ups do not create a new conference or change the route identity.

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

- 2026-09-21 21:03:51 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
