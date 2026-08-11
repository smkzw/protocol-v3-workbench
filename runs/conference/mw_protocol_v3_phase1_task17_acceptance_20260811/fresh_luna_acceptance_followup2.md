## Verdict: NOT_READY

Counts:

- P0: 0
- P1: 0
- P2: 1
- P3: 0
- P4: 0

### P2 — Module-level private sealer remains caller-reachable

Location: [`harness.py:370`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:370)

`HarnessDispatchRequest._validated_construct` is gone, and ordinary field mutation correctly fails proof validation. However, `_seal_validated_request(**kwargs)` remains directly importable and signs arbitrary fields without rerunning Role/Skill validation.

Reproduction:

```text
OLD_CLASSMETHOD False
HMAC_MUTATION request_unvalidated False 0 0
PRIVATE_SEALER_BYPASS True None True 1 1 ['not-in-skill']
```

Impact: a caller can bypass `build_request()` and dispatch a forged request with tools outside the registered skill.

Smallest repair: make sealing require an opaque capability unavailable through the request-facing module, or move the sealer/key into a controlled closure and add a regression test that directly attempts the private sealer bypass. Removing the name from `__all__` is insufficient.

### Prior findings

All eight earlier findings remain closed:

- False session recovery: stable `session_recovery_not_authorized`, zero probe/transport.
- True recovery: resumed OMP plan, one invocation.
- Harness mismatch: `adapter_harness_mismatch`, zero probe/transport.
- Fallback logical-call, idempotency, and input-hash mismatches: all `HarnessFallbackError`.
- Gate case/whitespace variants: fail closed before probe.
- Non-`DispatchReceipt`: stable `dispatch_invalid_receipt`.
- Allowlists: present in physical payload.
- Windows paths: `RegistryDocumentError`.
- `tool_versions`: immutable `mappingproxy`.
- Lease release failures remain typed and preserve transport classification.
- Adapter documentation still assigns lease lifecycle and probe caching to the common Harness boundary.

Relevant implementation points: [`harness.py:1154`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:1154), [`harness.py:1171`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:1171), [`harness.py:1451`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:1451), [`loader.py:107`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/registries/loader.py:107), and [`loader.py:413`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/registries/loader.py:413).

### Verification

- Focused collection: `199 tests collected`.
- Deterministic focused run: `198 passed, 1 deselected`.
- Targeted repair checks: `6 passed`.
- AST parsing: `AST_OK 9 files`.
- Non-JSON schema fixture reproduced read-only with an existing `.py` file: `schema_file_invalid`, zero probe/transport.

The one deselected test writes a temporary file, but the environment has no writable temporary directory. No files were modified; no services, live models, OCR, translation, or medical-monitoring workflows were invoked.

Next safe action: close the private-sealer route, add the regression test, and rerun the focused suite.