# Codex Execution Plan: mw_protocol_v3_full_review_20260912

Objective: READ-ONLY full engineering review and actionable planning input. Do not implement product changes. Read the source-of-truth and delegated work-item boundary below; return concrete evidence-backed findings, not a restatement of prior reports.

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | Backend review: read all product protocol_workflow canonical, storage, events, runtime, graph, application, api, ports, artifacts and agent5 modules and adjacent tests; trace actual main composition. Exclude registries/chapters.py and registries/dependency_graph.py owned by parent review. Identify reachable correctness, persistence, recovery, versioning, integration gaps and useful simplifications. Product sources/tests read-only. No services, product models, OCR, translation, web, credentials, cleanup or recursive agents. Return file:line, concrete trigger, existing test gap and smallest repair; distinguish absence of future features from implemented bugs. Optional isolated pytest only; no existing evidence writes. | `runs/execution/mw_protocol_v3_full_review_20260912/worker_01.md` |
| `worker_02` | Frontend/user-flow review: read current frontend/AGENTS, App.jsx WritingPage actual wiring and all frontend/src/features/medical-writing components/hooks/CSS, protocolWorkspaceApi, corresponding tests and backend medical-writing endpoints only as needed. Trace actual user paths from intake/recommendations/adoption/edit/save/export; verify previous claims and retract unreachable ones. Identify reachable failures and practical AI-led UX/visual changes for senior medical writer (20click/5text/8 risk confirmations). Read-only sources; no servers, browser production, models, credentials, cleanup, nested agents. New diagnostics only in runs/mw_protocol_v3_full_review_20260912/worker_frontend. Return evidence file:line plus precise proposed fixes and test targets. | `runs/execution/mw_protocol_v3_full_review_20260912/worker_02.md` |

## Manager

No execution manager is dispatched for this route; Codex reviews the worker outputs directly.

## Codex Acceptance

Bounded reports returned and source-adjudicated. Owner review: reviews/codex_execution_mw_protocol_v3_full_review_20260912_review.md. Actual tests/probes and coverage/runtime-identity limits are recorded in reviews/mw_protocol_v3_full_review_20260912.md. This closes review input only; product3R.4 and full UI/Word remain unaccepted. No cleanup.
