Independent engineering cross-review of Protocol v3 Plan v2 and Phase R. Starting with the conference context and plan, then auditing the claimed fix paths against source.Next I'll pull Plan v2, Phase R evidence, and the core backend/frontend surfaces in parallel so the review is grounded in source, not claims.Pulling Plan v2 Phase R/1R criteria and the architecture seams that matter for H-R: authority amendment, workflow/storage, and frontend API.Workers failed on flags; switching to direct reads and targeted scouts for Plan v2 gates and architecture gaps.Notable: `mutable_source_baseline.json` looks overwritten with live observation content. Digging into Plan v2 and that baseline swap next.Baseline identity swap looks material. Next: Plan R criteria, storage/router presence, and decisive Phase R tests.Confirming product `sqlite.py` is absent (1R.1 still open). Verifying selected factory/router, authority scripts, and reproducing Phase R tests.Focused Phase R suite is green (183). Checking H-R git cleanliness, baseline identity, dead frontend client, and PoC-copy hazards next.# Conference Participant Output: mw_protocol_v3_engineering_crossreview_20260905 - general_single_object

## Boundary Check

- Stayed inside isolated workspace `.`; Plan v2 / design v1.3 read from allowed `../plan-upgrade-20260905/`; live `../workbench` used only for drift line-count / observation comparison.
- No source edits, commits, product services, model/OCR/Word/browser calls.
- Tests limited to `tests/protocol_v3` and `pocs/protocol_v3/orchestrator/tests` with `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=services/api:packages:.`, `/opt/homebrew/bin/python3.12`, `-p no:cacheprovider`.
- Did not write `runs/conference/.../general_single_object.md`; this body is the report for the runner.
- No final visual/clinical/regulatory acceptance claimed; Codex retains authority.

## Independent Work Product

### Verdict (advisory)

**H-R: NOT_READY.**  
Phase R technical green is real and reproducible, but Plan v2 Gate H-R is not closed: R.2 shared/legacy impact assessment is unfinished, and the R.1 checkpoint artifact is missing.  
Separately: Plan v2 Phase 1R text has copy/wiring hazards that will break fail-closed storage and replay if executed as written.

### Component map (offline kernel vs runtime vs planned)

| Layer | Status | Evidence |
|---|---|---|
| Ports / memory UoW / events / application / Agent⑤ / API router factory | Implemented offline kernel | `services/api/app/protocol_workflow/{ports,storage/memory.py,events,application,agent5,api/router.py}` |
| Product SQLite adapter | Missing (fail-closed) | No `storage/sqlite.py`; `selected.py:273-282` raises `StorageNotReadyError` without `adapter_builder` |
| PoC SQLite | Evidence only; imports product ports | `pocs/protocol_v3/storage/sqlite_adapter.py` imports `app.protocol_workflow.ports.*`; `selected.py` forbids product import of PoC |
| Router product mount | Not mounted | `main.py` has **zero** `protocol_workflow` / `protocol-workflow` hits; router docstring says composition root not edited |
| Feature-flag durable allowlist | Not implemented | `legacy/cutover_state.py:7-9` is in-memory only, explicitly “no feature-flag wiring” |
| Frontend v3 workbench UI | Not present | `protocol-workbench/` contains only `protocolWorkspaceApi.mjs`; **0 importers** |
| Template v2 registry | Planned | `config/.../templates/tp_ma_07_v2/` absent; additions only in authority amendment |
| Orchestrator typed cases | PoC offline accepted | Task 2.1 pause; `pocs/.../orchestrator/tests` **75 passed** this session |

### Phase R counter-proof (what holds / what does not)

**Holds (reproduced):**
1. Focused Phase R suite: **183 passed** (`test_authority_locator_amendment`, `test_source_drift_reconciliation`, `test_frozen_authority_manifest`, `test_repository_hygiene_mutator`).
2. Full `tests/protocol_v3`: **1240 passed, 101 subtests, 2 warnings, 14.60s**.
3. Authority amendment: **13 relocations + 8 additions**; `validate_amendment` OK; Plan v2 SHA `040eb6ad…` matches; frozen manifest SHA `f4b385d4…` matches on-disk `immutable_protected_assets.json`; TP-MA-07 v2 `018d28d3…` matches.
4. Historical baseline copy `mutable_source_baseline_20260809.json` SHA **`32e274b47ec14a40…`** exact.
5. `immutable_protected_assets.json` / `protected_path_rules.json` **unchanged vs HEAD**.
6. Product app source not in Phase R tracked diff (only qc scripts + baseline fixture + two tests modified; additive amendment/scripts/tests untracked).

