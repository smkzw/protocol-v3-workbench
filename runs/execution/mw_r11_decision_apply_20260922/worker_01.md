All checks pass. The batch is complete and verified. Final report follows.

# Execution Output: mw_r11_decision_apply_20260922 - worker_01

## Boundary And Context Check

- **Fallback declaration:** The primary worker (`codebuddy/codebuddy-cli/deepseek-v4.1-flash`) was unavailable before a resumable session existed. I am the declared fallback `zcode` / `GLM-5.3-Flash`, admitted under Beijing off-peak on route `codebuddy/codebuddy-cli/deepseek-v4.1-flash` per the packet branch. I preserved the same bounded role (finite code execution), source list, output path (`runs/execution/mw_r11_decision_apply_20260922/worker_01.md`, runner-persisted — I did not write it), quality gates, and one-pass protocol. Capability limitation: I did not exercise a CodeBuddy-specific environment; no work was claimed that could not be performed with my own tools.
- **Delegated mode:** Bounded worker only. No conference started, no peer review, no final visual/clinical/regulatory acceptance claimed. Codex remains final authority.
- **Initial read set:** `context/mw_r11_decision_apply_20260922_execution_context.md`, `plans/codex_execution_mw_r11_decision_apply_20260922.md`. Additional reads were required because the "Source Of Truth" section was a TODO placeholder; all reads stayed inside the workspace.

## Work Performed

State on entry: the coherent batch was already present as uncommitted changes in the working tree (backend service, API route, frontend UI, tests) — evidently left by the primary before it fell. I verified every integration point end to end, found one real defect in the resolution path, fixed it minimally, extended the focused tests, and ran the verification batch.

1. **Inspection (evidence):**
   - Authoring-journey mutation channel: `medical_writing_authoring_journey_service.adopt_prefill_candidate` (medical_writing_authoring_journey.py:4221) — `BEGIN IMMEDIATE` transaction, journey/package revision CAS, idempotent replay, audit; writes StudyDefinition via `_build_study_definition` with `revision + 1`. `SUPPORTED_ADOPT_PATHS` (medical_writing_authoring_prefill.py:102) gates writable paths; exact clinical facts remain protected in `EXACT_FACT_PATHS`.
   - Full-draft contracts: v0.4 prompt / artifact schema v4 / descriptor v4 (medical_writing_full_draft.py:44-47); durable job identity = descriptor digest; scoped descriptors carry `section_ids` so a scoped regeneration can never reuse a full-document job; `adopt` binding check invalidates stale artifacts.
   - Frontend study-design flow: WritingPage full-draft panel; decision cards rendered only for `content_status === "decision_required"` sections.

2. **Verified inherited implementation (all four required behaviors present):**
   - `MedicalWritingFullDraftService.resolve_decision` (medical_writing_full_draft.py:1139): validates all decisions against the immutable artifact → persists each answer through the injected `study_definition_writer` (the existing adopt channel; no second decision store) → artifact superseded by the StudyDefinition revision under the unchanged `adopt` binding check (zero artifact bytes rewritten) → submits a new full-draft job scoped to affected sections only. Unbound paths fail closed.
   - API: `POST /api/projects/{project_id}/medical-writing/full-drafts/{job_id}/decisions` (main.py:7892) with writer `_confirm_full_draft_decision_in_study_definition` (main.py:7854) reusing the exact CAS/idempotency/audit semantics of study-design adoption; conflict→409, validation→422; wakes the regenerated durable job.
   - Frontend (App.jsx:10505-10570, 11567-11604; styles.css:6306-6349): recommended option preselected (`fullDraftDecisionChoice` falls back to `recommended_option_id`), radio selection of an alternative, one explicit "确认该决定" button per card, then clears the old artifact and monitors only the scoped regeneration job.
   - Decision identity derived from the artifact (`fdd_` digest of section_id+question) and projected at read time — persisted artifact stays byte-identical.

