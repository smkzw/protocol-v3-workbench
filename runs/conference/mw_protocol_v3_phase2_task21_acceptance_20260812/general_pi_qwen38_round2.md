Removed the file I wrongly wrote to the runner-managed path (`runs/conference/.../general_pi_qwen38.md`); the runner will persist the report. Returning the complete updated participant output inline:

---

# Conference Participant Output: mw_protocol_v3_phase2_task21_acceptance_20260812 - general_pi_qwen38

Round 2 (post-repair re-acceptance), same Pi session as round 1. Read-only; no edits, no security tests, no services; only the initial delta set plus the three case modules for reproducers. Worker/manager/Grok reports not read. Codex remains final authority; this is not acceptance of Task 2.2/P2-G2, security, product integration, UI, or release.

## Boundary Check

- Worked only inside the workspace root `.`. No production paths read or modified.
- Read-only: every counterexample ran from `/tmp` probe scripts against the live tree; no source file edited (my round-1 veto was repaired by the owning worker session, not by me).
- No security tests, no service starts, no live databases/providers/scheduler/LangGraph/MAF.
- Delta set respected: `context/...conference_context.md`, `pocs/protocol_v3/orchestrator/__init__.py`, `fakes.py`, `tests/test_case_contracts.py`, plus the three case modules for reproducers.
- Verifier isolation maintained: no worker, manager, or other-participant outputs were read before or during this verdict.
- Frozen plan re-verified: `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md` SHA-256 `fa99fbd3…d54914` still matches the context pin; Task 2.1 micro-steps (lines 838–861) unchanged.

## Independent Work Product

### Round-1 blockers restated (both independently reproduced in round 1, re-tested now)

1. **Hidden-cycle false negative in construction-time acyclicity** (blocker). The old `_assert_edges_and_acyclicity` Kahn loop decremented in-degree per edge, so a cycle hidden behind parallel DATA/GATE edges between the same node pair over-decremented the shared target and masked `CC_CYCLE`. A cyclic graph could construct, and `topological_order()` returned a partial order.
2. **Direct mutable nested state in fake records** (high). `ArtifactRef(payload=…)` / `DecisionRecord(value=…)` constructed directly with plain dict/list payloads accepted mutable nested state; only the store/board write paths validated deep immutability, so the immutable-record read contract could be bypassed.

### Delta inspection (what changed, and only what needed to)

- `__init__.py` (38.0→39.8KB): validator and read helper now share one `_distinct_dependency_kahn()` core — indegree counts *distinct* upstream nodes; each completed source decrements each distinct target at most once; parallel typed edges share one prerequisite slot. `_assert_edges_and_acyclicity` fails closed with `CC_CYCLE` on any remaining node; `topological_order()` raises `CC_CYCLE` on a partial order instead of returning it. Single source of truth: validator and helper cannot drift.
- `fakes.py` (27.4→29.4KB): `ArtifactRef` and `DecisionRecord` gained `model_validator(mode="after")` deep-immutability checks (`assert_deep_immutable` on payload/value) so direct construction and any validated rebuild fail closed with `CC_INPUT_MUTABLE`. Store/board write paths unchanged (they already validated).
- `tests/test_case_contracts.py` (56.3→65.6KB): four new regressions — `test_minimal_three_node_cycle_behind_parallel_pair_fails_closed`, `test_eligibility_back_edge_to_lock_fails_closed_as_cycle`, `test_topological_order_fails_closed_on_bypassed_cyclic_graph`, `test_direct_fake_record_construction_rejects_mutable_payloads`. Pinned hashes unchanged; case modules untouched (mtimes/sizes identical to round 1) so hashes cannot drift.

### Independent counterexample battery (all re-run fresh this round, python 3.12.13 / pydantic 2.13.4)

| # | Reproducer | Result |
|---|---|---|
| R1 | Round-1 minimal cycle behind parallel DATA+GATE pair (a→b DATA+GATE, b→c, c→b) | `CC_CYCLE` at construction |
| R1b | Same cycle without parallel edges (sanity) | `CC_CYCLE` |
| R2 | 2-cycle made entirely of parallel pairs (a→b DATA+GATE, b→a DATA) | `CC_CYCLE` |
| R3 | Acyclic diamond with parallel pair + independent source | full deterministic order, no over-rejection |
| R4a/c | Direct `ArtifactRef(payload={"x":[1]})`, `DecisionRecord(value=[1,{"y":2}])` | `CC_INPUT_MUTABLE` |
| R4b | `freeze_input` equivalent constructs, read back deep-locked (`append` → `TypeError`) | OK |
| R5 | Real eligibility back-edge `finalize_eligibility_criteria → eligibility_decision_lock` with matching `depends_on` | `CC_CYCLE` |
| R6 | `model_construct`-bypassed cyclic sample-size graph → `topological_order()` | `CC_CYCLE`, never a partial order |
| R7 | Pinned hashes for all three graphs + reversed-tuple construction-order stability | exact match, stable |
| B1 | `graph.model_copy(update={"edges": ("junk",)})` validator bypass | rejected (re-validating copy intact) |
| B2 | Reservation `model_copy` COMPLETED+error_code inconsistent terminal combo | `FK_TERMINAL_FIELDS` |
| B3 | `ArtifactRef.model_copy(update={"payload": {"m":[1]}})` smuggled mutable payload | `CC_INPUT_MUTABLE` (new validator covers the copy path too) |
| B4 | Completed reservation `resume` returns same lineage, no re-execution | OK |
| B5 | `unknown_outcome` resume | `FK_UNKNOWN_OUTCOME` (never auto-redispatched) |
| B6 | Second actor concurrent claim | `FK_CONCURRENT_DECISION` |

