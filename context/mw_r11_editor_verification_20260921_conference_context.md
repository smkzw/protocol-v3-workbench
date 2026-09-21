# Fresh implementation review contract
Owner: current Codex. One independent read-only reviewer. Review current uncommitted frontend work against original requirements, not the owner's conclusions. The reviewed frontend files are frozen during this pass; an unrelated backend recovery worker may edit agent3/graph/runtime/manuscript_drafts.py.

## User requirement
Senior medical writer, low technical familiarity, visually sensitive: use wide screens with parallel context and real document, reduce excessive spacing and redundant AI text, use short logical bullets, avoid competing simplified editors, saved/downloaded document must be the actual edited document. AI suggestions remain distinct from confirmed medical facts. Working drafts can contain explicit noncritical gaps. No new general security engineering requested.

## Read set
- reviews/protocol-v3-requirements-v2/REQUIREMENTS_AMENDMENT.md
- reviews/protocol-v3-requirements-v2/ACCEPTANCE.md
- frontend/src/features/medical-writing/protocol-workbench/ProtocolWritingDesk.jsx
- ProtocolIntakeWorkspace.jsx/.css and StudyContextWorkspace.jsx in the same directory
- ManuscriptWorkspace.jsx/.css in the same directory
- office/GenOfficeFrame.jsx/.css and its test in the same directory
- frontend/public/genoffice/bridge-shim.js and embedded.css and index.html
- office/bridge-shim.test.mjs
- frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs
- services/api/app/protocol_workflow/application/manuscript_documents.py (read only)
- services/api/app/protocol_workflow/api/manuscript_drafts.py (read only; concurrent worker may touch nonOffice paths)

## Scope
Inspect full affected definitions and adjacent consumers. Identify real regression, version/source mismatch, reopen/save/download behavior, loss of existing edits, missing required user actions, layout shortcomings. Check loading/error behavior and bridge payloads. Review frontend current diff only; do not review unrelated dirty runtime files or backend worker output. Refer to exact file/line and explain concrete trigger/consequence. Distinguish source proof from hypotheses. Do not count test totals as product acceptance. No need to repeat speculative generic risks.

## Boundaries
No writes; runner persists final report. Do not start services, models, browser, network, tests, git mutations, child agents. Shell/read/search allowed only read-only. Do not read runtime databases, ai_provider_settings, credentials, home configuration, or original handoff containing secrets. No final user acceptance. Return PASS/FAIL/UNVERIFIED per critical criterion and smallest coherent repairs. If a concern requires a user choice, explain why existing requirements cannot decide it; routine engineering choices belong to owner.
