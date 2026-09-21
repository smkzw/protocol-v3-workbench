Verification is complete — everything is evidenced. Final report:

---

# Conference Participant Output: mw_r11_v05_evidence_review_20260922 - general_single_object

## Boundary Check

- Same session, continuation round 2. Worked only inside the runner-bound workspace plus `/tmp` (deps at `/tmp/mw_r11_review_deps`, probes at `/tmp/mw_r11_v05_probe/probe_final_reuse_gate.py` and `/tmp/mw_r11_v05_probe/probe_round2.py`). No repo file modified by me; the runner-managed report path untouched; the v0.4 historical artifact opened read-only; no product model invoked; no medical prose judged; no final acceptance claimed — Codex remains final authority.
- State: HEAD is still `58639c7`; the repair under review is the unstaged batch on `services/api/app/medical_writing_full_draft.py` (+79/−31) and `tests/test_medical_writing_full_draft.py` (+54), fingerprinted this round (diff sha256 prefix `6131e9f016d373b5`, 9 implementation hunks + 2 test hunks, all inspected). The `e2e_runtime/*` working-tree changes are runner-owned runtime state, unrelated to the repair.

## Independent Work Product

**Verdict: PASS for this engineering scope.** M1 and L1 are closed exactly as specified, with no adoption, recovery, legacy-read, or cross-chunk regression found. One Low-severity residual edge (L3 below) is reported with evidence and a one-line remedy; it does not reopen the adoption-safety concern. The real v0.5 product run and the fresh medical review remain explicitly pending and are not covered by this PASS.

### M1 closure — verified closed

- The early final-reuse gate now requires `_artifact_evidence_is_resolvable(existing_final)` (`medical_writing_full_draft.py:834`), sharing one implementation with the chunk-reuse gate (`:744-765` region), the merge gate (`:986`), and the adopt gate (`:1157`) — no divergent copies.
- Probe A (current tree): final with one section's `evidence_bindings` emptied → rerun takes the regeneration path (message “全文初稿已生成 2/2 个章节候选”， not the old “已复用已持久化”)， model **not** re-invoked (both valid chunks reused), rebuilt final has restored bindings and a resolvable chain. This matches the dedicated regression test `test_damaged_final_is_rebuilt_from_valid_chunks_instead_of_reused` (`tests/test_medical_writing_full_draft.py:701`), which additionally asserts `runner.calls == 1` and chain resolvability after rebuild.
- Probe D: a subtler tamper (binding locator swapped, quote/hash intact) is also rejected at the gate and rebuilt — the batch's new locator-equality check is live at the gate, not just at adopt.
- Read-time honesty: `_apply_review_policy` now computes `coverage["evidence_chain_resolvable"]` and folds it into `adoption_ready` (`:635-641`). Probe B: a completed store row whose final was damaged after completion reads with `evidence_chain_resolvable=false`, `adoption_ready=false`, and `adopt` rejects “全文初稿章节证据链不完整，未采纳” — the review-facing flag no longer lies about a damaged candidate, and the last-line adoption gate holds.

### L1 closure — verified closed

- The binding call is wrapped: `except RuntimeStoreError as exc: return DurableJobResult(error=str(exc), retryable=False)` (`:933-934`), before any chunk bytes are written, matching the sibling non-retryable classification. `_evidence_bindings_for_section` raises exactly `RuntimeStoreError`, so the catch is sufficient; the remaining loop body cannot raise for well-typed provider output (`quote` passes through `_text`, so `.encode` is safe).

### Regression sweep — none found

- **Adoption:** all adopt-path tests pass (legacy rejection, marker rejection, idempotent adopt); probe B confirms the chain gate still rejects at adopt.
- **Recovery:** undamaged-final reuse is preserved (the `adoption_ready`-relevant gate condition is additive; reuse-idempotency test passes; probe C incidentally shows the reuse path still fires when the gate passes).
- **Legacy read:** `not is_legacy and cls._artifact_evidence_is_resolvable(artifact)` short-circuits (`:636`), so v3/v4 artifacts never touch the stricter check; both legacy tests pass (`tests/test_medical_writing_full_draft.py:624`, `:649`); adopt rejects legacy at the schema check (`:1150-1152` region) before the chain gate.
- **Cross-chunk:** the new `test_duplicate_span_ids_in_different_chunks_keep_section_scoped_bindings` (`tests/test_medical_writing_full_draft.py:723`) documents the core invariant — the same span ID in two single-section chunks with distinct `ai_run_id`s persists section-scoped bindings and a resolvable artifact. The stricter per-section `source_ids` membership does not reject legitimate reused chunks: frozen-v5 chunk sections carry `source_ids`, and all reuse/merge/idempotency tests pass.
- **Independent reproduction:** `py_compile` clean; 117 tests pass (26 + 53 + 38) under my own run, matching the owner's report.

