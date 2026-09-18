# C03 Fresh Engineering Review — Frozen 15-File Candidate

- **Reviewer:** C03 (fresh, read-only; no owner reasoning or prior reviewer conclusions used)
- **Run root:** `runs/mw_protocol_v3_v1_1_application_review_20260913`
- **Date:** 2026-09-13
- **Verdict:** The frozen candidate holds up under independent challenge. 1 low-severity frozen-code defect (crafted GET on a correction-run id returns a raw 500 outside the Chinese envelope), 1 low-severity frozen-UI observation (double-click on 准备写作材料 is not ref-guarded in the component itself), and 3 adjacent-layer risks to carry into the pending App-mount phase. All lifecycle claims in the assignment (durable start, GET zero effects, same-input reuse, one correction, crash-window recovery, no redispatch of unknown outcomes, selection order irrelevance, SQLite concurrency) were independently reproduced and passed. **No final product acceptance is claimed.**

## 1. Scope disposition (exact)

**In scope — reviewed against live adjacent sources and probed:**

| Area | Files | Disposition |
|---|---|---|
| Source batch UI + metadata clear | `ProtocolSourceIntake.jsx/.css/.test.jsx`, `protocolSourceApi.test.mjs`, `protocolWorkspaceApi.mjs` | Pass with 1 observation (D2) |
| Durable research prefill API/coordinator | `research_intake.py`, `seed_coordinator.py`, `composition.py`, `sources.py`, `source_identity.py`, `test_seed_*`, `test_restored_product_probe.py` | Pass with 1 defect (D1) |
| Restored successful probe policy | `restored_probe.py` + its test | Pass; real approved receipt verified (G1–G4) |

**Consciously pending (declared by owner; NOT counted as defects here):**
- Actual App mount: `services/api/app/main.py:591` calls `mount_protocol_workflow_router(app)` **without** `seed_coordinator_factory`, so the research-intake router (`composition.py:292-299`) and `RestoredZhipuProbePolicy` are not wired into the product app; only tests exercise them. Likewise `ProtocolSourceIntake` is composed by the non-frozen `ProtocolIntakeWorkspace.jsx`, which no page mounts. This matches the declared "App mount PENDING".
- Production credential binding, native/browser/Word acceptance, full-source modality scope. No screenshots manufactured; no product calls made.

**Read as context only (not new owner acceptance claims):** `graph/runtime.py`, `graph/state.py`, `seed_workflow.py`, `research_seed.py`, `seed_validation.py`, `harness.py`, `adapters/*`, `storage/sqlite.py`, `artifacts/local_store.py`, `main.py`, `ProtocolIntakeWorkspace.jsx`.

## 2. Hash verification

All 15 entries of `artifact_manifest.json` verified with sha256 against **both** the frozen `snapshot/` copies and the live repo paths: **15/15 match, 15/15 match**. The frozen candidate equals current live state.

## 3. Verification evidence

Baselines (existing suites, prescribed environments):

- `pytest` frozen 4 files: **9 passed** (`test_seed_coordinator_integration.py`, `test_seed_source_selection.py`, `integration/test_seed_intake_api.py`, `test_restored_product_probe.py`).
- `vitest --environment jsdom ProtocolSourceIntake.test.jsx`: **19 passed**.
- `node --test protocolSourceApi.test.mjs`: **5 passed**.

Independent scratch probes (all inside `reviewer_scratch/`, synthetic HTTP + temp SQLite only; no live service, no product calls):

| Probe file | Coverage | Result |
|---|---|---|
| `probe_backend_lifecycle.py` | A: start persists before response / GET zero effects (event+reservation counts); B: same-input reuse & one correction; C: crash between initial and correction; D: initial/correction timeout not redispatched; E: two threads resuming the same run on real SQLite (slow opener); F: selection order, duplicate ids, superseded-id rejection; G: real approved receipt restored without any new probe call | **23/23 pass** |
| `probe_api_http.py` | H1–H11: 202 ack, GET terminal, identical re-POST reuse (no new call), 404/409/422 Chinese envelopes, stale selection, brief-only intake, admission gate no-file-creation; H4b: crafted GET on existing correction-run id | **12/13 — H4b fails → defect D1** |
| `ProtocolSourceIntake.c03.test.jsx` | U1–U10: double-click guards (import/correction/prepare), invalid list payload, transport failure, unshapely correction response, clear-flag interplay, unmount/project-switch aborts | **10/10 pass** (U3 documents the double-fire behavior) |
| `probe_api_client_edges.test.mjs` | C1–C4: invalid JSON body, string detail, audit-key stripping, empty 202 body | **4/4 pass** |

