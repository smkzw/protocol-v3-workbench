# Conference Context: mw_protocol_v3_wp6_final_review_20260923

Created: 2026-09-23 03:05:38 CST
Objective: 对冻结提交e8966d5及WP6真实证据做独立只读工程与医学接受复核；判断A/V/B验收结论、工作稿医学边界、Office/Word所有权、模型fallback和重复采用修复是否有P0-P4问题，不修改源码。
Task type: `complex_delivery_conference`
Risk: `high`
Conference mode: `serial`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

- Ordinary tasks remain Codex-direct. Chinese labels or Chinese sentence work uses its declared execution route and does not start a conference.
  - This packet uses one Codex-led conference object (`general_single_object`) with no sub-venue chair. Its effective `CST` route chain is `zcode/zcode/glm-5.3-flash:max -> codebuddy/codebuddy-cli/deepseek-v4.1-flash:max -> codex-subagent/codex/gpt-5.6-sol:medium`; the packet branch is recorded at creation and filtered against the actual execution route nodes recorded below. Before a new session, the runner rechecks the Beijing period; an already-started session is never rerouted.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Execution-Conference Model Deduplication

- Linked execution task: `mw_protocol_v3_wp6_final_review_20260923`
- Execution evidence status: `no linked execution packet`
- Excluded route identities: none
- If an execution packet exists but runner evidence is missing or unreadable, initialization fails closed. The complete agent/provider/model boundary is retained, and effort differences do not bypass deduplication.

## Source Of Truth

- Frozen source: Git commit `e8966d5`. Inspect `git show e8966d5`, and only the affected source/tests needed to evaluate it.
- Product contract: `plans/protocol_v3_0922V2_execution/00_START_HERE.md`, `07_ACCEPTANCE.md`, `GOAL_PROMPT.txt`.
- Current product evidence (read-only; never read secret/config runtime files):
  - `runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/http_acceptance_results.json`
  - `runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/office_citation_roundtrip_results.json`
  - `runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/native_word_roundtrip_result.json`
  - `runs/requirements_v2_20260919/wp6_0922v2_20260922/ego_v03_v08/v03_width_metrics.json`
  - `runs/requirements_v2_20260919/wp6_0922v2_20260922/ego_v03_v08/study_c_candidate_r2_acceptance.json`
  - `runs/requirements_v2_20260919/wp6_0922v2_20260922/ego_v03_v08/study_c_office_roundtrip_acceptance.json`
  - `runs/requirements_v2_20260919/wp6_0922v2_20260922/study_a_v10_route_receipt_reconciliation.json`
  - `runs/requirements_v2_20260919/wp6_0922v2_20260922/study_b_route_acceptance.json`
  - `runs/requirements_v2_20260919/wp6_0922v2_20260922/study_c_route_acceptance.json`
- Test result supplied by Codex: backend `2608 passed, 1 warning`; frontend `111 Vitest + 66 Node passed`; production build `1971 modules`.
- Product default is local MTPLX `Youssofal--Qwen3.8-Flash-Next-MTPLX-Optimized-Speed / medium`; fallbacks are OpenCode Go DeepSeek v4.1 Flash/max then CMS Router DeepSeek latest cloud/max. Local MTPLX was unavailable during real generation, so its generation quality is unverified.

## Scope

- In scope: challenge source correctness, current-document ownership, duplicate candidate adoption, frontend semantics, routing/fallback receipts, Word evidence, and whether A/V/B outcomes can honestly be PASS/PARTIAL/NOT_RUN.
- In scope: perform a chapter-level medical plausibility sample from the Study C candidate DOCX if tooling permits, and identify specific unsafe or misleading claims.
- Out of scope: modify any source, test, product database, runtime artifact, or Word document; expose credentials; call product models; start or stop services; claim formal submission readiness.

## Success Criteria

- Each selected primary route returns an auditable output or an explicit health/fallback reason.
- The prompt uses the correct Agent identity, provider/model, effort, tools-enabled policy, and same-session continuation policy.
- The runner records session, usage/tool observations, fallback decisions, and failure reasons without `--max-turns 1`.
- No production path is read or modified; Codex retains final acceptance.
- Findings use P0-P4 severity, exact file/evidence references, and distinguish deterministic evidence from inference.
- Explicitly state whether the candidate is only an editable working draft and whether any missing evidence prevents final Protocol v3 completion.

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

- 2026-09-23 03:05:38 CST: Conference initialized by `hermes_workflow_guard.py init-conference`.
