# Execution Output: mw_protocol_v3_phase2_task21_20260812 - worker_01 (repair2, same-session)

## Boundary And Context Check

- Role: first-line executor `worker_01`; effective route `opencode-go/deepseek-v4-flash` authoritative per session override; no provider/model change attempted.
- Repair2 constraints honored: initial read set limited to `AGENTS.md`, execution context, execution plan, and the three owned files; only `pocs/protocol_v3/orchestrator/__init__.py` and `pocs/protocol_v3/orchestrator/fakes.py` modified (both worker-01-owned). `cases/__init__.py` had no defect and was left untouched. No Worker 02/03 case files, tests, product source, medical-monitoring, services, databases, or security files touched. No packages installed; only stdlib + already-pinned Pydantic.
- Codex's three Worker-02-acceptance defects (model_copy bypass, unknown-node/output-schema validation, non-validating fake state replacement) were addressed exactly; requirement 4 (retain the four prior fixes, determinism, hash stability, project/branch isolation, idempotency) verified by regression.

## Work Performed

1. **Defect 1 — `CaseGraph.model_copy(update={"edges": ("junk",)})` validation bypass** (`__init__.py`): overrode `CaseContractModel.model_copy(*, update=None, deep=False)`. Non-`None` update merges `self.model_dump()` with the update and rebuilds via `type(self)(**merged)`, re-running every field validator and every `after` model validator (`revalidate_instances="always"` included); `update=None` returns `self` (frozen models; identical copy is indistinguishable, immutability preserved). Invalid copies now fail closed at the copy site with typed errors instead of crashing later at hash time.
2. **Defect 2 — unknown node / mismatched output schema** (`fakes.py`): `FakeArtifactStore.put` now calls `graph.node(node_id)` first (unknown → `CC_NODE_UNKNOWN`), then requires `schema_name == node.output_schema` (→ `CC_SCHEMA_MISMATCH`); the old "schema merely declared in graph" check was removed as subsumed. `FakeReservationLedger.reserve` likewise validates `node_id` via `graph.node(node_id)` (→ `CC_NODE_UNKNOWN`).
3. **Defect 3 — non-validating state replacement** (`fakes.py`): `_FakeModel` now inherits `CaseContractModel` (acquiring the validated `model_copy`); `FakeReservation` gained a `model_validator(mode="after")` enforcing the product `ExecutionReservation` terminal contract (terminal status ↔ matching `terminal_state`; completed = output hash + no error code; failed/unknown = error code + no output hash; non-terminal = no terminal fields); `FakeReservationLedger` replaced the two-step `_transition` + secondary `model_copy` pattern with `_assert_transition` (legality + terminal-finality) plus one-shot fully re-validated rebuilds per `complete`/`fail`/`mark_unknown_outcome` — a non-64-hex output hash, empty/whitespace error code, or inconsistent terminal combination is rejected at the rebuild site.
4. Docstrings updated (module docstring, store, ledger, fake base, `CaseContractModel.model_copy`).

## Artifacts And Evidence

Changed files (only worker-01-owned):
- `pocs/protocol_v3/orchestrator/__init__.py` — `model_copy` override with forced revalidation on `CaseContractModel`.
- `pocs/protocol_v3/orchestrator/fakes.py` — `_FakeModel` base change; `FakeArtifactStore.put` node/output-schema checks; `FakeReservation` terminal validator; ledger `reserve` node guard and one-shot validated transitions.

Evidence (all observed):
- Compile: `python3 -m py_compile` (3.9.6) and `/opt/homebrew/bin/python3.12 -m py_compile` (3.12.13) on all three owned files → PASS both.
- Cross-runtime import smoke: `_FakeModel` is subclass of `CaseContractModel`; `FakeContractError.__mro__[1] is CaseContractError`; `model_copy` source contains the `type(self)(**merged)` rebuild → all True.
- Focused counterexamples (all fail closed): `model_copy(update={"edges": ("junk",)})` rejected; `update` with duplicate schemas → `CC_SCHEMA_DUPLICATE`; with a cycle → rejected; with undeclared output schema → `CC_SCHEMA_UNKNOWN`; store `put` unknown node → `CC_NODE_UNKNOWN`; store schema declared but ≠ node output → `CC_SCHEMA_MISMATCH`; `reserve` unknown node → `CC_NODE_UNKNOWN`; `complete(..., "bad")` and `complete(..., "")` rejected; `fail(..., "")` and `fail(..., "   ")` rejected; direct construction of inconsistent terminals (COMPLETED without terminal_state; COMPLETED with error code) rejected; second `complete` on terminal → `FK_INVALID_TRANSITION`; resume FAILED → `FK_TERMINAL_FAILED`; resume UNKNOWN_OUTCOME → `FK_UNKNOWN_OUTCOME`.
- Positive regressions (all pass): `model_copy()` without update returns the same frozen object; `model_copy(update={"branch_id": ...})` yields a valid rebinding; reserve idempotent by logical key (same ID, count 1); start→RUNNING with no terminal fields; complete/fail/mark_unknown_outcome normal paths with consistent terminal combinations; resume completed → COMPLETED; store happy path (matching node + output schema); prior four fixes retained (`CC_SCHEMA_DUPLICATE`, `CC_ROOT_INPUT_DUPLICATE`, `CC_INJECTION_KIND_DUPLICATE`, `FakeContractError` true inheritance); hash stable across shuffled equivalent construction; cross-branch → `CC_BINDING_MISMATCH`; mutable nested input → `CC_INPUT_MUTABLE`.

## Commands And Observations

- `python3 -m py_compile pocs/protocol_v3/orchestrator/{__init__.py,fakes.py,cases/__init__.py}` and same under `/opt/homebrew/bin/python3.12` → both OK.
- Two import/attribute smokes (one per interpreter) → OK.
- In-kernel verification suite (no files written): full counterexample + positive matrix above; all assertions passed on first run after the edits (no probe corrections were needed this pass, unlike repair1 where two probes were construction-error fixes).

## Blockers Or Missing Environment

None. Both runtimes available; pure import/compile/inline checks were sufficient per worker-01 boundary. Integrated `test_case_contracts.py` remains worker-03-owned and does not exist yet, so no `pytest` run was attempted.

## Rerun Requests Or Next Step

- No rerun requested; deliverable complete with acceptance evidence above.
- Next step for Codex: shared-contract review of the repair2 base, then continue the serial Worker 02 → Worker 03 chain. Worker 02/03 can now rely on: validated `model_copy` on all contract/fake models, `CC_NODE_UNKNOWN`/`CC_SCHEMA_MISMATCH` from the stores, and `FK_TERMINAL_STATE`/`FK_TERMINAL_FIELDS`/`FK_INVALID_TRANSITION` reservation semantics.
