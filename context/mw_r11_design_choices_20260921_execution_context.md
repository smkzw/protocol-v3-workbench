# Bounded execution contract
Owner Codex; latest user requests full product continuation and compact widescreen clinical writing UI. This is full-product defect repair/verification, not a new stage. Product-model calls forbidden for this assignment. Engineering model invocation is authorized.

Allowed writes ONLY:
- frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.jsx
- frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.test.jsx (new focused component tests)
Do not touch CSS, Office, other frontend modules, backend, databases, AGENTS, historical evidence, external paths, git state, services, or model config. Do not write home plan files or invoke plan-mode tools. Final report runner-owned; return report text. Owner is concurrently editing other files.

Read the current component completely; relevant backend design-elements API/application adoption source and adjacent tests; requirements R1/R3 in reviews/protocol-v3-requirements-v2/REQUIREMENTS_AMENDMENT.md if needed. Do NOT read HANDOFF_ROUND10.md (contains a credential). Current uncommitted component edits by owner are intended: primary endpoint marked critical, confirmed content remains visible, compact basis label. Preserve them.

Findings to reproduce and repair:
1. OptionList renders multiple primary objectives as text, but confirmCard hardcodes primary_objective:0. Expose real radio selection with first default selected (recommendation preselected is NOT clinical confirmation), submit the chosen index, and retain which objective was confirmed. Never call confirmation automatically or claim alternatives all confirmed.
2. confirmCard writes ':intent:<card>' to localStorage but always generates a fresh operation id before reading prior unknown intent. Reconcile the existing exact intent first after uncertain results/remount. Never silently substitute a new choice for an outstanding confirmation; show a concise action/result. Use existing recover/adopt APIs, no new retry engine. Determine how to separate terminal rejection vs unknown outcomes from actual API contracts.
3. Confirmed display currently uses local confirmedCards. Do not display a new proposal's default option as the historical chosen value. Preserve/recover selection if receipt/intent contains it, and explicitly show unknown historical selection if genuinely missing. Avoid new scientific assertions.

Keep changes minimal; no generic security engineering/tests. A targeted component test must prove selecting second objective sends index1; pending original id survives remount and no duplicate adoption; confirmed choice remains visible. Run vitest from frontend with --environment jsdom. No full regression, no browser/server; Codex handles final integration, review and rendered acceptance. Do not use in-memory stubs as proof of real backend success. If backend contract blocks correctness, report exact file/line and stop dependent change, without inventing payload fields.
