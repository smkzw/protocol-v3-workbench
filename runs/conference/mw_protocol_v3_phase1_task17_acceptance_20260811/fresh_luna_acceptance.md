# Fresh independent acceptance report

Decision: **NOT_READY**

Findings: P0=0, P1=3, P2=4, P3=1, P4=0.

## Findings

1. **P1 — Session polarity is not enforced by the common dispatcher**

   The check exists only in `build_request()`; the dispatcher trusts the `_validated` stamp and does not re-check `same_session_recovery` before preflight/probe/transport. `_validated_construct()` is directly callable.

   Evidence: [harness.py:307](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:307), [harness.py:1099](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:1099).

   Reproduction: a validated request mutated to `same_session_recovery=False` with a non-null session returned:

   `DISPATCH_FALSE_WITH_SESSION True None True 1`

   Smallest repair: add the polarity invariant as the first dispatcher check, before gate/preflight/probe; make `_validated_construct` inaccessible or remove it as a caller-reachable constructor.

2. **P1 — Adapter harness identity is not bound to the request**

   `TransportAdapter` exposes provider/model but no harness field. All adapter preflight methods check provider/model only. An `OmpCliAdapter` configured with provider `codex-app` successfully dispatched a request intended for the Codex harness.

   Evidence: [harness.py:530](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:530), [omp_cli.py:232](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/adapters/omp_cli.py:232).

   Reproduction: `HARNESS_MISMATCH_FALSE_SUCCESS True None True 1`.

   Smallest repair: add an explicit adapter `harness` identity and compare it centrally with `request.harness` before probe/transport.

3. **P1 — Fallback authorization is not bound to the same logical call**

   `FallbackInput` carries `logical_call_id` and `idempotency_key`, but `build_fallback_request()` never validates or uses them. Any caller supplying `failed` plus an error code can produce a fallback payload, including empty logical identifiers.

   Evidence: [harness.py:447](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:447), [harness.py:1020](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:1020).

   Reproduction: empty logical identifiers were accepted and returned `{'content': 'x'}`.

   Smallest repair: require typed prior-dispatch evidence containing matching logical call/idempotency identity, terminal state, and input hash; reject missing or mismatched evidence.

4. **P2 — Gate model comparison is not fully exact**

   `_effective_gate_model()` strips whitespace before comparison. Thus `PaddleOCR-VL-1.6 ` is accepted as equal to `PaddleOCR-VL-1.6`.

   Evidence: [harness.py:934](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:934), [harness.py:984](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:984).

   Reproduction: `WHITESPACE_GATE True None 1`.

   Smallest repair: reject surrounding whitespace and compare the raw effective identity byte-for-byte, retaining case sensitivity.

5. **P2 — Invalid typed receipts can escape as untyped exceptions**

   The dispatcher catches exceptions raised by `adapter.dispatch()`, but `_validate_receipt()` assumes the returned value is a `DispatchReceipt`. A custom adapter returning `None` causes an uncaught `AttributeError`.

   Evidence: [harness.py:1248](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:1248), [harness.py:1355](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:1355).

   Reproduction: `INVALID_RECEIPT_ESCAPES AttributeError 'NoneType' object has no attribute 'output_schema_ref'`.

   Smallest repair: type-check the receipt before field access and return a stable `dispatch_invalid_receipt` result with `dispatched=True`.

6. **P2 — Validated tool/path allowlists are dropped before physical dispatch**

   `build_request()` validates contract tools/paths against the Skill, but `HarnessDispatchRequest.to_payload()` does not carry `allowed_tools` or `allowed_paths`. The injected adapter transport therefore cannot enforce the validated allowlist.

   Evidence: [harness.py:743](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:743), [harness.py:318](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:318).

   Reproduction: `ALLOWLIST_KEYS_PRESENT False`.

   Smallest repair: carry the immutable allowlists or a binding digest into the dispatch request and enforce them at the adapter/transport boundary.

7. **P2 — Registry path validation accepts Windows absolute/backslash paths**

   The loader rejects POSIX absolute and parent-traversal paths but not values such as `C:\secret`.

   Evidence: [loader.py:104](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/registries/loader.py:104).

   Reproduction: `C:\secret` was accepted by `load_skill_registry()`.

   Smallest repair: reject backslashes, drive-letter paths, and UNC paths; add negative tests.

8. **P3 — Skill registry immutability is shallow**

   `SkillEntry.tool_versions` is a mutable `dict` inside a frozen Pydantic model.

   Evidence: [loader.py:350](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/registries/loader.py:350), [loader.py:366](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/registries/loader.py:366).

   Reproduction: `NESTED_MUTATION stdlib-urllib.v1 MUTATED`.

   Smallest repair: deep-freeze nested registry metadata using an immutable mapping representation.

## Checks performed

- Registry tests: **31 passed**.
- Harness deterministic tests excluding sandbox-temp-dependent Codex cases: **114 passed**.
- OMP tests: **26 passed**.
- Codex command/schema subset: **12 passed**.
- Manual Codex new/resume plans: passed; URI resolved to an existing local JSON path.
- AST parse: `AST_OK 9 files`.
- Imports: `IMPORT_OK`.
- Frozen plan SHA-256 matched:

  `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`

- No medical-monitoring path appeared in `git status`; no tracked monitoring diff was observed.
- No source, test, configuration, record, or generated artifact was modified.

The complete suite could not run in this read-only environment because `tests/__init__.py` and Codex test helpers require a writable temporary directory. No live service, network, model, OCR, translation, or monitoring workflow was invoked.

Next safe action: repair the three P1 boundaries first, add regression tests for all findings, then rerun the full deterministic suite in a writable isolated test runtime.