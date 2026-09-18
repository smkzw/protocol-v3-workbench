# Conference Participant Output: mw_protocol_v3_2r1_fresh_20260905 - general_single_object_round2

## Boundary Check

- Read-only revalidation; zero source edits. No services, models, network, OCR/translation, live or monitoring paths touched. `main` imported only by the existing readiness test itself under the sanitized env (`env -i`, `.local/bin`-first PATH, venv Python, fresh `WORKBENCH_RUNTIME_DIR`, `-p no:cacheprovider`); no TestClient lifespan/startup, no gate/model calls (all patched in-test).
- New synthetic evidence only as new files (`runs/mw_protocol_v3_2r1_fresh_20260905/r2_atomic_lock_probe.py`, `r2_concurrent_receipt_probe.py`) plus fresh temp SQLite dirs. Round-1 evidence (`true_race_driver.py`, `receipt_zombie_repro.py`, `cas_proof.py`) intact and re-used where still valid.
- Identity unchanged: `pi / opencode-go / muse-spark-1.3-contributor / xhigh`. No task closure, no product/Word acceptance claimed — Codex retains both.

## Revalidation Findings

Verdict per round-1 finding, each against changed code actually read (not worker claims), with concrete evidence. Focused suites re-run by me: **70 passed in 12.7 s** (`test_graph_runtime.py` + `test_graph_runtime_recovery.py` + `test_typed_facade.py` + 5 Codex probes), plus **16 passed** readiness matrix.

### F1 (sequential "concurrent" test) — FIXED

- `test_graph_runtime_recovery.py:371-405` now spawns with genuinely overlapping `Popen` lifetimes (`_spawn_overlapping`: all children created before any join); the child barrier treats rendezvous failure as hard failure (exit 75), never proceed-then-conflict. Only typed `GraphDecisionConflictError` counts as the semantic outcome. New `TestOverlappedAdvanceContention:914-986` asserts single dispatch (`attempt == [1]`, one draft result), typed `graph_reservation_contended_retryable` for any loser, and full convergence to `completed`.
- Verified by reading the harness and by green runs; the old sequential `_spawn` remains only for genuinely sequential setups (kill-before/after setup phases), which is correct use.

### F2 (decision CAS) — FIXED, proven at the relocated seam

- Repair matches Codex Q2 (existing-UoW guard, no new schema): `record_decision` appends via `_append_events_tx` with `_decision_guard` (`runtime.py:531-535, 1545-1566`). Guard runs after a fresh in-transaction stream read, inside the same `BEGIN IMMEDIATE` UoW as the row inserts (`:1497-1529`) — check-then-append is one atomic step; identical identity returns `False` (idempotent reuse, no second event, `:536-538`), conflicting identity raises typed conflict.
- My old `cas_proof.py` hook (outer `_append_events`) no longer targets the decision path — the ported test's comment (`test_graph_runtime.py:990-996`) says exactly this, so the old probe's green result is correctly not claimed as overlap proof.
- New independent proof at the relocated seam — `r2_atomic_lock_probe.py`: parked writer A inside its tx (after guard, between event build and insert); writer B made **zero** progress during a 2 s park (busy_timeout 5 s, so B was blocked on the write lock, not timed out); after release, `outcomes == {A: recorded, B: conflict}`, exactly 1 `graph_decision_recorded`. **PROBE-A PASS.** This is the experiment the ported test approximates; both agree.

### F3 (receipt zombie) — FIXED, per Codex Q1 (genuine payload + verified hash)

- `resolve_unknown_with_receipt` (`runtime.py:606-719`): caller supplies payload + declared hash; runtime recomputes (`:667-674`, mismatch → `graph_receipt_hash_mismatch`, covered by test at `test_graph_runtime.py:777-780`); persists the real `graph_node_result` event with same-schema contract/input provenance + `recovered_receipt` flag (`:687-700`); converges the reservation in place (`:703-713`). Hash-only call returns a `blocked` snapshot with typed `stop_reason: unknown_outcome_requires_payload_bearing_receipt` (`:655-665`) — no zombie, no exception. Hash-only COMPLETED reservations now derive `BLOCKED_UNKNOWN` and explicitly "never certify run completion" (`:961-966`).
- Re-ran my round-1 zombie repro verbatim: before → `completed` + 0 result events + escaping `GraphRunError`; now → `blocked_unknown`, `advance ok: blocked`, all downstream `pending`. `TestTerminalReceiptRecovery:1190-1269` further proves final-node adoption completes the run with a real `final_state` hash, idempotent identical reuse (1 result event), and typed refusal of a different receipt.

### F4 (concurrent start) — PARTIALLY FIXED, one test gap remains (limitation, not defect)

- `_start_guard` (`runtime.py:1579-1603`) implements the symmetric in-tx CAS (no start → proceed; identical identity+roots → reuse `False`; else typed `GraphPlanBindingError`), wired into `start_run` (`:339-342`). Sequential changed-roots test (`:1083-1099`) passes.
- **Gap:** no truly-concurrent start test exists (no Popen/thread overlap for `start_run`; grep confirms the only threading tests target decisions). The guard is line-symmetric to the proven decision guard and shares the same tx mechanism, so I judge the window closed by construction — but the F4 interleaving itself is unexecuted. Recommend one overlapped-start test asserting exactly one start event + typed binding error for the loser.

### F5 (contention error typing) — FIXED per Codex Q3

