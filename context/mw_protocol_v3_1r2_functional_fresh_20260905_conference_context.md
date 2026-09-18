# Conference Context: mw_protocol_v3_1r2_functional_fresh_20260905

Created: 2026-09-05 17:39:21 CST
Objective: 独立审阅 Protocol v3 Task1R.2 当前真实 main 挂载、默认关闭兼容、SQLite持久项目开关与迁移；依据原始需求和源码验证，不依据执行者结论。用户已批准阶段断言升版并排除安全专项工程测试。仅功能审阅，不写产品，不调用产品模型，不启动服务或碰live。具体范围和证据见本会商context。
Task type: `stage_review_plan`
Risk: `high`
Conference mode: `parallel`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`general_single_object`) with no sub-venue chair. Its effective `CST` route chain is `xai/grok-4.6:high -> cursor/default -> cms-router/cms-model:high -> openai-codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_protocol_v3_1r2_mount_20260905`
- Execution evidence status: `linked`
- Excluded provider/model nodes: `opencode-go/muse-spark-1.3-contributor`
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Read .trellis/tasks/09-05-protocol-v3-1r2/prd.md and design.md for original task requirements; plans/mw_protocol_v3_review_amendment_20260905.md for approved supersession only, not earlier review conclusions.
- Current code: services/api/app/main.py (mount wiring and legacy startup), services/api/app/protocol_workflow/api/composition.py, api/router.py, storage/sqlite.py and storage/selected.py; follow relevant application/ports callers as needed.
- Tests: tests/protocol_v3/test_protocol_v3_1r2_mount.py, test_protocol_v3_api_contract.py, test_sqlite_product_storage.py and test_repository_backends.py.
- Do not read worker reports or previous reviewer findings. Discover independently from requirements, current code and tests. No external project paths are authorized for this review.
- Do not add production paths unless the user explicitly authorized reading them for this task.

## Scope

- In scope: functional correctness of actual-main wiring, default-off compatibility, persisted project selection, v1-to-v2 migration preserving existing content, route-scoped error behavior, real successful HTTP use, restart and lazy initialization. Identify weak evidence and actual reproducible defects with file/line and proposed minimal repair.
- User explicitly approves obsolete no-main-mount and schema-fixed-v1 assertions being upgraded. Security-specialist engineering/tests/gates are excluded, not failed or passed; do not recommend adding that program. Scientific/data/function correctness remains required. Task1R.3 backup/replay and1R.4 simplification are future scope, not missing1R.2 features.
- Out of scope: source edits, new security tests, credentials, any live/monitoring runtime changes, services, network/model/OCR/translation/Word calls, installing dependencies, cleanup or task closure. Do not run full repository tests: main owner is separately inspecting their runtime dependencies.
- Allowed verification: existing focused mount suite only, in isolated venv and credential-free child environment. Command: env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=services/api:packages:. WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_protocol_v3_1r2_mount.py -q -p no:cacheprovider
- Temporary test-owned files are allowed by the existing suite. No sibling report files or manual modifications; runner writes final report. Return PASS/NOT_READY recommendation scoped to1R.2, independent checks performed, concrete findings, and unverified criteria. This review cannot substitute full-repository output or final Codex acceptance.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No production path is read or modified; Codex retains final acceptance.

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

- 2026-09-05 17:39:21 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