Key reproduced facts:
- **Concurrency (E):** two concurrent `resume()` executions over one temp SQLite DB produced exactly **one** physical generation call (opener.calls == 2 incl. probe), `max_active == 1` (no overlapping HTTP), and the run converged to terminal; the loser either failed closed with the typed contention error or converged after the winner — matching `graph/runtime.py:1104-1126` reservation semantics.
- **Crash window (C):** after the initial run completed with `needs_structure_correction` and no correction run, a later resume executed exactly the missing correction (calls 2 → 3), pinning the original materials (`seed_coordinator.py:38-46`).
- **Timeouts (D):** initial or correction `TimeoutError` → status `blocked`; repeated `execute` does not redispatch (calls frozen), consistent with `graph/runtime.py:1148-1150`.
- **Probe restoration (G):** `RestoredZhipuProbePolicy` loaded the actual approved receipt `runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json` (sha256 `dd04b0b4…78904`), pinned its hash, skipped the probe for identity `direct-api:zhipu-coding-plan:glm-5.3-flash` (which the role registry's llm profile matches), and a mismatching receipt fails closed (`prior_product_probe_does_not_match_profile`). `effective_reasoning_effort` stays `not_reported_by_server` — correctly carried, genuinely unverified.

## 4. Findings

### D1 (Low, frozen code) — Crafted GET on an existing correction-run id returns raw 500

- **Where:** `services/api/app/protocol_workflow/api/research_intake.py:41-50` (route maps only `graph_run_unknown` → 404); root cause at `services/api/app/protocol_workflow/agent1/seed_coordinator.py:50` — the first `load_run` of `read()` raises `GraphPlanBindingError` (`graph_plan_binding_mismatch`, a `GraphRunError` subclass with a different code, `graph/state.py:120`) when the id names the `…:correction:1` run bound to the correction graph.
- **Repro:** `probe_api_http.py` H4b — after a run that needed one correction, `GET /api/projects/{p}/protocol-workflow/research-intake/{run_id}:correction:1` → **HTTP 500 `Internal Server Error`**, outside the mounted chain's stable Chinese-envelope contract (`composition.py` module docstring).
- **Impact:** Not reachable through the shipped UI (it only handles the parent id returned by POST). Contract-level breach only; no data effect (GET path, nothing persisted).
- **Minimal fix (either):** in `SeedCoordinator.read`, translate `GraphPlanBindingError` from the first `load_run` into the same 404 semantics (a non-parent id is "not found" from the client's view), or add `GraphPlanBindingError` to the route's 404 mapping beside `graph_run_unknown`. One test: extend `integration/test_seed_intake_api.py` with the H4b scenario.

### D2 (Low, frozen UI) — 准备写作材料 has no synchronous ref guard

- **Where:** `frontend/src/features/medical-writing/protocol-workbench/ProtocolSourceIntake.jsx:465-468` — guard is `prepareDisabled` (state-driven), so two synchronous clicks both pass before re-render; `onPrepare` fires twice (U3).
- **Impact in the intended composition:** neutralized — the (non-frozen) parent `ProtocolIntakeWorkspace.jsx:69` ref-guards `prepare` and blocks while running; and at the API level an identical repeat POST is idempotent (H3: same `workflow_run_id`, zero extra calls). Risk exists only for a future parent that lacks the guard.
- **Minimal fix:** mirror the import/correction pattern (`importBusyRef`, lines 101/134-137) with a `prepareFiredRef`, or accept and document the parent-side contract.

### R1 (Medium, adjacent layer / pending wiring) — Stuck `running` job after server restart has no UI recovery path

POST is the only advancement trigger (`research_intake.py:36-38` schedules the in-process `BackgroundTasks` resume; GET is deliberately effect-free — a stated acceptance criterion). The durable run survives a restart, but the pending resume does not; recovery is re-POST (verified working, C2/H3). However the non-frozen `ProtocolIntakeWorkspace.jsx:44-66,69` polls GET with backoff **and blocks prepare while `status === "running"`** (fieldset disabled, line 96) — a permanently-`running` ghost job deadlocks intake with no user affordance. Must be addressed in the pending App-mount phase (e.g., offer re-submit after stalled polls, or an explicit resume action); the frozen API already supports it.

### R2 (Low, adjacent layer) — Per-request `LocalArtifactStore` instances don't share the manifest lock

`composition.py:287,295` construct `LocalArtifactStore` per request; its read-modify-write manifest cycle is serialized only by a per-instance `RLock` (`artifacts/local_store.py:86,192-210`; the file write itself is atomic temp+`os.replace`). Two concurrent imports of **different content under the same filename** (two tabs/users) can compute the same next revision and one manifest update can be lost; the loser's later `read_content` fails loudly (binding mismatch / not found), never silently. Minimal fix at wiring time: share one store instance in the composition lambdas, or add cross-process manifest locking.

### R3 (Low, pending wiring) — Thread occupancy per dispatch

Each background resume occupies a threadpool thread for up to `REQUEST_TIMEOUT_SECONDS = 600` (`adapters/zhipu_api.py:82`). Many concurrent intakes could starve other sync endpoints in a single-process deployment. Consider a dedicated executor when wiring `main.py`.

### Observations (verified, no action required)

- `SeedCoordinator.read/_outcome`'s `next()` without default (lines 41, 66) is safe by construction (runs always start with `EVENT_RUN_STARTED`; `completed` implies the validate result exists).
- `prepare_current_seed` re-parses DOCX bytes on every POST (`seed_coordinator.py:101-103`); cost is paid even on idempotent re-POST. Acceptable at current scale.
- Import response carries `medical_admission: "pending"` (`sources.py:55`); the PATCH correction response does not repeat the marker — UI copy never claims admission either way, so consistency-only note.
- UI/UX acceptance criteria honored at code level: role select is required before save (no default role); version/jurisdiction default to 未注明 and are never inferred from filenames (`ProtocolSourceIntake.test.jsx:184-186`); categories are document roles, not medical admission; AI output is labeled proposal/not-confirmed (`research_seed.py:170-172` `requires_confirmation: True`, `canonical: None`, `confidence_basis: 'model_estimate_not_medical_admission'`; workspace copy "以下内容是待核对的建议，尚未确认为研究事实").
- The client-contract middleware matches only `/medical-writing` paths (`runtime_readiness.py:160-164`), so the plain `<a href>` source download (`ProtocolSourceIntake.jsx:632-639`) is not blocked by the header requirement.

## 5. Lazy senior medical-writer flow (code-level estimate, intake scope only)

- Clicks: 添加文件 label (1) + native picker confirm (1) + category select open/choose (2) + 保存到资料 (1) + 准备写作材料 (1) ≈ **6 clicks** for the base path; each extra file group ≈ +4; one metadata correction ≈ +4 (更正按钮, category open/choose, 保存更正). Well within **≤ 20** including a high-risk correction dialog. Native file-dialog behavior is part of pending browser/Word acceptance — not verified here.
- Required free-text fields: **0** (brief optional; version/jurisdiction optional with explicit 未注明 defaults). Within **≤ 5**.

## 6. Unresolved limitations

1. App mount, production credential binding, native/browser/Word flows, and full-source modality scope remain **pending by declaration** — untested here by constraint.
2. Effective reasoning effort of the restored probe is `not_reported_by_server` — genuinely unverifiable offline; the code carries it honestly.
3. Multi-process deployment behavior (R2/R3) unprobed: probes ran single-process threads over one temp SQLite DB, matching the current composition model.
4. Frontend probes ran on jsdom via the installed vitest 4.1.10 with a scratch config extending the frozen `vite.config.mjs`; no visual/rendered-DOM assessment was made (no browser launched).
5. `ProtocolIntakeWorkspace.jsx` behavior (R1) is adjacent, unfrozen code — findings there are context for the App-mount phase, not frozen-candidate verdicts.

## 7. Output paths (all under this run's `reviewer_scratch/`)

- `REPORT.md` — this report
- `probe_backend_lifecycle.py`, `probe_backend_output.txt` — 23/23
- `probe_api_http.py`, `probe_api_output.txt` — 12/13 (H4b = D1)
- `ProtocolSourceIntake.c03.test.jsx`, `vitest.c03.config.mjs` (+ `node_modules` symlink to the frontend's installed deps — nothing installed) — 10/10
- `probe_api_client_edges.test.mjs`, `probe_api_client_edges_output.txt` — 4/4

No source file, test file, or history was modified; nothing outside `reviewer_scratch/` was written. No final product acceptance.
