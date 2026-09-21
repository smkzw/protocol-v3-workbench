# Task Context: mw_r11_full_draft_v04_contract_20260922

Created: 2026-09-22 01:17:14
Objective: Implement the smallest coherent Protocol v3 full-draft v0.4 contract: AI output decision items with recommended and alternative options, explicit source-gap state, rejection of unsupported prescriptive rules, and decision-level review/adoption. Preserve immutable v0.3 artifacts. Work only in full-draft/gateway/task-runner contracts, focused tests, and a worker report; do not touch runtime data or run product models.
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `codebuddy-cli` / `deepseek-v4.1-flash` / `max`

## Trigger Reason

The v0.3 independent review found a contract-level defect shared by prompt schema, validation, persistence and adoption. A bounded worker can implement that cohesive backend slice while Codex retains the live browser, clinical synthesis and final integration.

## Source Of Truth

- `AGENTS.md`
- `runs/requirements_v2_20260919/t17_round11/STUDY_A_FULL_DRAFT_V03_20260922.md`
- `reviews/codex_conference_mw_r11_full_draft_v03_review_20260922_review.md`
- `runs/conference/mw_r11_full_draft_v03_review_20260922/evidence_single_object.md`
- `services/api/app/medical_writing_full_draft.py`
- `services/api/app/ai_gateway.py`
- `services/api/app/ai_task_runner.py`
- `tests/test_medical_writing_full_draft.py`
- `tests/test_ai_gateway.py`
- `tests/test_ai_task_runner.py`

## Scope

- In scope: edit only the three backend modules and three focused test files listed above.
- In scope: upgrade the full-draft schema/version to v0.4; add per-section `content_status=complete|decision_required|source_gap`; add structured `decision_items` and `missing_source_classes`; keep complete prose separate from missing facts.
- In scope: require each decision item to contain a concise question, one recommended option, 1-2 alternatives, rationale and the section it blocks. The options are advisory only and must not write StudyDefinition or become protocol prose.
- In scope: permit source-gap sections to have no proposal body and exempt only those sections from the minimum-body rule.
- In scope: make any decision-required or source-gap section prevent whole-draft adoption and return exact counts/section IDs in artifact coverage.
- In scope: reject complete sections whose rationale says a rule is unsupported/undecided while the proposal writes that rule as an established project requirement.
- Out of scope: frontend edits, runtime data, durable v0.3 artifacts, StudyDefinition writes, decision persistence, product-model calls, triage/download/OCR/translation, git commit/push.

## Success Criteria

- Legacy v0.3 artifacts remain readable through their current projection and are never rewritten.
- New v0.4 model output has exact deterministic validation and same-model correction support.
- `complete` sections remain substantive and source-bound.
- `decision_required` sections expose 2-3 choices with exactly one recommendation.
- `source_gap` sections name the missing source class and do not use generic filler to satisfy length.
- Adoption rejects artifacts with unresolved decisions or source gaps before any section write.
- Tests are authored with the implementation. Run one concentrated focused suite only after all edits are complete; do not test after each file.

## Risk Boundaries

- Writable paths are exactly the six in-scope source/test files. Do not touch any other path.
- Do not alter user-facing runtime data, generated artifacts, expected scientific facts, or test inventory gates.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, malformed output, or a stale/incomplete catalog must be recorded and followed by one real route attempt. Explicit user-selected routes are not blocked merely because the catalog does not list them; only a missing executable or native transport boundary may stop before that attempt.

## Loop Log

- 2026-09-22 01:17:14: Task initialized by `tools/hermes_workflow_guard.py init-task`.
