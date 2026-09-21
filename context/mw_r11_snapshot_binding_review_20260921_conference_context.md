# Conference Context: mw_r11_snapshot_binding_review_20260921

Created: 2026-09-21 20:06:55 CST
Objective: 独立只读审阅 Study A immutable registry snapshot 续接修复：核查同 registry_filter 保留快照、历史绑定恢复的严格前置条件、不得重复检索或模型分诊、真实 revision20→22 恢复证据；输出 PASS/FAIL/UNVERIFIED 与 file:line，禁止修改源码、测试、SQLite 和运行态。
Task type: `code_open_audit`
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

- Linked execution task: `mw_r11_snapshot_binding_review_20260921`
- Execution evidence status: `no linked execution packet`
- Excluded route identities: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. The complete agent/provider/model boundary is retained, and effort differences do not bypass deduplication.

## Source Of Truth

- `services/api/app/medical_writing_authoring_journey.py`
- `services/api/app/medical_writing_competitor_triage.py`
- `tests/test_medical_writing_authoring_journey.py`
- `tests/test_medical_writing_competitor_triage.py`
- `runs/requirements_v2_20260919/f12_20260921/study_a_snapshot_binding_recovery/recovery-result.json`
- `.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md`
- Git diff for the listed source and test files. Runtime SQLite and backup files are out of scope and must not be opened or modified.

## Scope

- In scope: read-only review of same-registry snapshot preservation, the narrow historical restoration path, retry orchestration, regression tests, and the sanitized Study A revision 20 to 22 receipt.
- Out of scope: modifying any file; opening SQLite, WAL, SHM, credential, or provider-setting files; running models, searches, downloads, OCR, translation, services, or browser journeys; assessing unrelated Protocol v3 features.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No runtime database or credential file is read or modified; Codex retains final acceptance.

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

- 2026-09-21 20:06:55 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
