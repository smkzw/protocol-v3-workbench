# 2R.1 Codex functional review — pre-repair

Status: NOT accepted; ongoing independent review50163. Frozen worker output
audited successfully, but implementation correctness remains below criteria.
No user decision needed; continue bounded repair after review synthesis.

## Confirmed counterexamples

All four run against actual product SQLite in pytest temporary directories.
Evidence: runs/mw_protocol_v3_2r1_typed_facade_20260905/test_codex_concurrency_probe.py
and codex_four_probes_red.xml (4failed,0.46s). No live/model operations.

1. **Conflicting confirmations both commit.** runtime.py record_decision reads
   existing decision outside the append transaction; _append_events obtains a
   fresh head later. A deterministic interleaving after both prechecks writes two
   graph_decision_recorded events; both callers report recorded. Make the semantic
   check and append atomic, or bind a genuine expected-head CAS and reconcile the
   loser as typed conflict/idempotent reuse. A process-local lock is insufficient.
2. **Concurrency evidence is sequential.** test_graph_runtime_recovery.py475ff
   calls blocking _spawn in a list comprehension; facade test655ff does the same
   in a loop. Each rendezvous times out and proceeds; broad Exception is counted
   as conflict. Launch both children before waiting, require rendezvous success,
   and assert exact semantic outcome/error, not any exception. Preserve old
   evidence as historical, never call these original tests true races.
3. **Changed root facts silently discarded.** start_run reuses by graph identity
   before checking new root inputs. A same run with different synthetic population
   and phase returns successfully with old state. Compare exact canonical root
   identities and reject a conflicting restart with a useful typed error.
4. **Decision hash does not identify downstream payload.** _decision_result_payload
   stores value-only SHA but wraps value with decision/actor/reason in output.
   The actual output hash differs. Hash the exact persisted/consumed object;
   keep a separate value hash if needed for decision deduplication.
5. **Last-result crash never converges to completed.** When the last durable node
   result exists but graph_run_completed was not appended, advance skips all
   nodes and never calls _finish_run_if_complete. Reopen stays running; the
   run_to_completion loop would keep calling advance. Bounded one-advance test
   proves the defect without hanging. Repair missing completion from results
   without re-executing a node and add actual process-death coverage.

## Remaining review questions, not yet claimed reproduced defects

- Receipt-only completion lacks payload adoption; inspect terminal-node behavior
  and ensure users can actually recover usable output, not just a hash/status.
- Dedicated crash test between result event and reservation completion is absent.
- Human actor_id vs writer_context is not Agent4 fresh-context independence.
  Inspect the accepted QC requirements and keep real-model activation deferred.
- Confirm outcome payloads satisfy typed schema obligations rather than merely
  carrying schema-name strings; synthetic labels are not clinical validation.
- Runtime1328lines plus plan364/ports97/state154 suggests reviewing whether the
  adapter remains a minimal reusable layer; line count alone is not a defect.

## Regression/environment disposition

- Initial Codex run with bundled Node:1645pass4fail67.06s; exact binary hash differs
  from existing manifest. This is test environment selection, not product failure.
- Existing /Users/smkzw/.local/bin/node v22.22.3:wrapper17pass4.18s;
  full tests/protocol_v3 + accepted/new PoC tests1649pass66.64s. XML
  codex_frontend_existing_node.xml / codex_full_existing_node.xml retained.
- These1649 passing tests exclude the four independent failing probes. No claim
  of full acceptance or all-repository green. No manifest/expected bypass.
- Worker actual ZCode/GLM-5.3-Flash:max,4219.794s, no fallback, session
  sess_1f8c1857-227c-49f3-b42f-d821a216eac6. audit-execution PASS is provenance,
  not functional acceptance. Same-session repair remains available after review.

## Independent review synthesis

MuseSpark1.3:xhigh fresh review completed413.823s, original report retained at
runs/conference/mw_protocol_v3_2r1_fresh_20260905/general_single_object.md.
Independently reproduced duplicate decisions and receipt-without-content wedge;
identified concurrent-start race statically, convergence error typing and QC
evidence limits. Its13 unforced overlapping runs serialized successfully, which
does not invalidate the deterministic interleaving counterexample.

Calibration: reviewer F3's terminal-node empty-hash certification statement is
not dynamically demonstrated. A nonempty recovered hash may exist, while Codex
actually reproduced a missing completion event remainingRUNNING. Treat potential
hash-only certification as a predicate/coverage concern, not an observed empty
hash export. Do not weaken the confirmed downstream missing-content finding.

Codex decisions: payload-bearing receipt recovery; atomic checks inside existing
UoW rather than new schema; graph-typed contention; independent offline QC
invocation/context evidence without claiming actual-model independence. Same
worker repair83826 is running, no acceptance yet. No user question required.