**Does not hold for H-R:**
1. **R.2 incomplete.** `source_drift.json` counts 313 diffs (129 monitoring / 127 writing / 57 shared) and states: *“Path-based triage, not attribution. Shared files require semantic review; no files merged.”* Plan R.2 requires evaluating whether writing/shared deltas affect **legacy read adapter assumptions**. **23 shared `changed` paths** include `frontend/src/App.jsx`, `services/api/app/main.py`, `ai_gateway.py`, `source_intake.py`, contracts `__init__/models` — none semantically dispositioned in the Phase R run artifacts (only JSON observations). App.jsx line counts match plan’s known gap (iso **16002** vs live **13514**); that is detection, not impact assessment.
2. **R.1 checkpoint missing.** Plan requires `runs/mw_protocol_v3_phaseR_r1_20260905.md`. Only `runs/mw_protocol_v3_phaseR_20260905/{live,isolated,source_drift}.json` exist.
3. **Baseline identity trap (acceptable per R.2 text, risky in practice).** Tracked `mutable_source_baseline.json` is **byte-identical** to `live_source_observation.json` (`source_commit=d2daef1`, root=`.../workbench`). Schema dropped `baseline_id` / `determinism` / inclusion rules. Tests correctly retarget historical file, but any tool still treating `mutable_source_baseline.json` as “isolated baseline” will silently pin **live**.
4. **H-R “git only Phase R declared diff”.** Tracked Phase R deltas are narrow; workspace also has conference/review/prompt/metrics untracked overlay. If H-R means whole worktree cleanliness, it fails; if runner artifacts are excluded, Phase R set is still uncommitted (expected pre-commit) but R.1 md still absent.

### Highest-impact defect (architecture / Plan v2)

**Plan 1R.1 “mirror PoC + flip factory to return SQLite / default memory for tests” conflicts with the accepted fail-closed selection surface.**

- `selected.create_unit_of_work_factory` (`selected.py:235-290`): no default backend; rejects `memory`; requires `adapter_builder`; otherwise `StorageNotReadyError` naming exact missing `storage/sqlite.py`.
- Blind `cp`/`import` of `pocs/.../sqlite_adapter.py` is explicitly forbidden (`selected.py:21-25`, `273-282`).
- PoC already depends on product ports (good for reimplementation), but still embeds **inbox + attempt-key reservation** semantics that **1R.4 plans to delete** after 1R.1–1R.3. Copying PoC then “simplifying” without a port-level cutover will desync `UnitOfWork` (`inbox_repository` still required), `memory.py`, `events/inbox.py` (446 lines), and ≥10 test modules with inbox references.

**Concrete remediation:** Amend 1R.1 to: (a) reimplement product `storage/sqlite.py` against current ports (not import PoC); (b) keep `create_unit_of_work_factory` fail-closed; (c) wire `adapter_builder` only from an explicit composition-root/test harness; (d) tests continue via `create_test_memory_unit_of_work_factory`; (e) defer any factory “default memory” language — it reintroduces silent degradation.

### Second-order Plan v2 amendments (ordered)

1. **Before H-R close:** finish shared semantic review note for the 23 shared changed files (especially `App.jsx`/`main.py`/AI gateway/source intake); write R.1 checkpoint md with amendment + pytest evidence; decide whether conference artifacts are H-R-excluded.
2. **1R.1:** as above; assert SQLite ≥3.51.3 in product adapter open path (decision.md already notes product preflight absent).
3. **1R.2:** durable project allowlist table in **product** SQLite; do **not** overload `CutoverStateRegistry` (in-memory ladder ≠ feature flag). Mount router only behind empty-default allowlist; re-run H6 “import/mount does not start workers / write legacy DB”.
4. **1R.3:** keep as hard prerequisite to 1R.4; event-replay hash + backup/restore must be green on product sqlite before inbox merge.
5. **1R.4:** treat as breaking schema change: migrate `UnitOfWork` Protocol, memory+sqlite adapters, outbox result columns, reservation three-state keys, and `protocol_v3.py` field-hash removal with explicit minor schema bump + migration; freeze PoC adapters as historical evidence or dual-maintain — do not leave product importing deleted inbox APIs.
6. **Frontend reality:** `protocolWorkspaceApi.mjs` is a dead client (methods exist; no UI import; API unmounted). DC-028 (≤15 clicks / ≤3 free-text) is Phase 6R/8R only; legacy `medical-writing/*` journey UI must not be mistaken for v3 A+C workbench (`protocol-workbench/` shell absent).
7. **Authority brittleness:** `authority_locator_amendment.validate_amendment` requires exact set equality of all `.docx/.xlsx` under `new_root` vs relocation map — any extra SOP file fails closed. Document SOP tree freeze or amendment-gated additions before Phase 3R extraction.