### Remaining finding

- **L3 (Low, evidence-backed, non-blocking): vacuous truth on zero-section payloads.** `_artifact_evidence_is_resolvable` ends with `return isinstance(sections, list) and all(...)` (`medical_writing_full_draft.py:588`); `all([])` is True, so a final artifact with `sections: []` and intact `coverage.section_ids` passes the early gate. Probe C: such a file is re-sealed as the completed candidate (“已复用已持久化全文初稿 2/2 个章节候选”， persisted section count 0), and read reports `adoption_ready=true` on a zero-section artifact — misleading for any UI badge. Existing mitigations: the merge path cannot produce this shape (its `actual_ids != expected_ids` check at `:983-985` runs first), `generated_count: 0` is a visible anomaly, and adopt rejects via the coverage-set mismatch (“全文初稿候选覆盖与目标章节不一致”)， so no prose can be written. This is the same damage class M1 targeted, in a narrower shape. **Remedy (one line):** require non-empty sections at `:588` — `return isinstance(sections, list) and bool(sections) and all(...)`; safe for all three call sites since the merge gate passes a non-empty list and genuine finals are non-empty. Add or extend the damaged-final test with the empty-sections shape if adopted.

### Carried observations (unchanged, non-blocking)

- `resolve_decision` checks schema version but not the chain — acceptable: decisions write upstream StudyDefinition facts, never prose, and the revision change supersedes the artifact.
- For legacy artifacts `evidence_chain_resolvable=false` conflates "no chain (legacy)" with "broken chain"; `legacy_read_only` already distinguishes them.

## Evidence And Assumptions

- Repair diff: unstaged working-tree changes vs `58639c7` (sha256 prefix `6131e9f016d373b5`); key lines `medical_writing_full_draft.py:575-592, 635-641, 744-765, 834, 933-934, 986-988, 1157`; `tests/test_medical_writing_full_draft.py:701-744`.
- Checks I ran this round: `py_compile` clean; 117 tests (26 + 53 + 38) pass; probe results A–D quoted above (script `/tmp/mw_r11_v05_probe/probe_round2.py`, rerunnable).
- Evidence base carried from rounds 0–1 (unchanged): frozen-commit line numbers, v0.4 artifact shape (`protocol_full_draft_artifact_v4`, 85 sections, no `evidence_bindings`, 15 cross-run span IDs), gateway/runner generation-time gates (`ai_gateway.py:2016-2026`, `ai_task_runner.py:2732-2774, 882-944`).
- Assumptions: the fake-runner fixture mirrors the real submission contract for gate isolation (as in the unit tests); the probe bypasses gateway validation deliberately to reach the gate logic. The unstaged diff is the owner's work — I inspected and tested it but neither accept nor commit it.

## Risks, Gaps, And Verification Needs

- L3 is the only remaining engineering-scope finding; it is Low, requires a contrived damage shape, and is blocked at adopt by an independent gate. Whether to spend the one-line fix before the freeze is Codex's call; my recommendation is to include it since this batch exists precisely to close this damage class.
- The repair batch is uncommitted; until Codex commits and freezes it, the next review checkpoint lacks a stable hash.
- Explicitly still pending and out of scope for this PASS: the real v0.5 Study A generation in the isolated environment, programmatic verification of all 85 sections' bindings on that actual artifact (now under the stricter locator rules), and the fresh medical conference before any adoption.

## Recommended Next Step

Optionally fold the L3 one-liner (`medical_writing_full_draft.py:588`, require non-empty `sections`) plus its test extension into this batch, then commit the whole batch as the plan's step-4 repair with a new freeze hash and record the 117-test + py_compile rerun in the stage record. After that freeze, proceed exactly as planned: isolated v0.5 Study A generation on the committed code, programmatic chain verification of the real artifact, and the fresh medical conference — with adoption still forbidden until that conference passes.
