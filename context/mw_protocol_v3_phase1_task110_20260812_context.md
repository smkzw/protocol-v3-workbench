# Task Context: mw_protocol_v3_phase1_task110_20260812

Created: 2026-08-12 01:24:01
Objective: 按冻结计划 Task 1.10 实现 v2→v3 只读 dry-run migration、显式 quarantine、幂等 lineage、旧 mutation 清单与单向 cutover guard，保护医学监查且不触碰真实数据
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `opencode-go` / `deepseek-v4-flash` / `max`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Frozen plan `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 1.10, SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`.
- Approved design `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md` §§17.2, 18, 19 and 20, especially single-source authority and strangler rules.
- Accepted Task 1.9 commit `795fa3f`; the new application/API/Agent⑤ skeleton remains unmounted and product SQLite remains `not_ready`.
- Current v2 contracts and implementations: `packages/contracts/workbench_contracts/models.py`; `services/api/app/medical_writing_authoring_journey.py`; `medical_writing_repository.py`; `medical_writing_legacy_authoring_migration.py`; `medical_writing.py`; `writing_reference_repository.py`; `sqlite_runtime_store.py`; and the `/medical-writing` routes in `services/api/app/main.py`.
- Existing v3 authority: `packages/contracts/workbench_contracts/protocol_v3.py` and accepted `services/api/app/protocol_workflow/{canonical,events,ports,application,errors}.py` surfaces.
- The historic 3,878-row company corpus is an explicit migration-denominator requirement, not permission to read or mutate a live database. Synthetic fixtures and typed snapshots are the only execution inputs in Task 1.10.
- Current filesystem and executed tests outrank delegated prose. Existing source files above are read-only contract evidence.
- Solution-discovery decision: the frozen design fixes the strangler/dry-run route and this task adopts no framework, executable dependency or storage product. Current repository schemas, routes and immutable event contracts are more decisive than a new external landscape scan, so no network discovery is needed for this bounded implementation.

## Scope

- In scope: typed read-only legacy inventory; explicit mapping specification; deterministic dry-run results; quarantine records with reason/locator/source hash; repeatable migration lineage; old mutation route/service inventory; one-way per-project cutover state and two-layer mutation guard; focused synthetic tests.
- Allowed product/test write paths: `services/api/app/protocol_workflow/legacy/`; `config/medical_writing/protocol_v3/v2_v3_mapping.json`; `tests/protocol_v3/test_v2_v3_migration_dry_run.py`; `tests/protocol_v3/test_v2_v3_migration_idempotency.py`; `tests/protocol_v3/test_legacy_read_parity.py`; `tests/protocol_v3/test_legacy_mutation_guard.py`; and this task's context/plans/prompts/runs/reviews/metrics/archives.
- Existing v2 repositories, SQLite schemas, `services/api/app/main.py`, Task 1.9 modules, v3 canonical/events/ports/errors, medical-monitoring and unrelated frontend are read-only.
- Out of scope: reading or migrating any real database; writing legacy rows; wiring product SQLite; mounting routes; changing feature flags; activating `NEW_CANONICAL`; reverse migration; service startup; browser/visual work; live AI/OCR/translation; Task 1.11 security tests; later Protocol phases.

## Success Criteria

- Inventory covers StudyDefinition v2, Authoring Journey/stage drafts, working copies/snapshots, corpus/evidence, decisions/approvals, Protocol documents, and artifact lineage. Each record binds project, source family/type, source ID, source revision token, payload SHA-256 and immutable locator.
- Dry-run input remains byte-for-byte unchanged and reports deterministic source/mapped/unmapped/quarantined counts, output hash and per-reason summaries. Invariant: `source_count = mapped_count + unmapped_count`, every unmapped record produces exactly one quarantine record, and no record is silently dropped or assigned a fabricated semantic node.
- Mapping configuration is versioned, schema-validated, explicit at field/identity/state level, and distinguishes direct, derived, preserved-legacy-only and quarantine outcomes. The 3,878-row corpus case can be represented without pretending all rows map.
- Same migration key plus identical source revision returns identical target identities/hash and no extra semantic effect. A changed source revision creates a new lineage child while retaining the old result.
- Read parity proves adapters preserve the declared v2 values/hashes and isolate projects. Unsupported or ambiguous data remains readable from legacy snapshot but is quarantined for v3.
- Cutover state is exactly `LEGACY_ACTIVE → SHADOW_READ_ONLY → NEW_CANONICAL`; reverse/skip/unknown transitions fail closed. `SHADOW_READ_ONLY` never writes legacy rows. `NEW_CANONICAL` blocks every inventoried legacy mutation at route and service layers with one stable functional error.
- Old `/medical-writing` mutation routes and underlying service mutators are explicitly inventoried with deterministic AST-based drift detection. A new unclassified mutator fails the focused test rather than silently bypassing the guard.
- Focused Task 1.10 tests, full Protocol v3 regression, plan hash and medical-monitoring/shared diff checks pass. Independent verifier owns READY; Codex owns acceptance and commit.

## Risk Boundaries

