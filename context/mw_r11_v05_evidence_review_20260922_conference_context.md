# Conference Context: mw_r11_v05_evidence_review_20260922

Created: 2026-09-22 04:51:26 CST
Objective: Independently review frozen commit 58639c7 for clinical draft evidence provenance, recovery compatibility, and adoption safety; report only evidence-backed defects and do not modify source.
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

- Linked execution task: `mw_r11_v05_evidence_review_20260922`
- Execution evidence status: `no linked execution packet`
- Excluded route identities: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. The complete agent/provider/model boundary is retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Frozen implementation: git commit `58639c7` and its parent `8aabfea`.
- `services/api/app/medical_writing_full_draft.py`
- `tests/test_medical_writing_full_draft.py`
- `tests/test_ai_gateway.py`
- `tests/test_ai_task_runner.py`
- `runs/requirements_v2_20260919/t17_round11/STUDY_A_FULL_DRAFT_V05_EVIDENCE_PROVENANCE_20260922.md`
- Historical v0.4 candidate, read only: `runs/requirements_v2_20260919/f12_20260921/three_studies/isolated_runtime/medical_writing_full_drafts/proj_user_8a5a00cb014a/mwjob_96ee70138c21a86568eb3f3d/full-draft.json`
- Test evidence: 115 selected tests passed after the frozen change. Re-run focused deterministic checks if needed; do not invoke product models or modify runtime data.

## Scope

- In scope: evidence-ID scope/collision behavior, source/locator/quote persistence, tamper and reuse checks, v3/v4 read compatibility, v5 adoption preconditions, schema/descriptor versioning, and missing focused tests.
- Out of scope: editing source, regenerating Study A, calling any product model, adopting a draft, changing provider configuration, reviewing medical prose quality, UI/Word acceptance, or reading credentials.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No workspace file is modified; Codex retains final acceptance.

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

- 2026-09-22 04:51:26 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
