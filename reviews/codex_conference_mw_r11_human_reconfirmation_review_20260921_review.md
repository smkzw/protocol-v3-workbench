# Codex Conference Review: mw_r11_human_reconfirmation_review_20260921

Date: 2026-09-21

Workflow: Codex-chaired conference initialized and validated with the Hermes workflow guard. The actual participant route was Z Code / zcode-live-bigmodel / GLM-5.3-Flash:max; no fallback occurred.

## Verdict

PASS after owner correction. The implementation now supports one explicit human re-review of an existing immutable search basket under current medical criteria, with no new AI triage, registry search, download, OCR, translation, or parent-pipeline advance.

## Boundary Compliance

The reviewer remained read-only, worked only inside the authorized repository, did not access live runtime databases or services, and did not modify the reviewed artifact. Codex retained integration and acceptance authority.

## Material Findings And Disposition

- Accepted F1/F5: a failed rebind previously left the run `confirmed`, hiding the retry path while the journey had no active basket. The run now becomes `projection_pending`; successful retry returns it to `confirmed`. The UI reports saved review plus pending synchronization instead of false success.
- Accepted F2: an initial confirmation after a revision-only title change could immediately request another review. Initial confirmations now compare material facts at the run revision; human reconfirmations compare at their own confirmation revision.
- Accepted F3: journey conflicts and stale projection retries now map to HTTP 409.
- Accepted F4: corpus audit text distinguishes human reconfirmation from AI triage and supplies a deterministic fallback when all candidates are excluded without optional prose.
- Accepted F6 in bounded form: added coverage for revision-only confirmation, failed human projection followed by retry, run-state recovery, and same-key replay without duplicate relevance decisions.
- Accepted F7 as an explicit prior user decision: arbitrary minimum-length reasons are removed. The field remains available, and a deterministic audit reason is stored when omitted.
- Deferred low-value F8 items: no extra state system or tie-breaker was added. Missing search plans remain a conflict and cannot silently rebind.

## Independent Evidence

Participant output: `runs/conference/mw_r11_human_reconfirmation_review_20260921/general_single_object.md`.

Session `sess_a19b465f-8d17-4bcb-bf41-c7f9af5fa580` completed one pass in 1535.527 seconds. Runtime identity was verified as GLM-5.3-Flash:max with 45 model requests and 122651 cumulative tokens.

The reviewer directly traced all external-work entry points and found none on the reconfirm path. It reproduced the hidden projection-failure state and revision-only false positive before owner repair.

## Owner Verification

- Related backend tests: 450 passed, 17 pre-existing deprecation warnings.
- Protocol v3 suite: 2601 passed, 1 Python tar-behavior warning.
- Frontend official inventory: 15 Vitest files/110 tests and 48 Node files/65 tests passed.
- Frontend production build: 1971 modules transformed successfully.
- Python compile and `git diff --check`: passed.
- The first broad test command omitted legacy test import directories and collected no tests; the corrected command used the complete project test path. A later combined-suite run exposed test-state pollution in three API tests and one real inventory drift. Running the suites through their established isolation removed the pollution; the inventory was updated and the full Protocol v3 suite passed.

## Scope Limit

This closes the deterministic implementation and review batch. It does not mutate Study A runtime data, does not claim browser rendering acceptance, and does not mark the overall Protocol v3 product complete.