- Three translation sites, all read: `_execute_node` (`:1062-1076`, `graph_reservation_contended_retryable` / `graph_input_binding_conflict`), `retry_node` (`:797-808`), orphan recovery (`:1140-1145`). The overlapped-advance test (`recovery:955-959`) asserts any loser error equals the typed code — never a raw repository type. Suite green.

### F6 (QC independence) — MEETS OFFLINE PHASE, activation explicitly retained

- `TestQCInvocationIndependence:1272-1380` proves exactly what its docstring claims and no more: QC callable invoked once over exactly declared input schemas, `service_invocation` provenance (owner `quality_control`, writer context, `svcinv:` identity) distinct from writer identity and human actor. The docstring explicitly defers real-model QC activation. Judgment: adequate orchestration-layer evidence for this offline phase; the later activation gate must stay a named obligation and must not be read as satisfied.

### NEW R2-1 (Codex question: concurrent receipt recoveries) — CONFIRMED RESIDUAL RACE, medium-low

- Probe result (`r2_concurrent_receipt_probe.py`, barrier-forced overlap, different payloads): **`n_draft_results: 2`** (`recovered-by-b`, then `recovered-by-a`), loser `A: RepositoryStateTransitionError:` (raw, untranslated), winner `B: ok:completed`, single COMPLETED attempt.
- Mechanism: the receipt path appends via unguarded `_append_events` (no in-tx guard equivalent to F2/F4), so both writers commit conflicting `graph_node_result` events; then the reservation transitions serialize and the loser hits illegal `COMPLETED→COMPLETED` (`sqlite.py:1891`) as a raw storage error. No wedge — run converges last-writer-wins — but lineage duplicates with conflicting content and the loser sees a non-graph error (Q3 gap on this path).
- Minimal repair: in-tx receipt guard (recheck blocked/no-result inside the append tx; identical content → idempotent reuse; different → typed conflict) + translate `RepositoryStateTransitionError` to a graph-typed code on this path. Narrow trigger (two owners recovering the same unknown node simultaneously with different payloads), hence medium-low, but it is the same bug class just closed on the two neighboring paths.

### Codex question (completed-node receipt reuse: declared-hash vs actual content) — REVIEWED SOUND, no finding

- Reuse (`runtime.py:638-644`) compares declared sha to the stored result's sha; the stored sha is hash-verified at write on every current path (receipt: computed==declared enforced at `:667-674`; dispatch: transport computes the sha itself). No legacy hash-only result events can exist (the old code never wrote result events on this path — it only transitioned the reservation, which is exactly the F3 zombie). Sequential different-receipt refusal is tested (`:1259-1269`).

### Small integration delta (`main.py` + readiness test) — REVIEWED, PASS

- Delta (~10 lines at `:3495-3515`): shared omlx workload-gate failure now forces `current_runnable=False` for the three dependent roles (OCR/body/support) with the Chinese reason `本地 OCR/翻译服务状态暂不可用，请稍后重新检查。`, preserving any pre-existing specific reason; remote/non-dependent roles unaffected (gate only applies when `provider == "omlx"` and role is dependent).
- Test (`tests/test_medical_writing_translation_readiness_projection.py`, 4×2×2=16 matrix): **16 passed**. It is sensitive to the delta by inspection (pre-delta, gate-failed+omlx would report runnable and fail lines 55-58). No live calls; TestClient constructed without lifespan.

## Evidence And Assumptions

- Observed: 70 focused passed (12.7 s); 16 readiness passed (2.4 s); PROBE-A PASS transcript; probe-B transcript (`2 results / raw loser error`); zombie repro before/after transcripts; guard/tx/translation code ranges cited above.
- The F4 "closed by construction" and Q(b) "no legacy hash-only results" claims are code-reading inferences (both grounded in cited lines), explicitly marked; F4 wants one executional test.
- Probes B and A use runtime-level hooks in throwaway scripts only; no product source touched; original evidence files unmodified.

## Remaining Risks

1. **R2-1 receipt-race** (duplicate conflicting results + raw loser error) — the one new functional finding; same-class fix as F2/F4, small.
2. **F4 concurrent-start test gap** — construction sound, execution missing.
3. **QC/model activation** must remain a named later gate; nothing in this round satisfies it.
4. Prior minor caveat retained: `flock` liveness assumes local FS; untested on remote FS (out of scope).

## Recommended Next Step

One bounded repair round (in-tx receipt guard + transition-error translation, plus an overlapped-start test), re-run the 70-focused set + readiness 16 + the three evidence drivers (`cas`-class decision probe, zombie repro, receipt-race probe expecting single result + typed loser error), then same-reviewer revalidation. No task closure on this pass; no change to the offline-QC scope note.

**Bounded questions for Codex:**
- Q-R2-1: For conflicting concurrent receipts, is the desired loser signal the existing `graph_node_completed`-family conflict, a new `graph_receipt_contended_retryable` code, or reuse of `graph_reservation_contended_retryable`? (Determines the guard's raise site.)
- Q-R2-2: Should identical concurrent receipts both report success (idempotent reuse, one event), or should the loser also see a contention signal? Current sequential behavior returns success; I recommend keeping success-if-identical.
- Provisional path if unanswered: treat R2-1 as must-fix-before-closure (it re-opens duplicate-lineage, an explicit acceptance criterion), F4-gap as should-fix, everything else as verified.
