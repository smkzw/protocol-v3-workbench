I'll start by reading the task context file.

Bash is denied; I'll use Read/Grep and record this for the verification section. Continuing with the sources.

Research is complete. Writing the plan.

I could not execute. Plan mode is active in this session, and both write-permission paths were denied:

- `Bash` → `Permission to use Bash has been denied ... permission prompts are not available in non-interactive mode`
- `ExitPlanMode` → `Permission to use ExitPlanMode has been denied`

Plan mode explicitly supersedes the delegated instruction to edit, so no file in the workspace was touched. The complete design is written to `/Users/smkzw/.codebuddy/plans/radiant-vortex-darwin-bo9Qdt1N.md` and summarized below so the runner can either re-dispatch with write permissions or hand it to Codex directly.

# Execution Report: mw_r11_full_draft_v04_contract_20260922

## Boundary Check

- Read set used: `context/mw_r11_full_draft_v04_contract_20260922_context.md`, the project `AGENTS.md`, `runs/requirements_v2_20260919/t17_round11/STUDY_A_FULL_DRAFT_V03_20260922.md`, `reviews/codex_conference_mw_r11_full_draft_v03_review_20260922_review.md`, `runs/conference/mw_r11_full_draft_v03_review_20260922/evidence_single_object.md`, the three in-scope backend modules and three in-scope test files, plus three read-only integration checks outside the read set (`services/api/app/ai_execution_policy.py`, `services/api/app/main.py` full-draft routes, `frontend/src/App.jsx` full-draft view) to confirm no cross-module break. No production path, no runtime data, no secret file, no model call, no git operation.
- Writes performed: **none**. The only file written is the harness plan file `/Users/smkzw/.codebuddy/plans/radiant-vortex-darwin-bo9Qdt1N.md`, which is outside the workspace and not a task artifact.
- Not claimed: no final clinical/regulatory/visual acceptance; no test run performed (see `Concentrated Verification`).

## Files Changed

None. `git status` was not run (Bash denied); the six in-scope files are byte-identical to the state described in `Source Of Truth`. The working tree is recoverable and unchanged — no partial edit needs reverting.

Planned edit set (not applied), design complete in the plan file:

1. `services/api/app/ai_gateway.py` — v0.4 section contract constants, `protocol_full_draft_decision_item_contract()`, prompt-contract block (`:530-563`), shared `protocol_full_draft_section_errors()` used by `_validate_protocol_full_draft_output` (`:1921-1974`). `PROTOCOL_FULL_DRAFT_CONTEXT_REQUIRED_KEYS` stays 5 keys (it is imported by `ai_execution_policy.py:28`, so it is the shared single source).
2. `services/api/app/ai_task_runner.py` — status-aware body/evidence gates, `blocking_section_id` membership, unsupported-prescriptive-rule rejection, extended same-model repair contract (`:2418-2457`, `:2782-2872`).
3. `services/api/app/medical_writing_full_draft.py` — `artifact_v4` / `chunk_v4` / `descriptor_v4`, legacy-readable schema set, v0.4 instruction, status-partitioned coverage + locator exclusions, decision/source-gap adoption gate, schema-accurate adopt result.
4. `tests/test_medical_writing_full_draft.py`, `tests/test_ai_gateway.py`, `tests/test_ai_task_runner.py` — fixtures moved to the v4 shape plus new tests for gap/decision adoption blocking, legacy v3 read, locator size, gateway shape rejections, runner gap exemption and prescriptive-rule rejection.

## Contract And Behavior

v0.4 model output, exactly 7 keys per section: `section_id, content_status, proposal_text, rationale, evidence_span_ids, decision_items, missing_source_classes`.

| `content_status` | body | evidence | `decision_items` | `missing_source_classes` |
|---|---|---|---|---|
| `complete` | ≥ minimum chars (80) | ≥1 known span | must be `[]` | must be `[]` |
| `decision_required` | ≥ minimum chars | ≥1 known span | 1–6 items | must be `[]` |
| `source_gap` | must be empty (no filler) | must be `[]` | must be `[]` | 1–4 named classes, no generic filler |

