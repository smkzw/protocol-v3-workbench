# Task 1.7 Independent Repair Verification

Decision: **NOT_READY**

Counts:

- P0: 0
- P1: 0
- P2: 1
- P3: 0
- P4: 0

The eight prior findings do not reproduce. One new P2 Harness-boundary bypass remains.

## Finding

### P2 — Caller-reachable validation stamp bypasses strict binding

Location: [`harness.py:309`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:309), [`harness.py:1134`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:1134)

Reproduction:

```python
valid = build_request(...)
kwargs = {k: v for k, v in vars(valid).items() if k != "_validated"}
kwargs["allowed_tools"] = ("not-in-skill",)

forged = HarnessDispatchRequest._validated_construct(**kwargs)
result = HarnessDispatcher().dispatch(
    request=forged,
    adapter=_direct_adapter(fake),
)
```

Observed:

```text
PRIVATE_STAMP_BYPASS True None 1 1 ['not-in-skill']
```

Impact: `_validated_construct()` is callable through the public request class. A caller can create a request that never passed RoleEntry/Skill/artifact/region validation, stamp it as validated, and reach transport. The dispatcher currently trusts only the boolean `_validated` flag.

Smallest repair: replace the boolean/private-constructor convention with an opaque factory-issued proof bound to all request fields, or rerun the full Role/Skill/artifact binding at dispatch. Add a regression test that directly exercises `_validated_construct()` with tools or paths outside the skill and requires stable pre-dispatch rejection.

## Prior contradiction checks

| Check | Result |
|---|---|
| `same_session_recovery=false` with session ID | Fixed. `session_recovery_not_authorized`, `dispatched=False`, zero probe/transport calls. |
| True same-session recovery | Fixed. OMP fake produced a resumed plan and one invocation. |
| Adapter/request harness mismatch | Fixed. `adapter_harness_mismatch`, zero probe/transport calls. |
| Fallback logical-call, idempotency, input-hash binding | Fixed. All three mismatches raised `HarnessFallbackError`. |
| Gate case and whitespace identity | Fixed. Lowercase and trailing-space identities fail closed before probe. |
| Non-`DispatchReceipt` return | Fixed. Stable `dispatch_invalid_receipt`, `dispatched=True`, no exception escape. |
| Tool/path payload propagation | Fixed. Physical fake payload contained both `allowed_tools` and `allowed_paths`. |
| Windows/backslash path rejection | Fixed. Loader returned `RegistryDocumentError`. |
| Nested `tool_versions` immutability | Fixed. Loaded value is a `mappingproxy`; item assignment and `|=` both raise `TypeError` without mutation. |
| Lease release failure classification | Fixed for ordinary exceptions. Release-only failure returns `gate_lease_release_failed`; transport plus release failure preserves `dispatch_exception` and `dispatched=True`. |
| Adapter documentation | Correct. Documentation assigns lease heartbeat/release and probe caching to the common Harness/gate boundary. |

Relevant repaired locations include [`harness.py:893`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:893), [`harness.py:1043`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:1043), [`harness.py:1145`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:1145), [`harness.py:1425`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/runtime/harness.py:1425), [`loader.py:107`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/registries/loader.py:107), and [`loader.py:413`](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/registries/loader.py:413).

## Verification commands and results

- Focused collection: `197 tests collected`.
- Deterministic focused run: `195 passed, 2 deselected`.
- OMP subset: `26 passed`.
- Codex subset with an existing workspace JSON used as the read-only schema resolver: `36 passed`.
- Targeted contradiction tests: `9 passed`.
- AST parse of Harness, all adapters, loader, idempotency runtime, and both test files: `AST_OK 10 files`.
- Frozen plan hash:

```text
fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914
```

- `git diff --check`: exit 0.
- No `medical-monitoring` or `monitoring` path appeared in porcelain status output.
- No files were modified by this verifier, and the runner-managed report path was not written.

## Environment-only limitations

The original focused tests that create temporary schema files could not run unchanged because the read-only environment has no writable temporary directory:

```text
FileNotFoundError: No usable temporary directory found
```

The two affected behaviors were reproduced without writes using existing workspace files. The full 867-test suite was not run because it may invoke prohibited live/service/medical workflows and the environment cannot support normal pytest temporary capture.

## Next safe action

Repair the caller-reachable validation stamp, add the regression test, then rerun the 197 focused tests in a writable isolated test environment and perform the permitted deterministic full-suite subset.