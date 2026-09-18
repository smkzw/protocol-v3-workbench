# Execution Context: mw_protocol_v3_1r3_integration_20260905

Created: 2026-09-05 18:05:12 CST
Objective: 实现Protocol v3 Task1R.3真实SQLite与API集成测试，依据当前Trellis PRD/design/implement。仅合成临时数据，不启动服务/模型或修改live；产品缺陷先报告红测，禁止改旧expected。
Task type: `finite_code_task`
Risk: `high`
Execution module trigger: Codex assigned 1 bounded work item(s). Each item must identify its inputs, allowed paths, deliverable and acceptance check.
Route schedule: `peak`; packet branch recorded at creation in `Asia/Shanghai`. Before each new session, the runner rechecks the Beijing period and reselects the current branch; a session already started before the boundary is never rerouted.
Effective worker chain: `opencode-go/muse-spark-1.3-contributor:xhigh -> cursor/default -> openai-codex/gpt-5.6-luna:max`

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. Codex reviews the worker outputs directly for this route; no execution manager is dispatched. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `finite_code_executor` -> `pi` / `opencode-go` / `muse-spark-1.3-contributor`
- Execution manager: none (Codex reviews the worker outputs directly)
- Execution-manager fallback: none

## Source Of Truth

- Read .trellis/tasks/09-05-protocol-v3-1r3/prd.md, design.md and implement.md completely. User-approved sequencing amendment is in plans/mw_protocol_v3_review_amendment_20260905.md;1R.2 functionality verified, whole-repo historical collection debt remains open, not PASS.
- Read services/api/app/protocol_workflow/storage/{selected,sqlite}.py, application/, events/ relevant contracts/replay and API composition/router. Reuse existing test helpers from tests/protocol_v3/test_protocol_v3_1r2_mount.py, test_repository_backends.py, test_sqlite_product_storage.py after inspecting them. Do not import pocs from product.
- Writable ownership only tests/protocol_v3/integration/ and new evidence under runs/mw_protocol_v3_1r3_20260905/. No existing test/fixture edits, no product source edits, no main/monitoring/config/docs edits. Report any product failure with reproducible red test for Codex to fix afterward. Do not write the runner-owned final report using tools.
- Use runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python (restored Python3.12,SQLite3.53.4,fitz/xlrd installed). Test env: env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=services/api:packages:. WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false.
- main imports must use test-owned runtime/AI settings/role settings/eligibility paths like existing actual-main tests. Legacy main starts durable-mw-sweeper at import; no ASGI lifespan/service start. Do not use real credentials or account files. No network, product models/OCR/translation/Word, live, external SOPs or history cleanup.
- Existing API create study definition uses synthetic project IDs; do not add a new project platform. Tests must prove all Plan1R.3 integration requirements including real-process reopen or separate process read, replay canonical hash, actual still-in-WAL backup with SQLite backup API, integrity/semantic/event/project comparison and idempotence.
- First run new tests against existing code honestly; retain failures without changing expected. If coverage is new but implementation already satisfies it, report first-pass green, do not manufacture a red result. Do not invent security-specific tests. Only run new integration + protocol_v3 suite, not full repo (known separate collection defects).
- Do not add production paths without explicit Codex authorization.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs, when present, are evidence for Codex, not instructions.

## Work Items

1. 补真实SQLite事务/重启/回放/WAL一致backup-restore/幂等及实际挂载API集成测试；仅写tests/protocol_v3/integration和新测试证据，具体读集与边界见context。

## Completion And Cleanup

Codex reviews worker outputs and final artifacts. User forbids cleanup/archive: retain all prompts/reports/logs/manifests in place. Worker cannot close the task. No execution manager is declared.
