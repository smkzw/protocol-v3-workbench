# Conference Context: mw_r11_v07_medical_review_20260922

Created: 2026-09-22 11:46:10 CST
Objective: Fresh independent medical review of Study A v0.7 full-draft candidate: assess all 85 sections for consistency with embedded confirmed facts, unsupported medical or operational rules, decision-card quality, true source gaps, evidence relevance, user cognitive load, and whether the candidate can proceed toward user review; do not modify or adopt the artifact.
Task type: `clinical_evidence_analysis`
Risk: `high`
Conference mode: `serial`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`evidence_single_object`) with no sub-venue chair. Its effective `CST` route chain is `grok/grok-build/grok-4.7:high -> pi/cursor/grok-4.7-high:high -> pi/openai-codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_r11_v07_medical_review_20260922`
- Execution evidence status: `no linked execution packet`
- Excluded route identities: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. The complete agent/provider/model boundary is retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Frozen candidate: `runs/requirements_v2_20260919/f12_20260921/three_studies/isolated_runtime/medical_writing_full_drafts/proj_user_8a5a00cb014a/mwjob_6ea88e6715579409992c43ee/full-draft.json`, SHA-256 `e199d57fd14d6d78ea630e02bdc8ba20592f01dc06233f4fd83d32f41c1a99ce`.
- The artifact embeds the authoritative StudyDefinition binding, 85 target sections, 85 generated sections, 75 complete sections, 3 decision-required sections containing 4 decisions, 7 source gaps, 218 evidence references, 22 unique AI run IDs, and 21 required-review sections.
- Product generator runtime identity: `opencode-go/deepseek-v4.1-flash:max`; the independent reviewer route is intentionally different.
- Product contract: `plans/protocol_v3_fork_execution_20260921/CLINICAL_CONTENT_CONTRACT.md`.
- User/product requirements: `plans/protocol_v3_fork_execution_20260921/03_PRD.md`.
- Earlier v0.5 medical review: `runs/conference/mw_r11_v05_medical_review_20260922/evidence_single_object.md`; use only to verify whether identified classes of defect were actually closed, not as authority over v0.7.

## Scope

- In scope: all 85 section proposals, rationales, statuses, evidence bindings, 4 decision items, 7 source gaps, cross-section consistency, medical/statistical/PV/operational unsupported rules, scientific Chinese quality, and user cognitive load.
- Out of scope: modifying source or runtime files, adopting any section, invoking the product generator, web research, assuming absent IB/SAP/SMP/pharmacy/manual facts, formal professional approval, Word/rendered-format acceptance, or claiming submission readiness.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- The frozen candidate is read-only, no source/runtime file is modified, no adoption endpoint is called, and Codex retains final acceptance.

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

- 2026-09-22 11:46:10 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
