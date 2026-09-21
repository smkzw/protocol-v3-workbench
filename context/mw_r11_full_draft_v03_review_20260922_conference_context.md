# Conference Context: mw_r11_full_draft_v03_review_20260922

Created: 2026-09-22 00:46:14 CST
Objective: Independently review the frozen Study A Protocol v3 full-draft v0.3 candidate and current v0.2 review projection against authoritative StudyDefinition revision 8 and AI-lead product acceptance. Determine adoption readiness, unsupported project-specific rules, cross-section inconsistency, excessive repetition, missing submission content, and exact remediations. Review only; do not modify source or runtime artifacts.
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

- Linked execution task: `mw_r11_full_draft_v03_review_20260922`
- Execution evidence status: `no linked execution packet`
- Excluded route identities: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. The complete agent/provider/model boundary is retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Primary readable packet: `context/mw_r11_full_draft_v03_review_20260922_source_packet.md`, SHA-256 `e010a1125d8949ebeba843fe2c0f0474bc81065b10c9bf58e144533ab0f0bccf`. It contains the authoritative StudyDefinition revision 8 extract and all 85 candidate sections with user-facing evidence notes and current review projection.
- Frozen raw candidate: `runs/requirements_v2_20260919/f12_20260921/three_studies/isolated_runtime/medical_writing_full_drafts/proj_user_8a5a00cb014a/mwjob_ccfa294601420a96bd660cf9/full-draft.json`, SHA-256 `c2e98124598aa71a2e36eedb173cd24163d8a8504f41d9996a963cf241192da9`.
- Generator and review policy: `services/api/app/medical_writing_full_draft.py`, `services/api/app/ai_task_runner.py`, `services/api/app/medical_writing_content_quality.py`, and `services/api/app/medical_writing_corpus_policy.py`.
- Current product goal and constraints: `plans/protocol_v3_fork_execution_20260921/GOAL_PROMPT.txt` and `.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md`.
- Do not read or emit `ai_provider_secrets.json`; credentials and raw transport payloads are outside this review.

## Scope

- In scope: review every section against its heading and StudyDefinition; identify unsupported fixed conduct rules, contradictions, omission hidden by generic prose, unnecessary design repetition, weak evidence notes, and excessive review burden. Assess whether this candidate can be adopted as a usable first draft for a senior medical writer. Give section-number evidence and the smallest coherent corrections.
- Out of scope: modifying files or databases, web research, rerunning any model, making efficacy or safety conclusions about the synthetic drug, or claiming formal medical/statistical/PV approval.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No production path is read or modified; Codex retains final acceptance.
- The verdict is `PASS`, `FAIL`, or `UNVERIFIED` for adoption readiness and cites section numbers for every material finding.
- The review distinguishes confirmed defects, inference, and missing project decisions. It explicitly assesses whether 18 mandatory cards are proportionate and whether the 85-card presentation supports the AI-lead user goal.

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

- 2026-09-22 00:46:14 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
