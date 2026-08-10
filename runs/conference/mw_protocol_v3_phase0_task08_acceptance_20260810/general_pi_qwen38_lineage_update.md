...

All five confirmation points are verified. Let me compile the final report.

---

# Conference Participant Output: mw_protocol_v3_phase0_task08_acceptance_20260810 — general_pi_qwen38 (Lineage Update)

## Boundary Check

Read-only functional review. No file modified, no Word/service/browser invoked, no other participant's report or medical-monitoring file inspected, no security/adversarial/path/symlink/TOCTOU/destructive test run or recommended. Effective route `cms-smk/cms-model` treated as authoritative.

## Sources Read

- `AGENTS.md`
- `pocs/protocol_v3/word_receipt/contract.py`
- `pocs/protocol_v3/word_receipt/producers/base.py`
- `pocs/protocol_v3/word_receipt/producers/applescript_bridge.py` (full, including delta lines 130-147, 426-545, 548-805)
- `pocs/protocol_v3/word_receipt/roundtrip_lineage.py` (full, including delta lines 110-140)
- `pocs/protocol_v3/word_receipt/decision.md` (updated; lines 38-125)
- `pocs/protocol_v3/word_receipt/results/CMS-UC-301-wording-roundtrip/` (staging)
- `pocs/protocol_v3/word_receipt/results/CMS-UC-301-wording-roundtrip-current-908726e34525/` (current final)
- `pocs/protocol_v3/word_receipt/tests/` (test suite)

## Checks Run

1. `python3 -m pytest pocs/protocol_v3/word_receipt/tests -q` → **67 passed** (0.25s).
2. `producer_identity()` recompute against declared SHA.
3. `validate_receipt()` on current receipt + disk-hash cross-check (input/saved/PDF/page-images/OOXML fingerprint).
4. Idempotency key + receipt_id recompute from receipt identity.
5. Staging replay: all four staged DOCX files hashed against lineage manifest + semantic revision.
6. Reservation/candidate/final lineage binding equality across the three event tiers.
7. Historical receipt retention (old r2 + r1 still validate, diverged producer SHA).

## Exact Observations

### Delta identification (what Codex changed)

Three changes to the producer/lineage provenance checks:

1. **`producer_identity()` now binds `roundtrip_lineage.py`** (`applescript_bridge.py:136` — `root / "roundtrip_lineage.py"` added to the hashed file list). This changed the implementation SHA from `f7d9d8b1…` (old r2) / `1fd1fb09…` (r1) to the frozen `9e214a16…`.
2. **Lineage bound at reservation time** (`applescript_bridge.py:626` — `001-reserved.json` now writes `edit_reimport_export_lineage`). Every replay path checks it:
   - `_reconcile_completed_word_invocation` line 524: `reserved.get("edit_reimport_export_lineage") != dict(expected_lineage)` → `WR_LINEAGE_STALE`.
   - Candidate replay line 577: candidate lineage != expected → `WR_LINEAGE_STALE`.
   - Final receipt replay line 570: final receipt lineage != expected → `WR_LINEAGE_STALE`.
3. **`stage_reimport` replay now validates all four staged files** (`roundtrip_lineage.py:112-140`): source/edited/reimported/reexported hashes all checked, plus semantic revision; hash-match-but-revision-mismatch gets a distinct `WR_LINEAGE_STALE` (line 134), while artifact-mismatch stays `WR_UNKNOWN_OUTCOME` (line 138).

### Confirmation point results