Decision item keys exactly `{question, options, recommended_option_id, rationale, blocking_section_id}`; `question` ≤160 chars ending in `？`; `options` 2–3 with unique ids and summaries ≤200 chars; exactly one `recommended_option_id` (= one recommendation + 1–2 alternatives); `blocking_section_id` must be a requested section id. Options are advisory only: no option summary (≥8 chars) may appear verbatim in `proposal_text`, nothing is written to StudyDefinition, and adoption is refused while any `decision_required` or `source_gap` section exists — resolution stays upstream and requires a new affected-section run. A `complete` section whose rationale admits an unsupported/undecided fact while the body states a high-impact conduct rule (blinding, contraception, AE/SAE reporting, dose modification, concomitant meds, washout, rescue, analysis sets, QA/audit duties, stratification, multiplicity, instrument timing) is rejected at generation with a repair-actionable message. Legacy v3 artifacts stay readable through the current projection (`required_review_*`, review policy `v0_2`), gain no v4 coverage keys, and are never rewritten.

## Concentrated Verification

- Attempted: `cd "<workspace>" && wc -l services/api/app/ai_gateway.py services/api/app/ai_task_runner.py tests/*.py` → denied: `Permission to use Bash has been denied because this tool requires approval but permission prompts are not available in non-interactive mode`.
- Planned single command, not run because all edits are blocked: `cd <repo root> && python -m pytest tests/test_medical_writing_full_draft.py tests/test_ai_task_runner.py tests/test_ai_gateway.py -q` (`pytest.ini` sets `testpaths = tests`; run from repo root so `services`/`packages` resolve).
- Verification actually performed is static only: contract trace across prompt payload, runner validation, persistence, coverage and adoption, plus a grep of `frontend/src/App.jsx` confirming the current UI reads only `coverage.required_review_count`, `coverage.required_review_section_ids`, `coverage.generated_count`, and per-section `proposal_text`/`rationale`/`review_level`/`review_evidences` — all preserved, so the additive fields do not break the live view.

## Remaining Codex Verification

1. Apply the plan (or re-dispatch this worker with write permission and Bash enabled), then run the focused pytest command above and record the pass/fail counts.
2. Confirm the v0.4 prompt contract renders as intended by inspecting one built `AiPromptEnvelope.payload` for `PROTOCOL_FULL_DRAFT` (no model call needed: assert-only test).
3. Confirm the real generation path still passes `AiExecutionResolution` — see the version constraint below before any prompt-version change.
4. Browser/rendered inspection of the review workspace with a v0.4 artifact (decision items + gap states) remains Codex-owned; the frontend does not yet render the new fields.
5. Decide whether `coverage.generated_count` keeps its current "merged candidate sections" meaning for gap sections (the plan keeps it unchanged to avoid breaking the live copy).

## Risks Or Blockers

1. **Execution blocker (this session):** plan mode + denied `Bash`/`ExitPlanMode` prevented any edit or test run. Nothing was changed, so there is no recovery action beyond re-dispatching with write permission.
2. **Prompt-version pin (important, outside my boundary):** `services/api/app/ai_execution_policy.py:72-86` hardcodes `SERVER_PROMPT_VERSIONS[AiTaskType.PROTOCOL_FULL_DRAFT] = "protocol_full_draft_v0_3"` and `_validate_common` (`:898-903`) denies any other version with `prompt version mismatch` on every `submit_internal`. That file is not in the six writable files, so bumping `FULL_DRAFT_PROMPT_VERSION` to `v0_4` would break the product generation path. The plan therefore keeps the label at `v0_3` and versions the v0.4 contract through `protocol_full_draft_artifact_v4` / `chunk_v4` / `descriptor_v4`. If Codex wants a `v0_4` prompt label, change `ai_execution_policy.py:84-86` and `medical_writing_full_draft.py:44` together.
3. **Deliberate breaking change:** the legacy 4-key model-output shape is rejected after this change (model output is transient and never persisted). Legacy persisted `protocol_full_draft_artifact_v3` files remain readable and adoptable; the descriptor digest change produces new jobs, so no v0.3 artifact or chunk is rewritten or reused.
4. **Strictness trade-off:** the unsupported-prescriptive-rule check is a conservative conjunction (rationale admits a missing fact + body states a high-impact conduct rule) and can reject an otherwise serviceable section; the correct recovery is `decision_required` plus a decision item, and the correction turn is told this explicitly. This is a fail-closed choice, not a verified medical judgement.
5. **Unverified:** no test run, no rendered inspection, no live API check — none of the acceptance-relevant evidence exists yet for this change.
