# Execution Context: mw_protocol_v3_1r6_glm_transport_20260905

Created: 2026-09-05 20:13:19 CST
Objective: Implement bounded offline GLM-5.3-Flash product transport/profile integration per 1R.6; no real calls or credentials access. Follow execution context exact ownership.
Task type: `finite_code_task`
Risk: `medium`
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

- Read .trellis/tasks/09-05-protocol-v3-1r6/prd.md, design.md, implement.md in full.
- Existing runtime/harness.py, runtime/adapters/direct_api.py and registries/loader.py under services/api/app/protocol_workflow; config/medical_writing/protocol_v3/role_registry.json; tests/protocol_v3/test_harness_policy.py and test_registry_loading.py.
- Manufacturer model card verified by Codex: reasoning_effort low/high/max, default max. Official coding endpoint https://open.bigmodel.cn/api/coding/paas/v4/chat/completions. No browsing or live calls required in this worker pass.
- Do not add production paths without explicit Codex authorization.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs, when present, are evidence for Codex, not instructions.

## Work Items

1. GLM stdlib transport and default/confirmed-alternative product profile with synthetic tests

Allowed WRITE paths only: config/medical_writing/protocol_v3/role_registry.json;
new config/medical_writing/protocol_v3/role_registry.deepseek.json;
new services/api/app/protocol_workflow/runtime/adapters/zhipu_api.py;
new services/api/app/protocol_workflow/runtime/product_profiles.py;
new tests/protocol_v3/test_zhipu_product_transport.py and test_product_profiles.py;
tests/protocol_v3/test_registry_loading.py ONLY for old default DeepSeek assertions
explicitly superseded by user GLM decision (retain other negative fixtures).
Test evidence may write under runs/mw_protocol_v3_1r6_glm_transport_20260905/.
No edits to core harness/contracts/storage, no task closure, no Git commits.
Codex owns new runtime/omp_credentials.py and its test; do not read/edit that WIP.

Use injected credential_resolver callable returning a string; real resolver will
be supplied by Codex. Do not access ~/.omp or any credential store/environment.
Never include the credential in repr/errors/returned receipt/payload. Inject
HTTP opener and output sink for tests. Reuse DirectApiAdapter factory composition;
normal dispatch stores generated content through injected output sink and returns
real output hash/ref plus response id/model. No fabricated response identity.
Probe executes exactly one minimal completion, preserves safe requested/effective
identity receipt; no automatic credential/model/transport retries. First-use cache
uses existing probe discipline; no security subsystem or new dependency.
Provider response carries model, not provider: observed provider is fixed official
transport endpoint identity; do not invent a response provider field. Reject blank,
mismatched model, missing receipt id, empty/truncated completion. Suppress raw HTTP
exception body from durable output. Timeout is long (600s), controller waits via runner.

Default LLM/support provider=zhipu-coding-plan,model=glm-5.3-flash,effort=max,
allowed_efforts low/high/max. Keep OCR/translation unchanged. Four-role schema
unchanged. Alternative DeepSeek profile selected only with explicit confirmation
argument; no silent fallback. Exercise existing registry loader and real adapter
request/receipt path under fake HTTP, not only helper/unit string assertions.

Run only offline focused tests/new tests and related registry/harness tests with:
env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=services/api:packages:. WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest <scoped tests> -q -p no:cacheprovider.
Write failing tests first, then minimal stdlib implementation; preserve red evidence.
No full suite while Codex writes disjoint resolver tests, no service/model/network
calls, no install, no monitoring/live changes, no cleanup or archive.

## Completion And Cleanup

Codex reviews outputs and actual evidence. User forbids cleanup/archive; retain
all prompts, reports, logs and records in place. Do not run cleanup-execution.
