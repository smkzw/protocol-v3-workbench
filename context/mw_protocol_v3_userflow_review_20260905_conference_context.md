# Conference Context: mw_protocol_v3_userflow_review_20260905

Created: 2026-09-05 14:26:42 CST
Objective: 只读交叉审阅医学写作用户主线的实际前后端接线、恢复与确认语义，给出可复现缺陷及Phase5R/6R/7R建议；不运行服务、浏览器、产品模型，不修改源码；与Task1R.1存储修复分离。
Task type: `code_open_audit`
Risk: `high`
Conference mode: `parallel`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`general_single_object`) with no sub-venue chair. Its effective `CST` route chain is `zcode/glm-5.3:max -> opencode-go/muse-spark-1.3-contributor:xhigh -> codebuddy-cli/deepseek-v4-flash:max -> openai-codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_protocol_v3_userflow_review_20260905`
- Execution evidence status: `no linked execution packet`
- Excluded provider/model nodes: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. Agent adapters are ignored for this check; provider boundaries and model identity are retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Read fully ../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md and plans/mw_protocol_v3_review_amendment_20260905.md. Read frontend/src/App.jsx WritingPage and medical-writing components/hooks, actual services/api/app medical_writing_* callers and relevant tests to trace user flow. Discover exact filenames with rg, no guessed paths. The full baseline review is reviews/mw_protocol_v3_engineering_review_20260905.md; use as hypotheses to challenge, not truth. No worker reasoning logs needed.
- Read-only code and synthetic tests, not real clinical documents/patient data. External plan-upgrade document above is authorized read-only. No LIVE, monitoring runtime, credentials, home sessions or SOP reads needed. Do not inspect active storage worker's four files; Task1R.1 repair is a separate ownership stream.

## Scope

- In scope: trace file-first creation → AI recommendation/preselection → high-risk confirmation → full draft/adoption → edit/recovery → export. Inspect frontend/backend identity, stale state and error/partial-success behavior, clinical content QC gates and unnecessary user burden. Give at most8 prioritized concrete findings with exact file:line, reproduction/uncertainty and minimum scoped solution; distinguish v3 requirement from current legacy behavior. Challenge the current proposed≤15click≤3text path including eight applicable high-risk cards. Default preselection must not mean confirmed. At least one deterministic actual-code check, using existing test fakes or Node callbacks, should ground material findings. Do not mistake pure helper tests for actual hook wiring, or byte/pagination checks for native Word acceptance.
- Out of scope: source/test/plan edits, dependency installs, git writes, service/browser/Word/model/OCR/translation runs, full-repo tests/importing main, network, cleanup and delegation. Existing tests must be read for side effects before running; Python interpreter runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python (or /opt/homebrew/bin/python3.12), Node from current PATH. Test DBs only own temp dirs. Optional new reproduction code/evidence ONLY runs/mw_protocol_v3_userflow_review_20260905/, manual edits via apply_patch. Do not write runner report file; return complete final report. No final visual/clinical/product acceptance. Preserve all history.

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

- 2026-09-05 14:26:42 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
