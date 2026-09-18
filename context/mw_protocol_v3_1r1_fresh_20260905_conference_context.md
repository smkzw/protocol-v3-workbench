# Conference Context: mw_protocol_v3_1r1_fresh_20260905

Created: 2026-09-05 14:06:30 CST
Objective: 独立验收Task1R.1当前产品SQLite adapter与双后端合同；只读检查当前源码与原始合同，运行隔离测试，查找数据一致性与失败关闭缺口。不启动服务或产品模型，不修改源码，不接受worker自行结论。
Task type: `C03`
Risk: `high`
Conference mode: `parallel`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`evidence_single_object`) with no sub-venue chair. Its effective `CST` route chain is `zcode/glm-5.3:max -> xai/grok-4.6:high -> xai/grok-4.6:high -> openai-codex/gpt-6-astra:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_protocol_v3_1r1_sqlite_20260905`
- Execution evidence status: `linked`
- Excluded provider/model nodes: `zcode/glm-5.3-flash`
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Read current ../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md (read-only exception outside cwd) and plans/mw_protocol_v3_review_amendment_20260905.md fully. Task1R.1 only. Original ports/repositories.py and ports/unit_of_work.py under services/api/app/protocol_workflow are contract authority; storage/memory.py is the reference observable behavior. Read actual application/service.py and events/unit_of_work.py callers.
- Review the frozen current four files: services/api/app/protocol_workflow/storage/sqlite.py (SHA256 8eeaa92410adf9b7b79a09856cd3f90e10fa4648ec0e9f30162f0e0cd57cd685), storage/selected.py (803e07fde2b3996acda16099b2cf90a14f52fc8da4c63da184bf3abeccbb93f8), tests/protocol_v3/test_repository_backends.py (01c3f54d1f4357532e760a14516e3e1667d8ef64aab2b0818131adab3bd103d6), tests/protocol_v3/test_sqlite_product_storage.py (411e8fa9911c12fc10cba73016ccd0f6c0c1ca0cc8997cb68e58ca4f6e358c62). Relative storage shorthand expands to services/api/app/protocol_workflow/storage.
- Existing test_repository_contract.py and test_selected_storage_contract.py are immutable test criteria. PoC pocs/protocol_v3/storage/sqlite_adapter.py and decision.md may be read for comparison, never imported into product. Do not read the worker report, worker reasoning/logs or its persuasive evidence_summary; form your own judgment from source, ports and executed checks.

## Scope

- In scope: independent static review and actual offline checks of Task1R.1. Cover all seven repository ports, project-scoped ID/key collisions, CAS/history, event batch failure caught inside a UoW, outbox/inbox transitions, unknown reservation blocking and session lineage, read-model replacement, nested/closed/rollback behavior. Check precise product activation configuration, linked version admission before I/O, schema history/malformed/unknown versions/foreign-file no-write behavior, import purity and no PoC imports. Identify gaps in the new tests as well as code defects; passing counts alone do not dispose findings.
- Out of scope: implementation/repair, main mounting, Phase1R.2+, frontend, actual product calls, OCR/translation/downloads, native Word, live/monitoring, production activation/cutover. No services, agents or external calls. No source/test/fixture/plan edits, no commits/staging/archive/delete. Test-owned temporary DBs and optional additive reproducer evidence under runs/mw_protocol_v3_1r1_fresh_20260905/ are allowed; runner owns its report.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No production path is read or modified; Codex retains final acceptance.
- Use PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api:packages:. /opt/homebrew/bin/python3.12 -m pytest tests/protocol_v3/test_repository_backends.py tests/protocol_v3/test_sqlite_product_storage.py -q -p no:cacheprovider --tb=short; then full tests/protocol_v3 if valid. Do not run whole-repo pytest: legacy main dependency closure/side effects are separate pending work. Do not install dependencies. Runtime SQLite should be inspected, not inferred from old candidate metadata.
- Return recommended READY/NOT_READY for 1R.1 only, priority/file:line/evidence/remedy for each actionable issue, actual command/results, four source hashes, and limitations. Self-authored repairs require a different verifier, so remain read-only. All prior negative fixtures/expected values remain unchanged. No acceptance claim for product/UI/clinical outputs.

## Parallel Work Rule

For logic-heavy, rigor-sensitive, or artifact-heavy tasks, each participant independently runs the whole bounded workflow and writes a separate output. Leads compare after all available participant outputs are in or explicitly marked pending.

## Timeout Policy

- Participant soft wait: 60 minutes.
- Large-task participant wait: 120 minutes.
- Chair hard wait: 120 minutes.
- Failure rule: Do not fail a model for slow response alone; fail only on terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no useful progress after the high-budget same-session recovery loop. A catalog/auth/transport health preflight timeout or malformed response is diagnostic and must still allow one live route attempt; explicit user routes also proceed when the catalog is stale or incomplete, while a genuinely missing CLI or native transport boundary may block. If a resumable session exists after a step/size boundary, continue it before fallback; repeated identical output/tool evidence triggers the no-progress breaker.
- Pass/turn boundary: one conference prompt is one conference pass. The
  `--max-turns` value controls internal Agent tool-calling turns and is never
  set to 1 for substantive conference execution; generated participant and
  chair commands use the route budgets recorded by the guard.

## Risk Boundaries

- External Agents are advisory; Codex remains final authority.
- Codex owns visual/browser/PPT/PDF/rendered checks, live authority checks, final clinical/regulatory conclusions, and production writes.
- Do not mark a slow model failed solely due to latency.

## Loop Log

- 2026-09-05 14:06:30 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
