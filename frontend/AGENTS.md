# Prototype Instructions

Run the local server yourself and open the preview in the in-app browser. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Global frontend experience contract:
- Design and acceptance are desktop-first for every subsystem: 项目总看板, 证据调研与方案设计, 入排审核, 医学监查, 数据分析与TFL, 医学写作, 安全信号与PV协同, and 审批中心.
- Preserve desktop information density, full workflow controls, tables, timelines, rich editors, review panels, and clinical-operational context even if mobile layouts become less convenient.
- Mobile is a smoke/degradation target only: it should avoid catastrophic overlap or complete inaccessibility where feasible, but mobile discomfort must not drive removal of desktop functionality.
- Browser QC should treat desktop failures as blocking. Mobile checks can record regressions and obvious breakage, but do not use mobile constraints to simplify or cut desktop features without explicit user approval.

Subject Timeline visual contract:
- Use the existing MG-K10 Subject Timeline reference as the source of truth for the drill-down page.
- The timeline must be visit-axis based, with events positioned below the axis by study day/date.
- Do not render long event text inside timeline lanes. Use compact numbered blocks on the graph, stable lane numbering, hover details, and matching numbered detail rows below.
- Keep the graph dense enough for clinical review: AE, concomitant medication/treatment, medical history, lab/efficacy, and PD/Query events that exist in the subject data should be visible on the main graph.
- Keep investigational-product changes separate from CM. `CM` means non-investigational concomitant medication/treatment only; dose adjustment, study drug pause/restart, and other investigational-product changes belong in a separate `试验药物变更` lane/detail section.
- Desktop should fit the full visit axis inside the content column where feasible; narrow screens may use internal timeline scrolling, but the page body itself must not overflow horizontally.

Patient Profile visual contract:
- Keep top center/subject filtering and a left center-subject grouped navigation tree; do not collapse the page back to a single flat subject list.
- Show every available `efficacy_trends` and `safety_trends` metric as a graphical trend, with point-level values and risk flags visible near the chart.
- Preserve separate sections for basic subject information, efficacy, safety, PD/Query, risk prompts, and source event index.
- Desktop and mobile page body must not overflow horizontally; only dense internal widgets may scroll when the content itself is wider than the viewport.

Module scope and naming contract:
- Do not build or expose standalone subsystems for non-medical lifecycle work such as project startup/activation, EDC or data-collection-system construction, site operations, visit execution, or recruitment operations.
- User-facing subsystem names must be business names only: 证据调研与方案设计, 入排审核, 医学监查, 数据分析与TFL, 医学写作, 安全信号与PV协同.
- Do not render lifecycle numbering in navigation, breadcrumbs, page titles, cards, approval rows, exports, help text, or empty states.

Source Registry boundary:
- Frontend source and bundles must not embed local absolute paths. UI source-candidate cards use opaque candidate ids plus business titles only.
- UI registration flows call `/sources/local-candidate` with `candidate_id` and `module`; raw `file_path` / `root_path` flows are backend/internal only.
- Before code distribution, multi-machine deployment, or public repository push, backend `SOURCE_REGISTRY_CANDIDATES` and `allowed_roots` must be externalized to a private deployment config rather than hardcoded in app source.

File content validation contract:
- Do not present malware or security scanning as an intake workflow. Validate technical readability and whether the file's role, project/study, indication, version, and expected content are consistent with the current task.
- Technical parse failure is blocking. Content warnings or mismatches may be explicitly confirmed for continued use by the senior medical user only after every unresolved check is acknowledged and a substantive reason is recorded.
- Confirmation changes only downstream use status. Keep the original `warning` or `mismatch` visible and separately show `已确认沿用`; never relabel a mismatch as a match.
- A changed file, project context, validator revision, or source revision invalidates prior confirmation. Preserve the original file object so confirmation can be followed by one exact retry of the same intake request.

Medical writing editor contract:
- The desktop writing canvas is the primary surface. Ordinary source-read-only, work-copy, AI-boundary, identity, and audit explanations must not occupy separate persistent vertical bands; expose the necessary state compactly and reserve full warnings for actionable blockers or failures.
- Body content and structured tables must both support full-screen editing. Table-cell and body formatting use the same visible capabilities and must persist through save, reload, restart, and Word export; never ship visual-only formatting controls.
- Keep AI quick actions beside the page title or in a compact title-level tool group, not in a separate row above the document.
- Project literature uses normalized reference entities. Manual and AI paths share the same citations, numeric rendering, generated References section, audit boundary, and Word-export links.

## Protocol v3 user design and build direction (2026-09-13)

Scope: the isolated Protocol v3 medical-writing workbench only; do not alter other subsystems.
- Use the user-named kangzhe-design-3d skill at `/Users/smkzw/.cc-switch/skills/kangzhe-design-3d/SKILL.md` for aesthetics. Adapt core/site visual rules to the existing React/API/SQLite product; do not replace it with a static site. Regulatory-defense high-risk tags remain red and preselected recommendations remain unconfirmed.
- Browser testing uses ego(lite), one reused TaskSpace per goal, after complete construction. This overrides the generic in-app-browser instruction for this scope.
- Current user direction defers writing/running stage tests until the full product is built. Preserve existing tests and evidence. Source inspection and governed execution/conference continue; full runtime, ego visual/interaction and native Word validation remain required later.
- User has requested current-stage review/retrospective and next-stage planning, followed by lossless pause. Read the current Trellis checkpoint and `runs/MW_PROTOCOL_V3_MANUSCRIPT_NO_LOSS_PAUSE_20260913.md`; do not start the next stage without explicit user continuation.

## Protocol v3 desktop feedback (2026-09-21)
User explicitly resumed implementation. Use wide desktop space for task-appropriate parallel panes instead of a tall single stream. Reduce redundant card padding, row spacing and repeated AI explanations while preserving legibility. Present actionable AI information as logically grouped bullets, emphasizing the decision and next action. The primary editor must represent the actual editable document (including its formatting), not a simplified preview presented as Office. Audit persisted/current/exported document identity together. Current requirements-v2 R1–R5 govern working drafts and Office editing.
