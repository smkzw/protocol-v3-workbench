# Codex Review: mw_protocol_v3_phase1_task11_20260810

Date: 2026-08-10
Independent review: `runs/codex_mw_protocol_v3_phase1_task11_independent_luna.md`
Reviewer session: `019fe9aa-804d-7b50-b9de-6186e418d9f6`

## Verdict

`READY` — Task 1.1 accepted after closing the reviewer's single P1.

## Boundary Check

- Product changes are confined to the isolated Protocol v3 contract module, package export, five exact immutable medical-writing functional assets, source-closure policy, and test fixtures/tests.
- Task records are confined to this task's `context/`, `prompts/`, `runs/`, `reviews/`, and `metrics/` surfaces.
- No medical-monitoring path is changed. No service, browser, model runtime, OCR or translation workload was started.
- No security, adversarial, permission, path, symlink, TOCTOU, malicious-input, destructive-state or penetration test was run.

## Codex Verification

- `python3 -m pytest tests/protocol_v3/test_contract_models.py -q` — 16 passed.
- `python3 -m pytest tests/test_medical_writing_study_schema.py tests/test_medical_writing_document_session.py -q` — 42 passed; 17 pre-existing deprecation warnings.
- Four focused positive source-baseline tests passed, including exact functional asset inclusion and manifest closure.
- The five restored assets match the former workbench byte-for-byte; company corpus count is 3,878 and glossary count is 108; both manifests agree with their payloads.
- `git diff --check` and Python compilation checks passed.
- Independent seven-case `SourceArtifact` identity matrix passed: original without parent identity accepted; original partial/complete parent identity rejected; derived partial identity rejected; derived complete identity accepted.

## Delegated-Agent Output Review

- The independent reviewer first returned `NOT_READY` for a real P1: XOR parent identity was not rejected for original artifacts.
- The validator and regression test were corrected, then the same reviewer session was resumed. It returned `READY` and confirmed no same-cause regression.
- Native Luna capability was explicitly probed and rejected by the App backend; the mandated CLI compatibility route was used without substituting Sol/Terra or routing through Hermes.
- The review is contract-level acceptance only. It does not claim repository, workflow runtime, frontend, Word round-trip or release readiness.

## Residual Risk

- Pydantic deprecation warnings in the legacy suites remain outside this task's scope.
- A pre-existing duplicate `MedicalWritingStudyFactEvidence` export was observed but not changed because it is unrelated to Protocol v3 Task 1.1.
- Phase 1.2 and later application/runtime behavior remain unimplemented and unverified.