### User-flow counterexample

Create→draft→recommend→edit→export on the **v3** path cannot succeed in-process today: no product store, no mounted router, no workbench UI, template registry v2 missing. Legacy authoring panels still exist and will absorb clicks unless strangler (6R.4) is explicit. Risk: Phase 1R “API green” without UI gate creates a false “闭环” while the lazy user still lives in v2 surfaces that Plan says contradict DC-028.

## Evidence And Assumptions

**Evidence (observed this session):**
- HEAD `3d6772f`; Plan v2 SHA `040eb6ad…`; historical baseline `32e274b4…`; immutable manifest `f4b385d4…`.
- pytest: 183 focused / 1240 full / 75 orchestrator.
- `validate_amendment` OK; 13+8 asset hashes match.
- `mutable_source_baseline.json == live_source_observation.json` bytes; live commit `d2daef1`.
- Drift classification caveat + 23 shared changed paths.
- No `storage/sqlite.py`; `main.py` unmounted; `protocolWorkspaceApi` orphan; `tp_ma_07_v2` absent; R.1 checkpoint md absent.
- Inbox still first-class in ports/memory/events/tests.

**Assumptions:**
- Conference/review untracked files are runner overlay, not Phase R product work — **Codex must confirm H-R scope**.
- “No product-source change during Phase R” means app/frontend/contracts product code, not qc/fixtures/tests (those did change, as required).
- Live tree was not mutated by Phase R (not re-verified beyond observation metadata / local non-write).

**Inferences:**
- Path triage alone cannot satisfy R.2’s “评估是否影响 legacy read adapter 假设”.
- Executing 1R.1 as currently worded will either violate fail-closed selection or create a temporary PoC-shaped product adapter that 1R.4 must immediately rip apart — schedule risk and replay risk.

## Risks, Gaps, And Verification Needs

| Risk | Why it matters | Verification needed |
|---|---|---|
| H-R false READY from test green alone | Shared drift / checkpoint gaps remain | Codex: require semantic disposition table + R.1 md before H-R |
| Blind PoC copy | Breaks “pocs are evidence only”; may bake inbox into product | Diff product ports vs PoC after draft sqlite.py; forbid poc imports |
| 1R.2 reuses cutover registry | Non-durable flags → restart loses allowlist / wrong projects on v3 | Test flag survives process restart only via sqlite file |
| 1R.4 before replay proof | Lost exactly-once / hash drift | 1R.3 replay hash gate mandatory |
| Frontend orphan client | UI work starts from wrong baseline | Inventory: only API file; no shell |
| Authority exact-set check | SOP tree churn blocks rebuild | Policy for additive SOP files |
| Baseline name collision | Future R/tools pin live as “baseline” | Rename or document `mutable_source_baseline.json` = live observation supersession |

**Bounded questions for Codex:**
1. Is H-R blocked until a written semantic review of the 23 `shared_manual_review` changed files (esp. `App.jsx`/`main.py`), or is path triage + “no merge” enough?
2. Are runner conference artifacts excluded from “隔离区 git 只含 Phase R 声明 diff”?
3. Authorize Plan v2 text amend for 1R.1/1R.2 (preserve `StorageNotReadyError`; separate durable allowlist from `CutoverStateRegistry`) before any 1R coding?

**Safe provisional path if unanswered:** treat H-R as NOT_READY; do not start 1R; draft the three Plan amendments above; keep product factory fail-closed.

## Recommended Next Step

1. Codex adjudicate the three questions; if Q1/Q2 require work, finish R.2 semantic note + R.1 checkpoint, then re-judge H-R.
2. Only after H-R: open 1R.1 with amended contract (product sqlite reimplementation + builder wiring; no PoC import; no default-memory factory).
3. Keep 1R.3 before 1R.4; treat inbox/hash-field removal as a versioned cutover with replay-hash CI gate.
4. Do not schedule frontend “workbench” tasks until `protocol-workbench/` has more than an unmounted API client — otherwise DC-028 work will latch onto legacy v2 UI and recreate P0-3.
