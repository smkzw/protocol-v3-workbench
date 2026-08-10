# Codex Review: mw_protocol_v3_phase0_task07_20260810

Date: 2026-08-10 09:27 CST
Delegated-agent output: `runs/codex_mw_protocol_v3_phase0_task07_20260810.md`

## Verdict

**PASS for Task 0.7 Word native receipt contract only. `P0-WORD` remains blocked pending Task 0.8; this is not a producer, Word runtime or Protocol release acceptance.**

## Boundary Check

- Codex executed the Hermes workflow guard-selected direct route; Hermes itself was not dispatched. No delegated worker, conference participant, provider fallback or model call was started.
- Product writes are limited to `pocs/protocol_v3/word_receipt/`; tracking writes are limited to this task's context/prompt/review/metrics.
- The legacy workbench, historical Word script/reviews and current product receipt models/repository were read-only. No Word, service, browser, OCR, translation or project runtime was started.
- Medical-monitoring files were not used as implementation inputs and were not modified.
- Per the user's explicit correction, no security, adversarial, permission, path, symlink, TOCTOU or destructive-state test was run or dispatched.

## Codex Verification

- `python3 -m pytest pocs/protocol_v3/word_receipt/tests -q` -> `55 passed`.
- Python compile for the contract and focused test passed; `fixtures.json` parsed with `python3 -m json.tool`; `git diff --check` passed.
- The checked-in positive fixture validates exact source/input/semantic/template/producer identity, full Word object workflow, ordered PDF pages, page manifest, OOXML binding and no-external-edit lineage.
- Functional negative tests reject omitted minimum evidence, unknown fields, LibreOffice/HTML/download-only labels, repaired open, main-story-only fields, update errors, field loss, no TOC, missing/substituted fonts, absent/incorrect/duplicate bookmarks, unresolved or misbound REF/PAGEREF, incomplete or non-Word pages, unresolved page dependency provenance, bad page manifest, bad OOXML binding, mutable artifacts, malformed external edit lineage, stale identities and invalid timestamps.
- The historical AppleScript trace is a deterministic negative fixture and cannot be upgraded merely because its legacy `result` is `ok`.

## Direct Work Review

- The contract is producer-neutral and side-effect free. It cannot open Word, mutate DOCX/PDF files, persist receipts or choose AppleScript/add-in/bridge implementations.
- Page evidence is cryptographically bound to the exact PDF; normalized OOXML evidence is bound to the exact Word-saved artifact. This closes two evidence-substitution gaps found during self-review.
- External edits require distinct source, edited, reimported and re-exported artifact identities, with the re-export bound to the current semantic revision and DOCX handed to Word verification.
- Primary Microsoft documentation is cited in the README as mechanism evidence only; no candidate is described as selected or accepted.

## Adjacent Functional Blocker

An additional compatibility command for the old receipt/repository suite failed during **collection**, before tests executed: `ModuleNotFoundError: packages.contracts.workbench_contracts.protected_tokens`. Read-only tracing established that the source-only builder treats any filename containing `token` as sensitive and therefore omitted these medical-writing functional files from the isolated candidate:

- `packages/contracts/workbench_contracts/protected_tokens.py`
- `services/api/app/medical_writing_protected_tokens.py`
- `tests/test_medical_writing_protected_tokens.py`

The legacy files remain present; the package contract file hash is `ac0042ec2cf90dac1b373d949175095e61390dbccfd9485c84ce7e539bd6d0dc`. This is a pre-existing Phase 0 source-closure defect and not caused by Task 0.7. No baseline/policy repair was made here. `P0-CORE` must remain not accepted until a separate functional source-completeness repair restores import closure without touching medical monitoring or reviving the stopped security-test lane.

## Residual Risk

- No Word producer has emitted this receipt yet; `P0-WORD=NO_RELEASE_WORD_BLOCKED` remains correct.
- The exact normalized OOXML algorithm/profile and page-rendering dependency still require Task 0.8 candidate/version/license validation and real Word evidence.
- The source-only candidate cannot currently collect product-level receipt tests due the adjacent missing functional module. Task 0.7 is isolated and green, but Phase 1 product integration must not start until that source closure is repaired.
