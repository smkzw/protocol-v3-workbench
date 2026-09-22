# Conference Context: mw_r11_v05_medical_review_20260922

Created: 2026-09-22 08:42:40 CST
Objective: Fresh independent medical review of Study A v0.5 full-draft candidate: assess source-bounded scientific content, cross-section consistency, unsupported operational rules, decision-card quality, source gaps, and whether any prose may proceed toward user review; do not modify or adopt the artifact.
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

- Linked execution task: `mw_r11_v05_medical_review_20260922`
- Execution evidence status: the product run was outside a guard execution packet; artifact and AI-run store prove 22/22 effective runs used `opencode-go/deepseek-v4.1-flash`.
- Excluded route identity for independent opinion: any `deepseek-v4.1-flash` reviewer. Codex therefore selected the manifest-listed fresh fallback `zcode/zcode/GLM-5.3-Flash:max` by explicit route rather than the generated same-model primary.
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. The complete agent/provider/model boundary is retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Frozen candidate: `runs/requirements_v2_20260919/f12_20260921/three_studies/isolated_runtime/medical_writing_full_drafts/proj_user_8a5a00cb014a/mwjob_bf28987c132c1b13527f252a/full-draft.json`, SHA-256 `a9731b65bf919ac83cb32da94b16fae6a24e857c08df39d6a83cb8b1d6c59c40`.
- The artifact contains the authoritative StudyDefinition binding, 85 target-section identities/headings, 85 generated section candidates, 73 decision items, 13 source gaps, 104 source bindings and 367 section-scoped evidence bindings.
- Product contract: `plans/protocol_v3_fork_execution_20260921/CLINICAL_CONTENT_CONTRACT.md`.
- User/product requirements: `plans/protocol_v3_fork_execution_20260921/03_PRD.md`.
- v0.5 provenance stage record: `runs/requirements_v2_20260919/t17_round11/STUDY_A_FULL_DRAFT_V05_EVIDENCE_PROVENANCE_20260922.md`.
- Engineering evidence-chain review: `reviews/codex_conference_mw_r11_v05_evidence_review_20260922_review.md`; use it only to trust artifact integrity, not as a medical opinion.

## Scope

- In scope: every one of the 85 sections; consistency with embedded confirmed study facts; unsupported or over-specific medical/operational rules; contradictions across sections; adequacy and answerability of 73 decision cards; whether missing inputs are correctly expressed as source gaps; evidence quote relevance; scientific/regulatory Chinese quality; a prioritized remediation plan that minimizes user effort.
- Out of scope: modifying files, adopting any section, invoking another product model, web research, assuming absent IB/SAP/CSR facts, formal statistics/PV/operations approval, Word/rendered-format acceptance, or claiming the candidate is submission-ready.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- The frozen candidate is read-only and no project/runtime path is modified; Codex retains final acceptance.

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

- 2026-09-22 08:42:40 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
