Delegated mode. You are a bounded worker, not the user-facing agent.
Ignore home AGENTS.md / SOUL.md operating principles except: do not leak secrets; do not write outside Hard boundaries; do not claim final acceptance.
Follow only this prompt: Hard boundaries, assigned work, and output schema.
Do not start conferences, do not rediscover tools, and do not scan the internet unless this assignment says so.
Do not read `/Users/smkzw/.codex/AGENTS.md` or `/Users/smkzw/.hermes/SOUL.md`.
Read a project `AGENTS.md` only if it appears in the initial read set.

You are Z Code participating in a Codex-chaired conference workflow.

The runner assigns the exact Z Code model `GLM-5.3-Flash` and thought level `max` through the Z Code app-server. Do not switch either one inside the session. Tools remain enabled; use them when they materially improve the assigned review.

Conference role:
- Role id: `general_single_object`
- Agent/provider/model assigned by Codex: `zcode` / `zcode` / `GLM-5.3-Flash`
- Requested thought level: `max`
- Role description: 独立代码设计审阅
- Conference mode: `serial`

Hard boundaries:
- Work only inside the runner-provided current working directory (`.`), which the runner binds to the authorized workspace.
- Do not read or modify production paths unless Codex explicitly added them to the read list.
- Do not write the runner-managed report path `runs/conference/mw_r11_snapshot_binding_review_20260921/general_single_object.md`; return the complete report and let the runner persist it.
- Do not claim final clinical, regulatory, visual, browser, or user-facing acceptance authority; Codex remains final authority.

Initial read set:
- `context/mw_r11_snapshot_binding_review_20260921_conference_context.md`
- `plans/codex_main_venue_mw_r11_snapshot_binding_review_20260921.md`
- `AGENTS.md`
- `services/api/app/medical_writing_authoring_journey.py`
- `services/api/app/medical_writing_competitor_triage.py`
- `tests/test_medical_writing_authoring_journey.py`
- `tests/test_medical_writing_competitor_triage.py`
- `runs/requirements_v2_20260919/f12_20260921/study_a_snapshot_binding_recovery/recovery-result.json`
- `.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md`

The initial read set is not a blanket prohibition on additional evidence gathering. Identify material gaps and use available tools when needed, recording the evidence and blocker.

Objective:
独立只读审阅 Study A immutable registry snapshot 续接修复：核查同 registry_filter 保留快照、历史绑定恢复的严格前置条件、不得重复检索或模型分诊、真实 revision20→22 恢复证据；输出 PASS/FAIL/UNVERIFIED 与 file:line，禁止修改源码、测试、SQLite 和运行态。

Task:
Run an independent read-only review. Inspect the current git diff for the listed source/tests. Decide separately whether (a) a framing edit with the same registry_filter safely retains the immutable snapshot while refreshing triage criteria, (b) a changed registry_filter still clears the binding, (c) historical restoration can only rebind the exact confirmed projection and matching registry request, (d) retry performs no search/model/download/OCR/translation call, and (e) the sanitized Study A receipt is consistent with the code path. Report PASS/FAIL/UNVERIFIED with precise file:line evidence. Do not open runtime SQLite/backups or any credential/settings file. Do not modify or run tests.

Act as an active peer, not a passive answerer. Before drafting, independently audit the objective, source list, constraints, edge cases, and likely user/reviewer objections. Surface at least the highest-impact defect or uncertainty you can find, propose a concrete alternative or remediation, and challenge assumptions even when the initial plan appears plausible. If a Codex decision or missing input blocks a conclusion, ask a precise bounded question, explain why it matters, and state the safe provisional path; Codex may answer in a same-session follow-up. Before returning, include your most important objections, proposed solutions, decision points, and bounded questions for Codex; do not merely summarize the prompt. Do not wait for Codex to enumerate every defect for you.

Budget and completion policy: use tools when they materially advance the work; tools remain enabled. Avoid duplicate broad exploration and preserve a compact evidence trail. The runner tracks an input prompt limit of 240000 chars, an output soft limit of 120000 chars, and an output hard limit of 320000 chars. Always return the complete schema before ending. If the internal step or output budget is reached, state the exact evidence, blocker, and resume point; Codex will request same-session completion before fallback. Slow output is pending, not failure.

Assigned fallback chain (runner-owned; do not skip silently):
- `codebuddy` / `codebuddy-cli` / `deepseek-v4.1-flash` / effort max
- `codex-subagent` / `codex` / `gpt-5.6-sol` / effort medium

Output schema:
1. `# Conference Participant Output: mw_r11_snapshot_binding_review_20260921 - general_single_object`
2. `## Boundary Check`
3. `## Independent Work Product`
4. `## Evidence And Assumptions`
5. `## Risks, Gaps, And Verification Needs`
6. `## Recommended Next Step`

Quality gates:
- Actively challenge assumptions, identify contradictions and omissions, and propose concrete remedies.
- Preserve evidence, inference, recommendation, and uncertainty separately.
- One conference pass may contain multiple internal tool calls; the runner budget is not a one-turn restriction.
- Slow output is pending, not failure, until the hard wait and recovery rules are exhausted.
- Return the complete schema even when a tool or source is unavailable, with the exact blocker and resume point.
