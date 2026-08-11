# Execution Output: mw_protocol_v3_phase2_task21_20260812 - worker_01 (repair4, same-session)

## Boundary And Context Check

- Role: first-line executor `worker_01`; effective route `opencode-go/deepseek-v4-flash` authoritative per session override; no route/provider change attempted.
- Repair4 constraints honored: initial read set limited to `AGENTS.md`, Task 2.1 execution context/plan, `pocs/protocol_v3/orchestrator/__init__.py`, `pocs/protocol_v3/orchestrator/fakes.py`, and the three case modules read-only. Exact write ownership respected: **only `__init__.py` and `fakes.py` modified**. Case modules, `tests/test_case_contracts.py` (read-only, including its pinned-hash contract), product source, medical-monitoring, services, databases, and security files untouched. No packages installed; no service started.
- Fresh verifier Qwen's three defects (per-edge decrement hiding cycles in validation; `topological_order` partial output; direct mutable `ArtifactRef`/`DecisionRecord` construction) were each reproduced conceptually against current code, fixed at the source, and proven by counterexample — including old-algorithm-vs-new-algorithm hiding evidence.

## Work Performed

1. **Defect 1 — validator Kahn over-decrement masked real cycles** (`__init__.py`): extracted a shared private deterministic core `CaseGraph._distinct_dependency_kahn()` that counts indegree by distinct upstream nodes and decrements each distinct target at most once per completed source (precomputed `successors` sets); edges with undeclared endpoints are ignored by the read helper (construction still rejects them with `CC_EDGE_UNKNOWN_NODE`). Both `_assert_edges_and_acyclicity()` and `topological_order()` now call this single core, so they cannot drift again. `CC_CYCLE` code and message format (sorted remaining node ids) unchanged.
2. **Defect 2 — `topological_order()` fail-closed on malformed/bypassed instances** (`__init__.py`): the helper now raises `CaseContractError("CC_CYCLE", …)` whenever the core reports remaining (unordered) nodes; it never returns a partial order.
3. **Defect 3 — direct mutable `ArtifactRef`/`DecisionRecord` construction** (`fakes.py`): added `model_validator(mode="after")` guards (`_validate_payload_deep_immutable`, `_validate_value_deep_immutable`) calling the established `assert_deep_immutable` on non-`None` payload/value → `CC_INPUT_MUTABLE`. Caller input is not silently frozen; callers use `freeze_input` explicitly; store/board happy paths preserved (they pre-validate before constructing).

## Artifacts And Evidence

Changed files (only worker-01-owned):
- `pocs/protocol_v3/orchestrator/__init__.py` — `_distinct_dependency_kahn()` shared core; validation and `topological_order` rewired to it; `topological_order` fails closed with `CC_CYCLE`.
- `pocs/protocol_v3/orchestrator/fakes.py` — deep-immutability model validators on `ArtifactRef` and `DecisionRecord`.

Evidence (all observed this session):
- Compile: `python3 -m py_compile` (3.9.6) and `/opt/homebrew/bin/python3.12 -m py_compile` (3.12.13) on both files → PASS.
- Counterexamples (all fail closed):
  - Real eligibility graph + back-edge `finalize_eligibility_criteria → eligibility_decision_lock` (DATA+GATE parallel pair, lock `depends_on` extended with finalize, existing `lock → finalize` DECISION edge kept) → `CC_CYCLE`; the old per-edge algorithm returns a full order over the same graph (`old_rem == []`), proving the cycle was hidden before.
  - Minimal three-node parallel-edge hidden cycle (A→B DATA+GATE, B→C, C→B) → `CC_CYCLE` at construction; old algorithm again hides it (`old_rem == []`).
  - `CaseGraph.model_construct`-bypassed cyclic instance: `topological_order()` → `CC_CYCLE` (no partial output); `material_sha256()` still computes.
  - `ArtifactRef(payload={"x":[1]})`, `ArtifactRef(payload=[1,{"y":2}])`, `DecisionRecord(value={"x":[1]})` → `CC_INPUT_MUTABLE`; `freeze_input`-equivalents pass and remain deep-locked (`payload["x"].append` / `value["x"].append` → `TypeError`).
- Positives/regressions (all pass): acyclic parallel-edge graph constructs and orders `('a_node','c_node','b_node')` with edge order and distinct deps; all three real graphs — complete order, every edge source strictly before target, `node_dependencies()` == `tuple(sorted(depends_on))`; sample-size `statistical_review` before `sample_size_decision_lock`; hash stability across shuffled rebuild; prior fixes green (`CC_NODE_UNKNOWN` store+reserve, `CC_SCHEMA_MISMATCH`, `CC_BINDING_MISMATCH`, reserve idempotency, bad hash / empty error code rejection, `FK_TERMINAL_FIELDS` terminal combo, `CC_INPUT_MUTABLE` on plain containers, `FakeContractError` in the `CaseContractError` family, validated `model_copy` rejecting `edges=("junk",)`).
- **Hash impact: none.** All three graph hashes match the worker-03 pinned `EXPECTED_HASHES` byte-for-byte — eligibility `f9d99776159d…f484b`, objective_estimand_endpoint `42c3ed3523c8…26d0`, sample_size `77870c7aabf0…5ef4` (the Kahn refactor and fake-model validators are not part of `material_payload`).

## Commands And Observations

- Two compile commands (one per interpreter) → both OK.
- In-kernel verification suite (no files written): three cells total. First cell ran all counterexamples plus store/board probes and completed the full result matrix; one probe (store/board happy path) initially used a mismatched project/branch (`proj_obesity_p3/branch_main` vs the case modules' shared `mw-protocol-v3-poc/orchestrator-poc-v1`) and was corrected in-cell to `FakeRuntime(elig_mod.PROJECT_ID, elig_mod.BRANCH_ID)` — the mismatch itself was correctly rejected with `CC_BINDING_MISMATCH`; no product defect. A second cell had two harness typos (stray subscript line, `g_probe`/`FakeContractError` not defined across cell boundaries) — corrected and rerun; all assertions then passed.

## Blockers Or Missing Environment

None. Both runtimes available; pure import/compile/inline checks were sufficient per worker-01 boundary. The integrated `tests/test_case_contracts.py` (worker-03-owned) was read-only (pinned hashes extracted as the invariant reference) but not executed by this worker — that remains with Codex/fresh verifier acceptance.

## Rerun Requests Or Next Step

- No rerun requested; deliverable complete with acceptance evidence above.
- Next step for Codex/fresh verifier: run `pocs/protocol_v3/orchestrator/tests/test_case_contracts.py` in full — the pinned-hash assertions (`test_hashes_match_pinned_contract_and_are_pairwise_distinct`) should pass unchanged since all three graph hashes are byte-identical to the pinned constants, and the new `CC_CYCLE`/`CC_INPUT_MUTABLE` semantics are additive fail-closed behavior. No further worker-01 code changes are pending; residual ownership (case files, integrated tests, acceptance) stays with the assigned workers/Codex.
