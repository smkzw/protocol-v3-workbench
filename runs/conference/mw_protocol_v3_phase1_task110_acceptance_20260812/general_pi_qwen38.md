All acceptance probes are complete. Returning the full report.

# Conference Participant Output: mw_protocol_v3_phase1_task110_acceptance_20260812 - general_pi_qwen38

## Boundary Check

- Worked only inside the workspace root `.`; read-only pass. No source/config/test artifact edited (`git status --porcelain`: **0 modified tracked files**; all Task 1.10 artifacts are untracked additions).
- No security tests, no service startup, no live/runtime DB access, no browser/visual work. All probes ran against pure in-memory code (`sys.dont_write_bytecode=True` for eval probes).
- Did not read any worker/manager/peer report. The only execution-prose artifact opened was the task's own `context/..._context.md` loop log, which the conference context explicitly designates as part of the task contract source of truth (scope/authority/criteria); all claims below were re-derived from artifacts and re-executed tests, not adopted from the log.
- Residual side effect disclosure: mandated pytest runs may refresh `.pytest_cache/`/`__pycache__/` (gitignored infra artifacts). No protected path touched.

## Independent Work Product

**1. Frozen plan hash (independently computed, not accepted on trust):**
- `shasum -a 256 .hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md` → `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, matching the contract's declared hash.
- Additionally `git show 2b530cd:<plan>` hashes to the same value → the plan is byte-identical to the last baseline commit (2026-08-10 13:33) and has not drifted during Task 1.10 execution.

**2. Focused tests (independently executed):** `pytest` on the four Task 1.10 test files → **220 passed, 0 skip/error** (6.5 s). These import via `services.api.app.…` and pass without PYTHONPATH.

**3. Full Protocol v3 suite (independently executed):** bare `pytest tests/protocol_v3` fails collection of 11 modules (`ModuleNotFoundError: No module named 'app'`) because they import `app.…` while `pytest.ini` declares only `testpaths`. With the established convention `PYTHONPATH=services/api` → **1221 passed, 0 skip/error** (14 s), exactly reproducing the acceptance count. See objection O3.

**4. API-isolation selector:** `test_protocol_v3_api_contract.py::TestSharedSurfaceIsolation` → **3/3 passed** (29 deselected from the 32-test file), reproducing the recorded selector shape. Tests prove: api sources import no monitoring/legacy/`app.main` surface; importing `app.protocol_workflow.api` loads no shared surface; `main.py` contains no `protocol_workflow` reference.

**5. Mapping spec + real-contract verification (recomputed, not quoted):**
- `load_mapping_spec(config/medical_writing/protocol_v3/v2_v3_mapping.json)` → `spec_sha256 = 34db4b34…dfa2`, identical to the hash recorded in the contract loop log; file hash `8ee8ac78…`.
- 7 families, **20 declared source types**; `verify_mapping_spec_contracts(spec)` → **0 issues** against the checked-in v2 models/tables/snapshot.
- Tamper probes (all fail closed, all change `spec_sha256`): unknown key → `MappingSpecError`; fabricated `models.FakeType` → rejected by closed type allow-list; adding a nonexistent `covered_fields` entry → verifier flags `whole_payload 声明了不存在字段`; dropping a non-role field (`synopsis_text`) from `covered_fields` → verifier flags `存在未处置字段`. See objection O2 for one asymmetric hole.

**6. Deterministic 3,878-row denominator (independent adversarial corpus, not the test fixture):** built my own 3,878-row synthetic set (3,000 mappable across study_definition/journey; 878 unmappable via declared jsonl corpus type + an undeclared table name). Result: `source == mapped + unmapped` exact (3000/878), every unmapped row quarantined as `unsupported_type` with no fabricated semantic node; permutation determinism (`run_sha256` identical under shuffle); exact replay (3,000/3,000 replayed, lineage ids identical); dry-run input byte-for-byte unchanged after the run.

**7. Idempotent/revision lineage (suite + independent probes):** exact key+revision replay returns identical target identity/hash with zero new lineage nodes; conflicting same-revision (different payload) → quarantined as `duplicate_conflict`, prior entry untouched; changed revision → retained parent + new child (`parent_lineage_id` chain verified for a 3-revision chain); cross-project lineage ids distinct; foreign mapping version and duplicate prior lineage rejected.

**8. Cutover ladder (independently reproduced):** ladder exactly `LEGACY_ACTIVE → SHADOW_READ_ONLY → NEW_CANONICAL`. Fresh project may only enter at the bottom (`unknown_project_reuse` otherwise); skip → `skip`; reverse → `reverse`; same-state → `already_terminal`; CAS mismatch → `cas_mismatch`; same revision+transition → `idempotent_replay`; conflicting same revision → `conflicting_replay` with history unoverwritten. Projects without records are read-only (`is_read_only` fail-closed).

**9. Two-layer mutation guard + inventory (independently executed):**
- Drift check on real sources: **235 discovered handlers / 133 route mutators / 195 service mutators, 0 findings**; `inventory_sha256 = 2e44f83a…9df0` (matches recorded hash).
- Matrix probe over all 3 states: in `SHADOW_READ_ONLY` and `NEW_CANONICAL`, **101/101 legacy_write routes and 94/94 legacy_write service mutators blocked** with the single stable code `legacy_mutation_blocked`; in `LEGACY_ACTIVE` 0 blocked; unclassified operation id fails closed via `MutationGuardConfigurationError` (inventory drift refusal); unknown-project mutation fails closed via `LegacyMutationBlocked(state=None)`.
- Investigator-brochure route `route.register_medical_writing_investigator_brochure` and `service.source_intake.SourceRegistryService.register_medical_writing_document` are both `legacy_write` and blocked in both read-only states (explicit counterexample executed). Generic source-registry and monitoring routes/services remain `excluded` — medical-monitoring source intake stays outside the cutover. Route row confirmed against `services/api/app/main.py:4753`.
- Read parity: `legacy_read` returns exact payload/hash/project in all three states and with no cutover record; returned payload rejects mutation; caller payload untouched.

**10. Protection and representation checks:** zero modified tracked files (medical-monitoring, `main.py`, plan all untouched — plan tracked since `2b530cd` with identical content hash). `legacy/` package imports are pure (no DB, no `app.main`, no runtime singleton). Nothing in the artifacts or tests represents the synthetic dry-run as a live migration or the standalone contracts as mounted runtime wiring; `main.py` contains no `protocol_workflow` reference.

## Evidence And Assumptions

**Evidence (directly observed):** all commands/outputs above; `git status`/`git log`/`git show` state; exact pass counts 220 / 1221 / 3; recomputed hashes for plan, spec, inventory; the adversarial corpus and tamper probe results in section 5–9.

**Assumptions:**
- A1: The established invocation convention for the full suite is `PYTHONPATH=services/api pytest tests/protocol_v3` (grounded: it reproduces the exact 1,221 count recorded independently in the contract loop log; bare pytest cannot import `app.…` by design of `pytest.ini`).
- A2: `.pytest_cache`/`__pycache__` refresh during mandated test execution is permitted infra side effect, not a prohibited write; no source/config/test file changed (verified via git afterwards).
- A3: "API isolation selector" = `TestSharedSurfaceIsolation` (3 tests, 29 deselected), matching the recorded shape.

## Risks, Gaps, And Verification Needs

**Objection O1 (bounded question for Codex — highest-impact design uncertainty):** target identity is project-unscoped. Two projects with identical `source_id` both map to the same `target_id` (`v3::study_definition::sd:dup` in my probe). Lineage ids, migration keys and accounting remain fully project-isolated (verified), so no acceptance criterion is violated — but any downstream projection that joins on `target_id` alone would alias across projects. Question: is project-scoping of v3 semantic-node identity delegated to the storage/canonical layer in a later phase, or should the identity rule basis include `project_id`? Safe provisional path: keep current behavior; Task 1.11 cross-project isolation tests will exercise it.

**Objection O2 (concrete defect, advisory — does not break any enumerated criterion):** `whole_payload.covered_fields` drift detection has an asymmetric hole. Dropping an identity/project/revision *role* field (e.g. `definition_id`) from `covered_fields` yields **0 verifier issues** (roles are covered separately) even though the rule contract says covered_fields must enumerate the model's complete field set; dropping a non-role field is correctly flagged. No data loss occurs (whole_payload deep-copies the full payload regardless), but the explicit-enumeration invariant is weaker than declared. Remediation (owning scope: `services/api/app/protocol_workflow/legacy/migration_map.py` verifier functions): require two-way equality `covered_fields == model_fields` for `whole_payload` rules instead of the current union-subset check. Shipped spec passes either way.

**Objection O3 (process gap):** the full-suite pass is environment-dependent and the convention is undocumented: bare `pytest tests/protocol_v3` produces 11 collection ImportErrors while the four focused files pass. Remediation: document the `PYTHONPATH=services/api` invocation or add `pythonpath = services/api` to `pytest.ini` (a write, out of my scope; assign to a later authorized task). Not an artifact defect — the recorded acceptance count is reproducible under the convention.

**Gap G1:** no artifact pins the spec/inventory hashes (`34db4b34…`, `2e44f83a…`) into a checked-in manifest; integrity currently rests on recomputation against recorded values (done here, both match). Optional hardening for a later task.

## Recommended Next Step

READY

Every material success criterion is independently grounded by my own executions and counterexamples: seven-family explicit inventory with exact accounting; real-contract mapping with whole-payload preservation and 0 drift issues; idempotent/conflict/child lineage semantics; exact read parity; forward-only cutover with all rejection codes; two-layer fail-closed guard covering all 195 inventoried mutators including the investigator-brochure route/service bypass fix; 220/220 focused, 1221/1221 full suite, 3/3 API isolation, zero skip/error; frozen plan hash verified against baseline commit; zero protected-path modifications; synthetic evidence never represented as production migration. Codex should record objections O1–O3 as follow-up items (O1 as a bounded decision question; O2 and O3 as hardening in a later authorized write round) — none of them violates a Task 1.10 acceptance criterion.
