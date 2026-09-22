# Conference Context: mw_r11_full_draft_review_20260921

Created: 2026-09-21 22:52:29 CST
Objective: Independently review the frozen Study A Protocol v3 full-draft candidate against the authoritative StudyDefinition revision 8 and the product goal. Identify unsupported project-specific rules, drafting-process language, irrelevant repetition, section insufficiency, and the smallest reliable product correction before adoption. Review only; do not modify source or runtime artifacts.
Task type: `clinical_evidence_analysis`
Risk: `high`
Conference mode: `serial`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`evidence_single_object`) with no sub-venue chair. Its effective `CST` route chain is `codebuddy/codebuddy-cli/deepseek-v4.1-flash:max -> zcode/zcode/glm-5.3-flash:max -> grok/grok-build/grok-4.6:high -> pi/cursor/cursor-grok-4.6:high -> pi/openai-codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_r11_full_draft_review_20260921`
- Execution evidence status: `no linked execution packet`
- Excluded route identities: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. The complete agent/provider/model boundary is retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Frozen candidate (read-only): `runs/requirements_v2_20260919/f12_20260921/three_studies/isolated_runtime/medical_writing_full_drafts/proj_user_8a5a00cb014a/mwjob_ca1eb8feb6baceb8d4fb9eb7/full-draft.json`.
- Authoritative StudyDefinition revision 8 (read-only): table `medical_writing_authoring_journeys`, column `payload_json`, object `study_definition` in `runs/requirements_v2_20260919/f12_20260921/three_studies/isolated_runtime/medical_writing_authoring_journey.sqlite3`. Identity is `mwdefinition_1ded2281210281a3b8a0`, revision 8, SHA-256 `3989470f61c21914c0df6910a0a80af4593ce2b08bbd31281cf44e0b069f272e`.
- Generator and validator implementation (read-only): `services/api/app/medical_writing_full_draft.py`, `services/api/app/ai_task_runner.py`, and `services/api/app/medical_writing_content_quality.py`.
- Current product goal and acceptance boundaries: `plans/protocol_v3_fork_execution_20260921/GOAL_PROMPT.txt` and `.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md`.
- Deterministic owner findings to challenge independently: 85/85 candidate sections, no simple TBD/internal token/competitor-drug-name hits; four proposals contain drafting-process language; project facts are repeated in many unrelated sections; the contraception appendix adopts substantive methods from company corpus although StudyDefinition confirms only exclusion of pregnant/lactating women.
- Do not read or emit `ai_provider_secrets.json`; credentials and raw model prompts are outside this review.

## Scope

- In scope: compare every candidate section with its heading and the authoritative definition; sample enough sections to establish recurring patterns; identify unsupported project-specific conduct rules, misleading filler, source-commentary/AI traces, repetitions that reduce usability, and sections that require missing material rather than prose fabrication. Assess whether the artifact may be adopted now. Propose the smallest product/data-contract correction and concrete acceptance checks.
- Out of scope: modifying any file or SQLite database, web research, judging the actual efficacy or safety of the synthetic drug, replacing formal medical/statistical/PV approval, rerunning generation, or changing model routes.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No production path is read or modified; Codex retains final acceptance.
- Return `PASS`, `FAIL`, or `UNVERIFIED` for adoption readiness; cite local file/section identities for every material finding; distinguish deterministic facts from reviewer inference.

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

- 2026-09-21 22:52:29 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
