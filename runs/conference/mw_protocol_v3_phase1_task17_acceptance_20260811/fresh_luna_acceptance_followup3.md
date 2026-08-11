NOT_READY

P0=0 P1=0 P2=1 P3=0 P4=0

Finding P2 — closure-exposed proof signer remains caller-reachable.

- Evidence: [`harness.py:929`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:929) defines `proof_for`; [`harness.py:938`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:938) exposes `build_request` with validation, but its `__closure__` exposes `proof_for(request)`.
- Reproduction: retrieved `proof_for` from `build_request.__closure__`, signed a directly constructed arbitrary request, then dispatched with a fake adapter.
- Result: `CLOSURE_INTROSPECTION True None True 1 1` — success, physical dispatch entered, probe=1, transport=1.
- Impact: arbitrary unvalidated role/provider/model/tool/path fields can be sealed without RoleEntry, Skill, artifact, region, or session validation.
- Smallest repair: remove any callable signer from the public builder closure, add a regression covering closure reachability, and use only an internal non-callable proof operation. A hostile same-process threat model would require an opaque native/out-of-process signing boundary.

The former module-level paths are closed: no `_seal_validated_request`, `_REQUEST_PROOF_KEY`, `_request_validation_proof`, or `_validated_construct` was found. Direct construction and post-validation mutation both returned `request_unvalidated` with zero probe/transport calls. [`test_harness_policy.py:1619`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/tests/protocol_v3/test_harness_policy.py:1619) does not test closure exposure.

Prior findings remained closed:

- Session polarity: stable `session_recovery_not_authorized`, zero probe/transport.
- Harness mismatch: `adapter_harness_mismatch`, zero probe/transport.
- Fallback bindings: logical call, idempotency, and input hash each raised `HarnessFallbackError`.
- Gate identity: case and whitespace variants rejected by exact comparison at [`harness.py:1039`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:1039).
- Non-`DispatchReceipt`: stable `dispatch_invalid_receipt`.
- Tool/path payload binding: preserved through [`harness.py:321`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:321) and adapter forwarding.
- Windows/backslash paths: rejected by [`loader.py:106`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/registries/loader.py:106).
- `tool_versions`: immutable `MappingProxyType` at [`loader.py:413`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/registries/loader.py:413).

Verification:

- Focused suite: `198 passed, 1 deselected`.
- Targeted contradiction checks: `14 passed`.
- Proof regression cluster: `10 passed`.
- AST parse: `AST_OK 9 files`.
- No services, network, models, OCR, translation, or medical-monitoring workflows invoked.
- One temp-file test was deselected because the read-only environment has no writable temporary directory.

Next safe action: repair the closure signer and rerun the deterministic acceptance suite before reconsidering `READY`.