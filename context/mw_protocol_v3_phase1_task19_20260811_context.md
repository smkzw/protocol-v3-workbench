# Task Context: mw_protocol_v3_phase1_task19_20260811

Created: 2026-08-11 22:46:57
Objective: 按冻结计划 Task 1.9 建立 storage-neutral application command/query、Agent⑤控制面、异常卡与 Protocol v3 API/client 骨架，证明 Agent⑤不能改临床事实、降级 Gate 或替代 Agent④
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `opencode-go` / `deepseek-v4-flash` / `max`

## Trigger Reason

This task was initialized through the Codex x Hermes complex-task entrypoint because it is expected to involve more than three execution steps, research/writing/report/code/report-visual work, or source-grounded verification.

## Source Of Truth

- Frozen plan `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 1.9, SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`.
- Approved architecture `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md` §§5.1, 5.4, 17.2, 18 and 19.
- Accepted canonical contracts and reducers: `packages/contracts/workbench_contracts/protocol_v3.py`, `services/api/app/protocol_workflow/canonical/`, `events/`, `ports/`, `runtime/` and their existing tests.
- Accepted Task 1.8 commit `ee6fbb8`; `storage/selected.py` is the authoritative storage-selection surface and deliberately reports `not_ready` until a product SQLite adapter is wired. Task 1.9 must accept an injected UoW factory and must not create a silent production Memory fallback.
- Existing finite error catalog `services/api/app/protocol_workflow/errors.py` is the stable machine/audit-to-public-copy boundary. API handlers must not invent arbitrary error codes or expose traces/log labels.
- Existing FastAPI/Pydantic and frontend module conventions in this repository. No new framework, dependency or architecture decision is needed for this bounded task; therefore the fresh external-discovery gate is satisfied by the current approved design and local executable contracts rather than a new network scan.
- Current filesystem and executed tests are final truth. Delegated output is evidence, not authority.

## Scope

- In scope: storage-neutral command/query models; application service as the only canonical mutation boundary; Agent⑤ coordinator, immutable run manifest and exception cards; Protocol v3 request/response schemas and router factory; frontend API client contract; focused negative and positive tests.
- Allowed product/test write paths: `services/api/app/protocol_workflow/application/`; `services/api/app/protocol_workflow/agent5/`; `services/api/app/protocol_workflow/api/`; `frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs`; `tests/protocol_v3/test_application_service.py`; `tests/protocol_v3/test_agent5_authority_boundary.py`; `tests/protocol_v3/test_protocol_v3_api_contract.py`; this task's `context/`, `plans/`, `prompts/`, `runs/`, `reviews/`, `metrics/` and archives.
- Existing shared files are read-only unless Codex identifies a strict compile/integration requirement. In particular, do not edit `services/api/app/main.py`, monitoring routers/services/tests, canonical reducers/contracts, storage adapters/selection, error catalog, legacy medical-writing routes or unrelated frontend modules.
- Out of scope: product SQLite adapter/cutover, Task 1.10+ migration, Task 1.11 security tests, service startup, browser/visual work, live model/OCR/translation, clinical content generation, frontend screen design and release/promotion.

## Success Criteria

- Every mutation command requires and validates `project_id`, `expected_revision`, `idempotency_key`, `actor`, `reason` and an immutable `DecisionRecord`; a path/project mismatch, stale revision or conflicting replay fails closed with a stable typed error.
- The application service is the only component that opens a UoW and invokes canonical reducers/repositories. Canonical mutation, domain event and optional outbox message remain atomic. Exact replays are idempotent; queries are read-only and cause no repository/event/outbox mutation.
- Agent⑤ may create/pin a run manifest, decompose registered work, aggregate progress/Gate summaries and generate user-facing exception cards. It cannot directly edit StudyDefinition facts, create an unowned canonical decision, lower/override a Gate, replace Agent④ verdict, relabel failure as completion or invent a `可提交定稿` state.
- Exception cards separate Chinese-native public copy from audit-only code/object/attempt/owner/recovery metadata; no traceback, backend field, `log`, `门`, `信号` or raw program label appears in the public payload.
- Router prefix is `/api/projects/{project_id}/protocol-workflow`; request/path project isolation, stable public error envelope and OpenAPI schemas are deterministic. Router is tested through a local in-process app/factory without editing or starting the shared `main.py` service.
- Frontend client uses the v3 route and stable business-shaped results, never exposes raw local paths or silently converts an error into success.
- New focused tests pass; full `tests/protocol_v3/` regression and relevant frontend unit/build/static checks pass; plan hash and zero medical-monitoring diff remain true. Fresh verifier owns READY; Codex owns final acceptance and commit.

## Risk Boundaries

- Do not write to production/legacy data or start a service. Use explicit in-memory/fake UoW factories in tests; product storage remains fail-closed.
- Do not modify any medical-monitoring path or the shared `main.py` composition root, because that surface is under parallel development.
- Do not perform security testing. Test only functional project isolation, authority boundaries and stable error behavior required by Task 1.9.
- Do not allow Agent⑤, router or frontend client to mutate canonical facts outside the typed application command boundary or to override deterministic/Agent④ Gate state.
- Do not add dependencies, regenerate unrelated bundles, or redesign UI. Frontend work is a small API client contract, not a visual task.
- Preserve every execution/manager prompt, stdout, rejected/accepted report and session identifier; archive after acceptance rather than delete.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, or malformed probe output must be recorded and followed by one real route attempt. Only a missing executable or explicit invalid/retired/unlisted model may stop before that attempt.

## Loop Log

- 2026-08-11 22:46:57: Task initialized by `tools/hermes_workflow_guard.py init-task`.
- 2026-08-11 22:47 CST: Re-read current global/root/frontend instructions and frozen Task 1.9. Effective night route is `opencode-go/deepseek-v4-flash:max`. No prior Task 1.9 external session exists, so first use requires a route-specific connectivity probe; subsequent repairs must reuse the established session even if route policy changes.
- 2026-08-11 22:48 CST: Solution-discovery decision: the approved design already fixes the application/UoW/FastAPI/Pydantic route and this task introduces no new dependency or framework. A new web landscape scan cannot materially change this bounded implementation; local accepted contracts and adjacent executable patterns are the decisive evidence.
- 2026-08-11 22:49 CST: Frozen three-work-item sequence: (1) command/query/application-service boundary; (2) Agent⑤ manifest/coordinator/exception-card authority; (3) API schemas/router and frontend client. Workers write disjoint files and run serially where contracts depend on earlier work; manager is read-only.
- 2026-08-12 00:31 CST: Worker implementation and targeted same-session repairs complete. Material repairs removed retained Agent⑤ authority, required non-empty source lineage, removed the client-supplied exception-card route, normalized public frontend errors and made OpenAPI user copy Chinese-native.
- 2026-08-12 00:39 CST: Fresh independent contradiction conference initialized. Qwen completed full runtime verification as `READY`. Grok primary exhausted two same-session recovery passes with cancelled tools; declared Cursor fallback was activated.
- 2026-08-12 01:12 CST: Cursor fallback static review found no P0-P4 but Ask mode blocked Shell. The same Cursor session was resumed with Shell enabled and returned `READY` after 115 focused, 1001 full, Node, SHA, storage and isolation checks. No product/test edits occurred in the follow-up.
- 2026-08-12 01:19 CST: Codex independently reran 115 focused and 1001 full tests, compilation, SHA, storage and shared-boundary checks. Task 1.9 accepted; product storage remains deliberately `not_ready` and router remains unmounted.
