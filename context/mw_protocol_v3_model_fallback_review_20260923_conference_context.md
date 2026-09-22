# Conference Context: mw_protocol_v3_model_fallback_review_20260923

Created: 2026-09-23 01:07:46 CST
Objective: 只读独立审阅Protocol v3综合AI用户自选provider/model/思考强度与MTPLX到OpenCode Go再到CMS Router的2+1自动降级实现；检查错误分类、身份/effort回执、全文chunk provenance、旧任务兼容、UI可理解性和测试缺口。不得修改源码。
Task type: `C03`
Risk: `high`
Conference mode: `serial`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`evidence_single_object`) with no sub-venue chair. Its effective `CST` route chain is `codebuddy/codebuddy-cli/deepseek-v4.1-flash:max -> zcode/zcode/glm-5.3-flash:max -> grok/grok-build/grok-4.7:high -> pi/cursor/grok-4.7-high:high -> pi/openai-codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_protocol_v3_model_fallback_review_20260923`
- Execution evidence status: `no linked execution packet`
- Excluded route identities: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. The complete agent/provider/model boundary is retained, and effort differences do not bypass deduplication.

## Source Of Truth

- `services/api/app/ai_runtime_settings.py`
- `services/api/app/ai_role_runtime_settings.py`
- `services/api/app/ai_execution_policy.py`
- `services/api/app/ai_task_runner.py`
- `services/api/app/medical_writing_full_draft.py`
- `services/api/app/main.py`
- `packages/contracts/workbench_contracts/models.py`
- `frontend/src/App.jsx`
- `frontend/src/styles.css`
- `tests/test_ai_fallback_chain.py`
- `tests/test_ai_execution_policy.py`
- `tests/test_ai_role_runtime_settings.py`
- `tests/test_medical_writing_full_draft.py`
- `runs/requirements_v2_20260919/wp6_0922v2_20260922/MODEL_ROUTING_2PLUS1_ACCEPTANCE_20260923.md`
- `runs/requirements_v2_20260919/wp6_0922v2_20260922/study_a_v10_route_receipt_reconciliation.json`
- `runs/requirements_v2_20260919/wp6_0922v2_20260922/study_b_route_acceptance.json`
- `runs/requirements_v2_20260919/wp6_0922v2_20260922/study_c_route_acceptance.json`
- Use `git diff --` limited to the named source and test files to identify the current change. Existing unrelated dirty files are evidence of other WP6 work and must not be edited.

## Scope

- In scope: read-only code review of route profile persistence, user selection, fallback eligibility, canonical request rebuild, per-attempt audit lineage, registered/internal execution parity, chunk/final provenance, old in-flight run compatibility, and concise UI behavior. Verify claims against the named tests and acceptance JSON. Report findings by severity with file and line references.
- Out of scope: editing any file; rerunning product models; reading credentials or secret files; touching live services; broad review of unrelated Protocol v3 features; formal medical acceptance of generated Study A/B/C prose.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No source or runtime artifact is modified; Codex retains final acceptance.

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

- 2026-09-23 01:07:46 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