### Anchors reproduced

- Focused suite: **75 passed** (was 71; +4 targeted regressions) in 0.26s.
- Functional regression: **1226 passed + 101 subtests** in 12.3s, `tests/protocol_v3` with `PYTHONPATH=.:services/api:packages` (bare run fails collection on imports — environment requirement, not a defect; identical to round 1).
- Pinned material hashes reproduce exactly and are pairwise distinct; cross-process stability covered by the suite's subprocess probe.
- Import-isolation probe passes: no `app`/`services`/`packages`/`langgraph`/provider/`sqlite3`/`pocs.protocol_v3.storage`/`word_receipt` imports.

### Remaining falsification matrix (dispatch list, all still hold)

- Duplicate/unknown node & dependency, duplicate/self/unknown-endpoint edge, duplicate schema/root-input, unknown input/output schema: typed fail-closed codes verified by suite + spot probes.
- Parallel DATA/GATE topological ordering: validator and helper share the Kahn core; parallel pairs count once in `node_dependencies` and ordering; no double-decrement possible.
- `model_copy` validator bypass: still re-validating (B1/B2/B3); new record validators also fire on rebuild.
- Hash instability: no runtime/scheduler state in payload; sorted canonical structure; reversed-construction equality + cross-process pin re-verified.
- Clinical link, duplicate logical effect, mutable nested payload, project/branch confusion, concurrent decision, unknown-outcome resume, old-graph missing link, accidental product/scheduler/provider/storage import: all covered above / by the suite.

## Evidence And Assumptions

Evidence (directly observed this round):
- Shared Kahn core in `__init__.py` (`_distinct_dependency_kahn` called by both `_assert_edges_and_acyclicity` and `topological_order`); partial order raises `CC_CYCLE`.
- Deep-immutability `model_validator(mode="after")` on `ArtifactRef`/`DecisionRecord` in `fakes.py`.
- Four new regression tests present and passing; 75/75 focused, 1226+101 regression.
- Case modules byte-identical in size/mtime to round 1; pinned hashes unchanged and reproduced.
- Frozen plan SHA-256 pin still matches.

Inference:
- Because validator and helper now share one Kahn implementation, future drift between construction-time acyclicity and read-time ordering is structurally prevented — stronger than round 1, where two independent Kahn loops coexisted.
- The repair is minimal and scoped: no contract weakened (B1–B6 confirm previously passing fail-closed behaviors still fire).

Assumptions:
- The pinned hash contract and 71→75 count are authoritative anchors; I reproduced both from current files rather than trusting them.
- `PYTHONPATH=.:services/api:packages` is the intended invocation for `tests/protocol_v3` (matches round-1 behavior and the suite's subprocess probes).

## Risks, Gaps, And Verification Needs

- Injection points remain **declarations, not executed recovery behavior**. The fakes *represent* kill-before/kill-after/duplicate-resume/concurrent-decision/old-graph-migration deterministically; actual kill/restart recovery execution is Task 2.2 scope and is not accepted here.
- The `model_construct` bypass path is now fail-closed at read time, but a deliberately bypassed instance can still exist in memory; acceptable for a PoC contract (read helpers and fakes fail closed), documented by the new test. Not a Task 2.1 blocker.
- No numeric clinical default regressed: suite still asserts `allowed_attempts` is the only number in any graph payload and sample-size assumption schemas stay labeled synthetic; `sample_size.py` (unchanged) encodes no numeric assumption.
- Not verified here (out of scope, Codex-owned): security Task 1.11, services, live providers/scheduler/LangGraph/MAF, product wiring, UI, OCR/translation/Word, medical monitoring, production migration, release, Task 2.2/P2-G2.

## Recommended Next Step

Both round-1 blockers are closed with direct counterexample evidence, the repair introduced no new Task 2.1 regression, both test anchors reproduce, and the injection-vs-execution distinction is preserved. Recommend Codex finalize acceptance of Task 2.1 and proceed to Task 2.2 under the same fail-closed discipline; no further Pi round needed on this tree.

`TASK21_READY`
