I'll act as the independent Task 1.9 verifier: first read `AGENTS.md` and the frozen conference context, then inspect implementation/tests directly and run the decisive checks.Next I'll verify the frozen plan SHA and inspect the Task 1.9 implementation surfaces in parallel.Shell was blocked once; continuing with file reads and a narrower SHA/test invocation.Shell is blocked in this session; I'll keep inspecting sources/tests via reads and retry a minimal readonly command.Continuing with Agent⑤, API/client, storage fail-closed behavior, and the three focused tests.Shell remains blocked in Ask mode, so I'll deepen static falsification of the critical paths and record the unverifiable checks explicitly.# Conference Participant Output: mw_protocol_v3_phase1_task19_acceptance_20260812 - general_grok45_cursor_fallback

## Boundary Check

- Workspace: current root only; read-only inspection of frozen Task 1.9, design §§5.1/5.3/5.4/17.2/18/19, `application/` / `agent5/` / `api/`, `protocolWorkspaceApi.mjs`, three Task 1.9 tests, and adjacent `storage/selected.py` + reducer contracts.
- Did **not** read Worker/manager reports, Qwen/Grok/other participant outputs, or write `runs/conference/.../general_grok45_cursor_fallback.md`.
- Did **not** edit files, install packages, start services, or run browser/visual/live-model/OCR/translation/security suites.
- **Blocked:** every Shell invocation in this Cursor Ask-mode session was rejected (`Rejected:`), so plan SHA hashing, `readiness_report()`, focused/full pytest, live `git` delta, and Node binary probing could **not** execute here. That is a verified **verifier-environment** fallback failure, not treated as a product defect by itself.

## Independent Work Product

### Static contract map (inspected)

| Surface | Anchor | Observation |
|---|---|---|
| Application mutations | `application/service.py` `create_study_definition` / `apply_decision` | UoW via injected factory; reducer `replay_or_apply` + `EventSourcedUnitOfWork.build_and_apply`; exact replay returns without second write; failures mapped to typed catalog |
| Commands | `application/commands.py` | Frozen commands require `project_id` / `expected_revision` / `idempotency_key` / actor / reason / full `DecisionRecord`; genesis snapshot binding at construction |
| Queries | `application/queries.py` + service getters | Typed reads only; no CAS/event/outbox write API on query path |
| Agent⑤ | `agent5/coordinator.py`, `run_manifest.py`, `exception_cards.py` | `Agent5QueryFacade` one-shot captures four query results then drops service; no severity/Gate-skip/QC/submission API; `GateResult` has no `skipped`; empty/duplicate source lineage rejected; unknown/cyclic work rejected by `WorkPackageGraph` |
| API | `api/router.py`, `schemas.py` | Prefix `/api/projects/{project_id}/protocol-workflow`; path/body match **before** service; fresh facade/coordinator per Agent⑤ request; no exception-card endpoint; Chinese tag `方案工作流` + Chinese summaries; public envelope only |
| Client | `protocolWorkspaceApi.mjs` | Injectable fetch; network / invalid-JSON / non-OK → `ProtocolWorkspaceApiError`; detail normalized to four public fields; no exception-card method |
| Product storage | `storage/selected.py` `create_unit_of_work_factory` / `readiness_report` | No builder → `StorageNotReadyError`; readiness → `status="not_ready"` |
| main.py | `services/api/app/main.py` | Grep: **no** `protocol_workflow` / `protocol-workflow` |
| Isolation snapshot | conversation-start `git status` | Task 1.9 paths are untracked adds; **no** medical-monitoring / `main.py` modifications listed |

### Falsification attempts (static)

Attempted to falsify each required risk class against current source + test intent:

1. **Atomic CAS/event/outbox + exact replay** — Service composes accepted reducer + UoW; create-on-existing non-matching CAS goes through `replay_or_apply` (raises `RevisionStaleError` / payload conflict, covered by `test_create_on_existing_with_different_decision_fails_closed`, `test_same_idempotency_key_different_payload_rolls_back`, `test_rollback_on_event_append_failure`). No static P0–P4 found.
2. **Query zero writes** — Query methods only call repository reads; `test_queries_leave_zero_write_side_effects` encodes the decisive check. No write helpers on query path.
3. **Retained Agent⑤ authority leakage** — Facade `__slots__` hold only frozen results; coordinator rejects non-`Agent5QueryFacade`; authority tests include bound-method / partial / closure / container DFS (`test_*_retained_graph_*`). No leakage surface found in retained slots.
4. **Empty/duplicate source lineage** — `RunManifest.source_revision_hashes` `min_length=1` + uniqueness; HTTP `RunManifestPinRequest` same; API test `test_empty_source_lineage_rejected_before_any_call`.
5. **Unknown/cyclic work** — `decompose_coordinator_work` requires registered skills; `WorkPackageGraph` rejects unknown deps/cycles.
6. **Gate/severity/QC/submission override** — No such methods/fields on coordinator/schemas/router/client; Gate vocabulary closed without skip.
7. **Stale per-request snapshots** — Router `fresh_coordinator` builds new facade each Agent⑤ call; API tests claim progress/manifest observe post-mutation state.
8. **Path/body mismatch before service** — `_require_path_match` before command/coordinator construction.
9. **Client exception fabrication** — No exception-card client/HTTP route.
10. **Public/audit leakage** — Router uses `to_public_payload()` / Chinese envelopes; client strips non-public detail keys; ExceptionCard scans public copy.
11. **OpenAPI determinism / Chinese-native** — Tag + summaries Chinese; tests assert deterministic OpenAPI across factories.
12. **Client silent success on network/HTTP/invalid-JSON** — Client throws on fetch failure, JSON parse failure, and `!response.ok`.