- Do not read or write live/runtime databases. All migration input is synthetic immutable data supplied directly to pure/in-memory code.
- Do not edit, import-mutator-wrap or monkeypatch `services/api/app/main.py` or any v2 service in this task. The guard and route inventory are standalone contracts for later composition.
- Do not claim cutover activation, production migration or complete mapping of the 3,878-row corpus from synthetic tests.
- Do not perform security testing; mutation guards here are functional single-writer/cutover contracts only.
- Preserve every execution/manager/verifier tool call and session ID; archive after acceptance rather than delete.
- Strictly protect medical-monitoring and unrelated user changes.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-12 01:24:01: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-12 01:25 CST: Read-only reconnaissance found v2 state split across the shared runtime store plus dedicated Journey, writing-reference, corpus, document and artifact SQLite repositories; the route inventory must therefore cover both HTTP handlers and service mutators rather than only `main.py` verbs.
- 2026-08-12 01:27 CST: Frozen three-work-item plan: (1) inventory/quarantine primitives; (2) mapping config and deterministic/idempotent dry-run; (3) cutover state, route/service mutator inventory and functional guard. Work is serial where shared types are consumed; manager remains read-only.
- 2026-08-12: Worker 01 accepted after same-session P1 repair. Inventory snapshots now deep-freeze all count maps and reject forged/non-canonical accounting; 54 focused tests pass.
- 2026-08-12: Worker 02 primary `opencode-go` session `019ff1f3-8cb2-7000-b56f-dde6d7495da1` ended incomplete after creating only the initial JSON. Its same-session resume then failed explicitly with `Session not found`, authorizing the declared `deepseek` fallback rather than a latency fallback.
- 2026-08-12: Worker 02 fallback session `019ff1fa-fdb7-7000-a01c-8985e7b81e55` was retained through two targeted repairs. Codex rejected the initial generic/toy mapping, reproduced shallow spec mutation, then reproduced wrong envelope identity plus silent field loss. The final delegated repair bound 20 real model/table/snapshot locators, real project/identity/revision values, explicit quarantine and deep immutability.
- 2026-08-12: Codex main-venue completion added exact `whole_payload.covered_fields` drift lists and corrected three false quarantines: `approval_gates.updated_at`, `approval_decisions.created_at` and `medical_writing_artifact_lifecycle_events.created_at` are deterministic source revision tokens. Current spec SHA-256 is `34db4b34d5b94114f88c171c125c817d61962cfac3ad2329c1dd63b76b1bdfa2`; all 20 real locators verify with zero issues.
- 2026-08-12: Worker 02 acceptance evidence: wrong project/ID/revision is quarantined with no lineage; valid StudyDefinition preserves framing/PICOS/synopsis/provenance; spec mutation is blocked; 114 Worker 02 tests, 168 Worker 01+02 tests, 70 adjacent contract tests, 3 API isolation checks and the full 1,169-test Protocol v3 suite pass. Plan hash remains frozen and medical-monitoring path changes are zero. Worker 03 is the next safe action.
- 2026-08-12: Worker 03 original session `019ff239-6131-7000-b581-d2ba19052dc4` implemented the pure cutover state, AST mutation inventory and read/guard contracts. Codex reproduced one P1 bypass: the project-bound investigator-brochure upload route wrote file/source-registry state but was marked `excluded`, and its medical-writing-specific service mutator was absent from discovery.
- 2026-08-12: The same Worker 03 session completed targeted repair without fallback or model switch. The route and `SourceRegistryService.register_medical_writing_document` are now `legacy_write`; no project-bound state-changing `/medical-writing` route remains excluded. Real-source drift is 235 handlers / 133 mutating routes / 195 service candidates with zero findings; inventory SHA-256 is `2e44f83a1992b7b2da8497a761666bf77905827291f99dda38247bedb2ae9df0`.
- 2026-08-12: Codex independently proved both the repaired route and service raise `legacy_mutation_blocked` in SHADOW_READ_ONLY and NEW_CANONICAL, while monitoring/source-registry operations remain excluded. Four Task 1.10 tests pass 220/220, API isolation passes 3/3 (29 deselected), full Protocol v3 passes 1,221/1,221, frozen plan hash remains exact, and medical-monitoring changes remain zero. Worker 03 is accepted; read-only Cursor manager is next.
- 2026-08-12: Read-only Cursor manager session `7656b349-59bf-412a-941f-7b1610c42c34` completed in 341.049 s without fallback or edits and returned `READY_FOR_FRESH_VERIFIER`. It independently reproduced the four-test/full-suite/API-isolation evidence plus 3,878 accounting, lineage, cutover, read-parity and brochure-guard counterexamples. Fresh isolated acceptance conference is next.
- 2026-08-12: Fresh Qwen verifier independently exposed a blocking whole-payload drift hole: removing identity `definition_id` from StudyDefinition `covered_fields` still yielded `verified=True`. Codex reproduced the exact counterexample, overrode the participant's nominal READY and marked conference NOT_READY. Grok's first output was incomplete and was completed in the same session.
- 2026-08-12: Worker 02 same fallback session `019ff1fa-fdb7-7000-a01c-8985e7b81e55` Recovery 04 repaired exact two-way whole-payload coverage for Pydantic and SQLite payload models and added five targeted counterexamples. Codex now observes 225 Task 1.10 tests, 1,226 full Protocol v3 tests and 3 API-isolation tests passing; spec SHA remains `34db4b34d5b94114f88c171c125c817d61962cfac3ad2329c1dd63b76b1bdfa2`. Fresh verifier same-session rechecks are pending.
- 2026-08-12: Qwen session `019ff263-0be7-7000-a840-05fc158df23f` and Grok session `0f7edd46-b967-48d4-98e9-e803c92e5f88` both returned READY on post-repair same-session rechecks without fallback. They independently reproduced missing identity/project/revision, SQLite status/working-copy and fabricated-field counterexamples and reran 225 focused, 1,226 full and API-isolation tests.
- 2026-08-12: Codex final verification matches both participants: frozen plan SHA `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`, mapping-file bytes SHA `8ee8ac78b98aa4ed836679f309a2695ca2c10d8dce65dd1fee153a88da1e6806`, 225/1,226/3 tests pass, and protected `main.py`, source-intake and medical-monitoring paths have no Task 1.10 diff. Task 1.10 is accepted as pure/synthetic contracts; no live migration, route mounting or cutover is claimed.