| # | Claim | Result |
|---|---|---|
| 1 | Producer SHA = `9e214a167b7f0bf67e417e0c75e4b71b8a6c9b98cf5b5e3b5f81aba7f90fc12b` | **Confirmed.** `producer_identity()` recomputes to exact value. |
| 2 | Current receipt `mwwr_v1_75c4311dfc1ac8c0af0d908726e34525` validates, binds `d9309158…` input / `4fdc8442…` saved / `0738d7ec…` PDF / 27 pages / lineage | **Confirmed.** `validate_receipt()` PASS. Disk hashes: input `d9309158…`, saved `4fdc8442ce87…`, PDF `0738d7ec323e…` — all match. 27 page images present + hash-verified. OOXML fingerprint `76327ed8…` recomputes from disk, matches decision.md. Lineage `edit_reimport_export`, 4 distinct artifact IDs, reexport binds input, merged_rev `semantic-document-cms-uc-301-wording-r2`. Idempotency key + receipt_id recompute match. |
| 3 | Staging replay validates all four staged files + semantic revision; reservation/candidate/final replay reject stale lineage with typed failure, no Word repeat | **Confirmed.** Staging: all four DOCX (source-export/external-word-edit/reimported/reexport) hashes match lineage manifest; `stage_reimport` replay path checks all four + revision (line 112-122), with `WR_LINEAGE_STALE` for revision mismatch (line 134). Reservation binds lineage at write-time; all three replay tiers check `expected_lineage` equality with `WR_LINEAGE_STALE`. Current run is a fresh Word run (events 001-004, no postprocess-resumed). |
| 4 | 67 focused tests pass | **Confirmed.** 67 passed in 0.25s. |
| 5 | Earlier `f7d9d8b1…` receipt retained only as immutable historical evidence | **Confirmed.** `f7d9d8b1…` is the old r2 producer implementation SHA (`CMS-UC-301-wording-roundtrip-r2-18dc202605c6`, receipt `mwwr_v1_234418ce…`). It still passes `validate_receipt()` (valid historical artifact), but its producer SHA (`f7d9d8b1…`) differs from the frozen current (`9e214a16…`), so it cannot replay under the current identity. r1 (`1fd1fb09…`) likewise retained as historical. All three receipts have distinct receipt_ids and distinct producer SHAs; nothing overwritten. |

### Additional verified facts

- **Lineage chain integrity**: current receipt's lineage `source_artifact_id` (`word-saved-bdf8b98224038fd66d02`) == staging manifest `source_artifact_id` == r1's saved artifact ID. Staging `reexport.docx` hash == current receipt's `input_docx_sha256` (`d9309158…`). The lineage binds r1's Word export → external edit → reimport → re-export → current Word re-verification.
- **Source preservation**: r1 saved DOCX (`bdf8b982…`) unchanged; current run used distinct input/saved/PDF hashes. No artifact overwritten.
- **User document isolation**: current run's `word_inventory_before.documents == word_inventory_after.documents` (3 user docs, name+path+saved identical).

## Failed Paths

None. All five confirmation points pass. No test failures, no validation failures, no hash mismatches.

## Uncertainty

- **[INFERENCE]** The lineage-stale rejection paths (`WR_LINEAGE_STALE` in reservation/candidate/final replay, and in `stage_reimport`) are verified by code inspection + the fact that the current run binds lineage at all tiers. I did not construct a synthetic stale-lineage scenario to trigger the rejection at runtime (that would require writing files, which is out of read-only scope). The test suite's `test_completed_word_invocation_resumes_postprocessing_without_replay` verifies the stale-producer-identity rejection (`WR_UNKNOWN_OUTCOME`); the new `WR_LINEAGE_STALE` path follows the same pattern with lineage as the checked field. The logic is sound: `reserved.get("edit_reimport_export_lineage") != dict(expected_lineage)` at line 524 will reject any lineage that doesn't exactly match the current request's computed lineage.
- **Word-native vs OOXML field count** (126 vs 59): unchanged from my earlier report. decision.md lines 86-89 now explicitly documents this as an intentional methodology difference (Word counts update operations per story/section; OOXML counts unique complex/simple fields). Not a defect; correctly bounded.

## Recommended Next Step

**Verdict: READY.**

The lineage/replay provenance enhancement is sound and complete. The producer implementation SHA is frozen at `9e214a16…`, the current receipt validates with exact artifact/page/lineage binding, all replay tiers reject stale lineage with typed failure without repeating Word, staging validates all four files plus semantic revision, 67 tests pass, and the earlier `f7d9d8b1…` receipt is correctly retained as immutable historical evidence that cannot replay under the current identity.

Codex owns final disposition and the already-completed 27-page visual judgment. The Phase 6-7 / text-frame / annotation / revision corpus-expansion residuals remain correctly bounded and do not affect this P0-WORD technical producer acceptance.
