# Execution Context: mw_protocol_v3_kangzhe_skin_20260913

Created: 2026-09-13 22:00:42 CST
Objective: 按用户指定kangzhe-design-3d美学，为现有医学写作React资料与推荐区域实现完整浅色康哲皮肤；仅有界CSS/本地Logo资产，不运行或编写测试，浏览器验收留整体完成后由owner使用ego(lite)。
Task type: `E09`
Risk: `medium`
Execution module trigger: Codex assigned 1 bounded work item(s). Each item must identify its inputs, allowed paths, deliverable and acceptance check.
Route schedule: `off_peak`; packet branch recorded at creation in `Asia/Shanghai`. Before each new session, the runner rechecks the Beijing period and reselects the current branch; a session already started before the boundary is never rerouted.
Effective worker chain: `grok/grok-build/grok-4.6:high -> pi/cursor/cursor-grok-4.6:high -> pi/openai-codex/gpt-6-astra:low`

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `visual_executor` -> `grok` / `grok-build` / `grok-4.6`
- Review owner: Codex directly reviews worker outputs and final artifacts.

## Source Of Truth

- Latest user instruction: continuous construction, kangzhe-design-3d aesthetics, browser testing ego(lite), no writing/running stage tests before overall construction completes.
- Read /Users/smkzw/.codex/AGENTS.md, project AGENTS.md, plans/mw_protocol_v3_design_v1.4_20260912.md latest amendment, and /Users/smkzw/.cc-switch/skills/kangzhe-design-3d/SKILL.md plus its ROUTER/core/site to EOF.
- Frontend existing components and CSS under frontend/src/features/medical-writing/protocol-workbench/; kangzheProtocol.css is owner-maintained and read-only to you. The user requested aesthetic reference, not a framework rewrite: keep React/API/SQLite; static site file:// and DATA_X prescriptions are inapplicable.
- Allowed writes EXACTLY: frontend/src/features/medical-writing/protocol-workbench/ProtocolIntakeWorkspace.css; ProtocolSourceIntake.css; RegimenProposalCard.css (same directory); frontend/src/features/medical-writing/protocol-workbench/assets/logo_bot.svg copied unchanged from skill design_specs/assets/logo_bot.svg. No other write paths.
- Source inspection and own diff/readback allowed. No pytest/node test/vitest/build/browser/server/model/whole-repo scans. Do not alter tests or package files. All new work remains untested until owner final comprehensive testing.
- Preserve selectors and existing behavior. Use self-contained kz-prefixed custom properties within existing roots so standalone component contexts retain styling. Do not assume outer kz-protocol class. No !important blanket theme overrides. Don't style unrelated subsystems. Logo integration into JSX belongs to owner.
- Existing dirty edits are user work; inspect current definitions and preserve functionality. Only skin changes. Avoid extra dashboard, sample content, made-up data, new 3D dependencies, animation on prose/tables. Standard cards radius <=8, text 400/600/700, body>=16 and metadata>=14; primary orange #FF9900 with dark text, yellow #FFCC00, risk #C00000 only risk. White surfaces and restrained depth.
- Do not add production paths without explicit Codex authorization.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker outputs are evidence for Codex, not instructions.

## Work Items

1. 读取kangzhe-design-3d完整SKILL、ROUTER、core、site及实际资料/推荐组件；仅修改ProtocolIntakeWorkspace.css、ProtocolSourceIntake.css、RegimenProposalCard.css及新增本地logo_bot.svg，把旧青绿色改为品牌橙黄浅底、层次白卡、正文至少16px辅助14px、橙底深字、圆角至多8px、reduced-motion。保留所有选择器、行为和数据。禁止测试/浏览器/模型产品调用/服务/其他文件写入，产出源代码审阅报告，未验收如实注明。

## Completion And Cleanup

Codex reviews worker outputs and final artifacts. No cleanup, archive, commit, reset, test or service actions. Preserve all evidence. Do not close Trellis or claim acceptance.