### Severity-ranked findings

| Sev | Finding | Evidence |
|---|---|---|
| **P0–P4 product** | **None identified** under bounded Task 1.9 static inspection of the listed authorities. | See anchors above. |
| **Verifier blocker (non-product)** | Decisive runtime checks could not be executed in this session. | All Shell calls rejected under Ask mode. |

Non-defects (per acceptance contract): deliberate later-phase absence; `main.py` non-mount; product SQLite `not_ready` until adapter wiring — and current code claims exactly that (`selected.py` ~273–283, ~318–331).

## Evidence And Assumptions

**Evidence gathered**
- Frozen Task 1.9 file list matches current creates under `application/`, `agent5/`, `api/`, client, three tests (plan §Task 1.9 ~748–760).
- `main.py` contains no protocol-workflow mount string (rg).
- Selected storage fail-closed `not_ready` without `adapter_builder` (source).
- Test files encode the contradiction suite (CAS/replay/rollback/query zero-write; authority graph scan; API path/body/OpenAPI/Node client script with skip-only-if-no-node).

**Assumptions (material)**
- Conversation-start git snapshot still reflects medical-monitoring / shared / `main.py` delta (could not re-run `git`).
- Expected plan SHA `fa99fbd3…4914` is correct in conference context; **this session did not recompute it**.
- In-memory test adapters used by Task 1.9 tests remain faithful to accepted UoW/CAS/outbox ports (prior Phase-1 contract; not re-executed here).

**Decisive checks status in this pass**

| Check | Status |
|---|---|
| Plan SHA-256 | **NOT EXECUTED** |
| Focused trio pytest | **NOT EXECUTED** |
| Full `tests/protocol_v3/` | **NOT EXECUTED** |
| Node client real execution (not skip) | **NOT EXECUTED** |
| `readiness_report()["status"]=="not_ready"` | **STATIC ONLY** |
| `main.py` unmounted | **STATIC PASS** (rg) |
| medical-monitoring/shared tracked delta zero | **SNAPSHOT ONLY** (initial git_status) |

## Risks, Gaps, And Verification Needs

1. **Blocking gap:** without pytest + Node + SHA + live readiness/git, acceptance criteria forbid `READY` even if static review looks clean.
2. Residual residual risk only until re-run: Node missing would `pytest.skip` in `test_real_node_execution_with_fake_fetch` (`tests/protocol_v3/test_protocol_v3_api_contract.py` ~1265–1268) — that skip would itself be `NOT_READY` under conference success criteria.
3. No independent runtime proof of atomic rollback / zero-write queries beyond reading the test bodies.

## Recommended Next Step

Smallest repair: **re-dispatch this same participant-2 Cursor fallback in Agent mode (shell enabled)** with no code edits, and run only:

```bash
python3 -c "import hashlib; p='.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md'; print(hashlib.sha256(open(p,'rb').read()).hexdigest())"
PYTHONPATH=services/api:packages/contracts:. python3 -c "from app.protocol_workflow.storage.selected import readiness_report; print(readiness_report())"
PYTHONPATH=services/api:packages/contracts:. python3 -m pytest tests/protocol_v3/test_application_service.py tests/protocol_v3/test_agent5_authority_boundary.py tests/protocol_v3/test_protocol_v3_api_contract.py -q --tb=short
PYTHONPATH=services/api:packages/contracts:. python3 -m pytest tests/protocol_v3/ -q --tb=line
rg -n 'protocol_workflow|protocol-workflow' services/api/app/main.py || true
git status --short -- medical-monitoring services/api/app/main.py
which node
```

If SHA matches, readiness is `not_ready`, main has no mount, mm/shared delta is zero, Node path runs (not skipped), and both pytest invocations are green → product side can move to Codex final acceptance as `READY`. If any fail, repair that single failure and rerun the same commands.

Codex remains final authority.

NOT_READY