3. **Defect found and fixed (my change):** `resolve_decision` wrote the option summary as a plain string for every `fact_path`. I verified empirically (Pydantic 2.13) that a `str` into a `List[str]` field such as `picos.assessment_timing_restrictions` fails `model_validate` (HTTP 422, confirmation refused), and that `map_design_adoption_to_study_updates` **silently drops** a string for `design.src_dmc`, `design.phase1_parts`, `design.arms_or_cohorts` (confirmed candidate with no study fact written — a silent wrong-write, worse than a refusal). Both break the assigned "one confirmation persists the answer" requirement. Fix in medical_writing_full_draft.py:
   - New `_decision_fact_value` (:1108): shapes the confirmed prose to the declared field type read from the authoritative contract models (`MedicalWritingStudyFraming`, `MedicalWritingPicosDefinition`) — string-list fields receive a single-item list (same replacement semantics as candidate adoption); scalar and `design.*` paths pass through unchanged.
   - New `_DECISION_STRUCTURED_DESIGN_PATHS` (:57): the three structured design paths now fail closed with a precise message directing the user to confirm in the study-design flow, consistent with the service's "unbound decision fails closed" principle — a decision card's prose cannot soundly produce the required dict input.
   - Existing test updated for list shaping; two focused tests added (`test_decision_fact_value_matches_declared_field_type`, `test_decision_targeting_structured_design_path_fails_closed`).

## Artifacts And Evidence

- `services/api/app/medical_writing_full_draft.py` — imports (+2 contract models, `get_origin/get_args`), `_DECISION_STRUCTURED_DESIGN_PATHS` (:57), `_decision_fact_value` (:1108), `resolve_decision` wiring (:1139); inherited: scoped descriptor/submit, decision identity/index, read-time projection, `resolve_decision`.
- `services/api/app/main.py` — decisions endpoint (:7892) and StudyDefinition writer (:7854).
- `frontend/src/App.jsx` — decision choice state/busy/message, `resolveFullDraftDecision` (:10511), decision-card radio UI + one confirm button (:11567-11604).
- `frontend/src/styles.css` — `.full-draft-decision-choices`, `.full-draft-decision-confirm` (:6306+).
- `tests/test_medical_writing_full_draft.py` — 6 decision/scoped tests including my 2 additions (:541, :565).

## Commands And Observations

- `python3 -m unittest tests.test_medical_writing_full_draft -v` → **Ran 22 tests, OK** (0.059s). ResourceWarnings about unclosed sqlite connections are pre-existing test-store noise.
- `python3 -m py_compile services/api/app/main.py services/api/app/medical_writing_full_draft.py` → OK.
- Spot-check of `_decision_fact_value`: scalar→str, `picos.assessment_timing_restrictions`→list, nested `framing.product_profile.administration_routes`→list, `design.blinding`→str, unknown root→str. All as designed.
- `npx vite build` (frontend) → built cleanly in 1.98s (pre-existing chunk-size warning only).
- Verified empirically before fixing: `MedicalWritingPicosDefinition.model_validate({"assessment_timing_restrictions": "<str>"})` raises `ValidationError list_type` — confirming the defect was real, not theoretical.

## Blockers Or Missing Environment

- `python3` (3.14, has all project deps) has no `pytest`; `python3.12` has pytest but lacks `cryptography`. The README convention (`python3 -m unittest discover -s tests`) runs unittest-style modules. Per risk boundaries I did **not** install anything. Consequence: pytest-styled module `tests/protocol_v3/test_draft_marker_context.py` (which function-locally imports `FullDraftServiceTests`) could not be executed this session.
- Full test suite and real-browser rendered verification of the decision card UI were not run — outside this worker's assigned checks and authority (Codex owns rendered acceptance).

## Rerun Requests Or Next Step

For Codex acceptance, in priority order:

1. Run `python3 -m pytest tests/protocol_v3/test_draft_marker_context.py` in the properly provisioned environment (or unittest the rest of the suite) to confirm the adjacent consumer.
2. Rendered acceptance of the decision card flow (recommended preselected, alternative selectable, one confirm → scoped regeneration progress) in the running workbench.
3. Product decision to record: mid-batch failure semantics — if the 2nd of N decision writes raises (e.g., CAS conflict), the 1st write persists and supersedes the artifact; the client cannot re-resolve the remaining decisions from the same artifact (binding check refuses) and the regenerated scoped job will re-raise those decision cards. This inherits existing adopt-channel semantics; I left it as-is rather than inventing a compensating transaction.
4. Minor observation for a future pass: the frontend idempotency key embeds `Date.now()`, so a user retry after a mid-batch failure re-writes previously persisted decisions as new confirmations (each audited). Same semantics as the existing per-candidate adopt UI; harmless but worth knowing during acceptance.
