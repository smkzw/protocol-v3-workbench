# Conference Context: mw_r11_editor_review_20260921

Created: 2026-09-21 09:05:53 CST
Objective: 独立审阅宽屏信息密度、AI提示层级与GenOffice真实文档编辑链，给出源码定位和最小完整修复建议，不修改产品
Task type: `C03`
Risk: `high`
Conference mode: `serial`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`evidence_single_object`) with no sub-venue chair. Its effective `CST` route chain is `codebuddy/codebuddy-cli/deepseek-v4.1-flash:max -> zcode/zcode/glm-5.3-flash:max -> grok/grok-build/grok-4.6:high -> pi/cursor/cursor-grok-4.6:high -> pi/openai-codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_r11_editor_review_20260921`
- Execution evidence status: `no linked execution packet`
- Excluded route identities: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. The complete agent/provider/model boundary is retained, and effort differences do not bypass deduplication.

## Source Of Truth

- User 2026-09-21: 宽屏仍单流、文字/卡片/行距过大、信息密度低；AI冗余提示未逻辑分点；编辑区格式脱离真实文档且编辑器简陋，要求一并审阅。
- Current SOURCE_HEAD=24c1ed1. Read requirements-v2/REQUIREMENTS_AMENDMENT.md and CODE_REVIEW.md under reviews, frontend/AGENTS.md (latest explicit user feedback supersedes stale pause), and frontend/src/features/medical-writing/protocol-workbench/ManuscriptWorkspace.jsx, office/GenOfficeFrame.jsx/css plus actual referenced renderer sources under scripts/qc/protocol_v3 and frontend/public/genoffice as needed.
- Read surrounding layout/CSS and semantic preview/editor, office snapshot APIs/storage. Runtime fixtures/databases and credential files excluded.
- Owner separately repairing synopsis StrictMode mount and a worker owns backend recovery: do not review transient edits there as final source. Editor source remains frozen until this report returns.
- Do not add production paths unless the user explicitly authorized reading them for this task.

## Scope

- In scope: READ ONLY source review of real editor integration and desktop layout. Establish whether GenOffice is actual full fidelity renderer or simplified facade. Trace current doc source, save, reload, download, semantic editor competing body, styles/numbering/headers/tables support. Identify exact P0/P1 findings with file:line; propose minimum complete technical path and desktop split layout, concise bullets by action/reason/outcome. Assess fixes against R1–R5, not old zero-gap draft assumption. No code edits, no tests/services, no browser use, no network, no credentials, no git writes or cleanup. Return report via final response only.
- Out of scope: claiming browser/Word acceptance or performing repairs; owner retains actual ego visual validation. No new chair, no recursive delegation.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No production path is read or modified; Codex retains final acceptance.

## Conference Pass Rule

This packet uses one serial Codex-led conference object. Each declared role receives one complete prompt and may use multiple internal tool turns. Codex decides whether a same-session follow-up is needed after reviewing the result; follow-ups do not create a new conference or change the route identity.

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

- 2026-09-21 09:05:53 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
