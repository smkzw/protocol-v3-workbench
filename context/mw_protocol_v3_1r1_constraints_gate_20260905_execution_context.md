# Execution Context: mw_protocol_v3_1r1_constraints_gate_20260905

Created: 2026-09-05 15:01:42 CST
Objective: Task 1R.1约束完整性修复及真实复验；保留原失败包，不改历史回执，不关闭任务。
Task type: `finite_code_task`
Risk: `high`
Execution module trigger: Codex assigned 1 bounded work item(s). Each item must identify its inputs, allowed paths, deliverable and acceptance check.
Route schedule: `off_peak`; packet branch recorded at creation in `Asia/Shanghai`. Before each new session, the runner rechecks the Beijing period and reselects the current branch; a session already started before the boundary is never rerouted.
Effective worker chain: `zcode/glm-5.3-flash:max -> opencode-go/muse-spark-1.3-contributor:xhigh -> mtplx/qwen3.8-flash-next-mtplx-optimized-speed:medium -> openai-codex/gpt-5.6-luna:max`

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. Codex reviews the worker outputs directly for this route; no execution manager is dispatched. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `finite_code_executor` -> `zcode` / `zcode` / `GLM-5.3-Flash`
- Execution manager: none (Codex reviews the worker outputs directly)
- Execution-manager fallback: none

## Source Of Truth

- Current user-approved Plan v2: ../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md; read Task 1R.1 and current plans/mw_protocol_v3_review_amendment_20260905.md. You read the full 481-line Plan in repair_01; this is a bounded correction, not permission to start 1R.2.
- Read current services/api/app/protocol_workflow/storage/sqlite.py and selected.py, tests/protocol_v3/test_repository_backends.py and test_sqlite_product_storage.py, plus runs/mw_protocol_v3_1r1_codex_20260905/test_acceptance_probes.py, test_projection_atomicity_probes.py, test_schema_constraint_probe.py. Related ports/test fixtures may be read as necessary.
- Same known terminal worker session sess_1eefde6c-2f6f-4bf3-9536-355e7e92cab9 resumes. Earlier task mw_protocol_v3_1r1_sqlite_20260905 repair_01 is terminal, not unknown_outcome. Its 1361+101 tests pass, main seven old/projection probes pass, but the new schema-constraint probe fails. Its process audit also fails (follow-up declaration format plus original/follow-up output receipt binding); those historical files are immutable. This packet performs a REAL remaining repair and verification, not retroactive relabeling of that failed pass.
- Do not add production paths without explicit Codex authorization.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs, when present, are evidence for Codex, not instructions.
- Allowed manual edits ONLY services/api/app/protocol_workflow/storage/sqlite.py and additive tests in tests/protocol_v3/test_sqlite_product_storage.py. Existing negative tests and their assertions MUST NOT be weakened, removed, xfailed or skipped. Do not edit selected.py, shared tests, Codex acceptance probes, plans, historical reports or workflow tools.
- ALL manual edits must use apply_patch (terminal executable /Users/smkzw/.codex/tmp/arg0/codex-arg0hCMeRK/apply_patch). Never use native Write/Edit, cat append, shell redirection, or Python file rewriting. Pytest-generated fresh JUnit/log output is permitted only under runs/mw_protocol_v3_1r1_20260905/repair_02/. Do not manually write the runner-owned report.
- No product model/API/service calls, no installs, no live/monitoring/runtime-library/SOP edits, no git staging/commits, no cleanup. No credential access. Test-owned temporary SQLite DBs only.

## Bounded repair and verification

- Current fingerprint verifies table and column NAMES only. A CTAS clone preserves those names and migration row while losing PRIMARY KEY/UNIQUE/NOT NULL/type semantics; factory must reject it without changing its main database bytes.
- Reproduce existing test_schema_constraint_probe.py failure BEFORE editing. Add meaningful targeted constraint regressions before the minimal fix. Preserve migration/version/read-only foreign-file checks and all repair_01 transaction/timezone safeguards.
- Prefer SQLite-native schema metadata (table_info and unique indexes) over a SQL parser or another dependency. Deriving canonical metadata from the known migration DDL in an internal transient reference connection can avoid manually duplicating dozens of constants; this would not authorize accepting a memory-backed PRODUCT factory. Choose the smallest complete implementation, explaining what semantics it verifies.
- Use runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python with PYTHONPATH=services/api. Run all three main probe files (eight tests currently), focused repository/product tests and full tests/protocol_v3. Record exact commands, counts and failures; do not silently change expected values to get green. Explain any legitimately unsupported historical shape instead of accepting it.
- Return compact report, final changed-file SHA256, exact red/green counts, remaining risks and scope deviations. Codex plus an independent reviewer owns acceptance; do not mark 1R.1 done.

## Work Items

1. 修复SQLite产品adapter对同名同列但丢失主键、唯一或非空约束的数据库误接纳，并运行现存反例与回归。

## Completion And Cleanup

Codex reviews worker outputs and final artifacts. User explicitly prohibits cleanup or archival here; preserve all prompts, reports, logs and failed history. Do not run cleanup-execution.
