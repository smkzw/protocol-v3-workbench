# Codex Review: mw_protocol_v3_phase0_task06_20260810

Date: 2026-08-10 09:10 CST
Delegated-agent output: `runs/codex_mw_protocol_v3_phase0_task06_20260810.md`

## Verdict

PASS for Task 0.6 permanent functional failure corpus. This is not a release or runtime acceptance claim.

## Boundary Check

- Codex executed the direct route; no delegated or conference role was started.
- Hermes was not used because the guard selected the Codex-direct route for this bounded task.
- Product writes are limited to the Task 0.6 builder, eight fixture files, manifest and focused test. Tracking writes are limited to this task's context/prompt/review/metrics.
- The legacy workbench, D017 DOCX, r17 durable reports and approved design were read-only. No service, browser, Word, network, OCR, translation or project runtime was started.
- Medical-monitoring files were not read as implementation inputs and were not modified.
- In accordance with the user's latest correction, no security/path/permission/symlink/TOCTOU/destructive-state test was run or dispatched.

## Codex Verification

- `python3 -m pytest tests/protocol_v3/test_failure_corpus.py -q` -> `19 passed`.
- `python3 scripts/qc/protocol_v3/build_failure_corpus.py --check --output tests/fixtures/protocol_v3/failure_corpus` -> 8 fixtures, manifest identity `mw_protocol_v3_permanent_failure_corpus_v1`, cross-layer identity SHA-256 `00715cbc8e8cb02f2a32d81511db68b1d643f6b0ac5a93b34ea5474348b193e1`.
- Python compile and `git diff --check` passed.
- Two independent temp rebuilds produced byte-identical manifest and fixtures.
- Checked-in tests prove missing/extra fixture, expected-gate drift, skip/xfail downgrade, fixture hash drift and manifest drift are blocking.
- Positive control is shorter than the 44-character negative fixture but has target claim, locator, surrounding context, source role and StudyDefinition binding; this prevents length from becoming the acceptance proxy.
- Read-only D017 inspection identified the exact audited artifact and hash; only controlled counts/headings were copied into the fixture, not the historical directory or document body.

## Direct Work Review

- r17 fixtures say `provenance=evidence_reconstructed`, `original_runtime_available=false` and explicitly disclaim verbatim recovery.
- Runtime consistency failures are assigned to the Phase 1 hard gate `P1-G1`, not the Phase 8 release gate `R1`.
- Failure identity, code, gate, owner, source locator, reason and file hash are all pinned in the manifest.
- No application code consumes these fixtures yet; Phase 1/4/6 integration tests remain later tasks named in the approved plan.

## Residual Risk

- The reconstructed 44-character text is a controlled minimal representative, not the deleted original row. That limitation is explicit and intentional.
- The focused corpus suite is verified. The broader `tests/protocol_v3` set was not rerun because it contains the security/adversarial lane the user ordered stopped; this slice adds no application imports or runtime mutation path.
- Later gate implementations must import this manifest rather than duplicate its identities; that wiring belongs to Tasks 1.x, 4.x and 6.x.
