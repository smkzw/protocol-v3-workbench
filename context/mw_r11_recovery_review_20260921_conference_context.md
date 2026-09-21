# Independent read-only recovery review
Owner Codex; fresh reviewer, not executor. SOURCE_HEAD 24c1ed1 + current uncommitted sources. Recovery worker has terminated; recovery files frozen during this review. Other owner edits outside this scope may continue.

Read reviews/protocol-v3-requirements-v2/REQUIREMENTS_AMENDMENT.md and ACCEPTANCE.md, then full affected definitions and adjacent consumers:
- services/api/app/protocol_workflow/agent3/{coordinator,manuscript_coordinator,subgraph,product_factory,manuscript_request}.py
- services/api/app/protocol_workflow/{graph/runtime,runtime/proposal_correction,runtime/reservations}.py
- services/api/app/protocol_workflow/api/manuscript_drafts.py (resume/recover paths)
- frontend/src/features/medical-writing/protocol-workbench/{ManuscriptWorkspace.jsx,protocolWorkspaceApi.mjs}
- tests/protocol_v3/{test_manuscript_recovery,test_chapter_product_factory,test_graph_runtime}.py

Criteria: explicit resume must continue unfinished siblings despite one non-retryable or live-unknown child; completed chapters never rerun. Read/recover stays read-only. Unknown live work never automatically redispatched. Explicit retries preserve identity, bounded attempts, old-run compatibility without silently rewriting history or accepting unrelated graph changes. Correction deduplication must preserve real input contracts, scientific facts, citations, schema reconstruction and provider/model lineage. API must schedule actual continuation, frontend must call it after reconciliation; mere refresh is not progress. Identify exhausted retry handling and whether an apparent running status spins forever with no active work. Inspect concurrency where code proves a problem, not hypothetical generic security.

No writes, models, network, services, browser, tests, subprocess agents, git mutations or cleanup. Read/search and read-only shell permitted. Never read credential/runtime configuration, DBs or handoff secrets. Do not read executor report/private reasoning. No final product acceptance. Return concise PASS/FAIL/UNVERIFIED for criteria, actionable findings with exact file/line and concrete trigger, minimal repair and missing decisive test. Note denied tools honestly. Owner retains scientific/UI acceptance.
