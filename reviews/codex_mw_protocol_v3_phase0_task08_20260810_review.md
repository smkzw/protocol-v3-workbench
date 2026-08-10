# Codex Review: mw_protocol_v3_phase0_task08_20260810

Date: 2026-08-10
Delegated-agent output: `runs/codex_mw_protocol_v3_phase0_task08_20260810.md`

## Verdict

`PASS_WITH_RESIDUALS` — Task 0.8 satisfies the frozen P0-WORD technical producer contract.

## Boundary Check

- Writes stayed inside the Word-receipt PoC, task tracking/conference records and ignored result
  tree. No product/API/frontend or medical-monitoring file changed.
- Word actions used task-owned copies only. The three pre-existing user documents returned with
  identical name/path/saved-state inventory.
- No security, adversarial, permission, path, symlink, TOCTOU, malicious-input or destructive-state
  test was run.

## Codex Verification

- `python3 -m pytest pocs/protocol_v3/word_receipt/tests -q`: 67 passed.
- Current and initial finalized CMS receipts pass `validate_receipt`; exact input/saved/PDF hashes
  match disk. The prior r2 receipt remains immutable historical evidence.
- Current roundtrip: 126→126 Word field-update operations, zero errors, TOC 1, 27 pages, 9 stable
  bookmark checks (including 5 business bookmarks) and 32 resolved PAGEREFs.
- Codex viewed every current-roundtrip page through four contact sheets; mixed orientation and
  layout passed.
- TP-MA-07 remained candidate-only because page 2 footer is clipped; D017 remained blocked by
  missing stable business bookmark evidence.
- TP-MA-07, D017 and CMS original hashes remain `a28e95d7…`, `bae34f09…`, `cd5d483a…`.

## Delegated-Agent Output Review

- Pi/cms-model independently returned `READY` after rerunning 67 tests and revalidating hashes,
  page manifests, receipts and OOXML fingerprint.
- After the producer identity changed, the same Pi session returned a second targeted `READY` for
  implementation `9e214a16…` and receipt `mwwr_v1_75c4311dfc1ac8c0af0d908726e34525`;
  no fallback or new session was used.
- Grok Build's first two outputs were cancelled/incomplete; the same session completed on the final
  allowed recovery pass and returned `READY_WITH_RESIDUALS`. It correctly challenged lineage hash
  wording and producer implementation drift. Codex resolved both in `decision.md`.
- No participant output was treated as final authority; Codex retained visual and gate disposition.

## Residual Risk

- The accepted bridge is macOS/Word 16.111.3 and representative-corpus bound.
- Word native field operation count (126) and unique OOXML field count (59) have different semantics
  and are now documented.
- Current producer implementation pin is `9e214a16…`; the earlier `f7d9d8b1…` and `1fd1fb09…`
  receipts remain immutable history.
- Staging, reservation, candidate and final replay now reject mismatched artifact hashes,
  semantic revision or lineage using typed failure instead of reusing stale evidence.
- This does not accept Protocol content, A+C UI, product wiring, Phase 6–8 or final release.
