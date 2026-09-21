# Codex Review: mw_r11_full_draft_v04_contract_20260922

Date: 2026-09-22
Delegated-agent output: `runs/codebuddy_mw_r11_full_draft_v04_contract_20260922.md`

## Verdict

`PASS_FOR_CONTRACT_IMPLEMENTATION` after Codex integration and concentrated verification. This verdict covers the v0.4 contract and review projection only. It does not accept any generated medical content or mark Study A ready for adoption.

## Boundary Check

- The delegated CodeBuddy session used the declared `codebuddy-cli/deepseek-v4.1-flash:max` route and returned terminally without fallback.
- It made no workspace source edit because its native session remained in plan mode. Its report disclosed the blocker. It read three adjacent implementation surfaces outside the packet's literal initial read set (`ai_execution_policy.py`, `main.py`, and `frontend/src/App.jsx`); these were read-only but exceeded the stated read boundary and are recorded as a process defect.
- The worker also wrote its harness-owned plan under `~/.codebuddy/plans`; that file is outside the repository and is not accepted as task evidence.
- Codex did not redispatch. It inspected the current source, used the worker's analysis only as advisory evidence, and implemented the coherent batch directly. Runtime JSON, v0.3 artifacts, live services and StudyDefinition data were not edited by this task.

## Codex Verification

- The Hermes review gate was applied to this Codex review and metrics pair. The generic execution audit could not parse an immutable worker manifest because this older packet was initialized with `init-task`, not `init-execution`; this packet-shape limitation is recorded and is not represented as an audit pass.
- Source trace covers prompt schema, gateway validation, same-model structural correction, artifact persistence/read compatibility, review projection, pre-write adoption checks, frontend decision/source-gap rendering, and prompt-version registration.
- v0.4 requires `content_status`, structured decision choices and named source gaps. `source_gap` cannot contain filler prose or evidence IDs. `decision_required` must contain 2–3 complete choices and exactly one listed recommendation.
- Any unresolved decision or source gap blocks all section writes. Legacy v0.3 remains readable but is explicitly read-only because its immutable Study A artifact has known unsupported rules.
- Final focused regression after all edits: `105 passed` across `tests/test_medical_writing_full_draft.py`, `tests/test_ai_gateway.py`, and `tests/test_ai_task_runner.py` using the repository's Python 3.12 environment. The broader affected backend suite had already passed `163` tests before the final legacy/read-only tightening; the final tightening touched only the three rerun modules.
- The same frontend changes had already passed the authoritative `110 Vitest + 65 Node` inventory and the production build (`1971` modules). No frontend source changed after that run.
- `git diff --check` passed.

## Delegated-Agent Output Review

The worker correctly identified the prompt-version pin, the need for exact status-dependent validation, and the need to keep StudyDefinition resolution upstream. Its proposed claim that legacy v3 should remain adoptable was rejected: the independently reviewed v0.3 artifact contains unsupported operational rules, so read compatibility cannot imply write eligibility. Its implementation report is not treated as execution evidence because no implementation or test occurred in that session.

## Residual Risk

- A real v0.4 product-model run has not yet been reviewed. Contract PASS is not content PASS.
- The current frontend presents recommended and alternative choices but does not yet persist a choice directly into the upstream StudyDefinition. The user must enter the existing study-design flow; closing that one-click loop is the next product batch.
- Unsupported-rule detection is deliberately narrow and deterministic. Independent medical review remains required on the actual v0.4 artifact.
