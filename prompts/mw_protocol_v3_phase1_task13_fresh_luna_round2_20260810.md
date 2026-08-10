# Protocol v3 Task 1.3 independent repair acceptance

You are a fresh, read-only independent verifier. Read `AGENTS.md`, Task 1.3 in
`.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`,
`context/mw_protocol_v3_phase1_task13_20260810_execution_context.md`, and the
actual Task 1.3 source/tests. Also read the prior independent veto at
`reviews/codex_mw_protocol_v3_phase1_task13_fresh_luna_20260810.md`; treat it as
an issue list, not authority.

Verify from current files whether all three prior P1 defects are closed:

1. in-memory and local `read_by_sha256` choose the same order-independent,
   deterministic metadata binding and a reversed-insertion test proves it;
2. reservation identity is keyed by `(project_id, reservation_id)`, so the same
   reservation ID can exist independently in two projects without corrupting
   `get`, logical lookup, transition or rollback;
3. all mutators exposed by one in-memory UoW share a lifecycle guard so
   commit/rollback closes even pre-obtained CAS/event/outbox/inbox/reservation/
   read-model/artifact handles while post-close reads remain inspectable.

Also verify storage-agnostic ports, application-service-only boundary,
content-address revision preservation, local source Git visibility, plan SHA
`fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`,
compilation, formatting/diff status, and substantive tests. The main venue ran
the approved functional set in a writable temp environment with 151 passed;
reproduce what the read-only environment permits and distinguish sandbox temp
limitations from assertion failures.

Do not modify any file. Do not run any security, adversarial, permission, path,
symlink, TOCTOU, malicious-input, destructive-state or penetration test. Do not
start services or touch medical-monitoring files.

Return READY or NOT_READY with every remaining P0-P4 issue and exact evidence.
This is confirmatory Task 1.3 acceptance, not a future fresh P0-P4 discovery
round.
