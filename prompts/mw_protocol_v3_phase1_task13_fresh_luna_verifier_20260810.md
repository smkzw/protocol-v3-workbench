# Protocol v3 Task 1.3 fresh independent acceptance

You are an independent verifier in a fresh context. Perform a read-only
acceptance of Task 1.3 in the current workspace. Do not rely on worker reasoning
or prior verdicts.

Read:

- `AGENTS.md`
- `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`
  (Task 1.3 and directly governing sections only)
- `context/mw_protocol_v3_phase1_task13_20260810_execution_context.md`
- the actual repository/artifact/UoW ports, in-memory and local adapters, and
  the two Task 1.3 test files

Verify against actual files and deterministic functional evidence:

1. storage-agnostic repository/artifact/UoW ports and application-service-only
   boundary;
2. CAS, append ordering, idempotency, reservation project ownership and UoW
   rollback;
3. content-address replay, revision preservation, deterministic get-by-hash,
   and single-process thread compatibility;
4. local artifact source is visible to Git despite the global artifacts ignore;
5. the immutable implementation-plan SHA-256 is restored to
   `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`;
6. UoW contract wording matches the reference adapter's post-commit inspection
   behavior;
7. tests are substantive and do not pass through over-broad assertions.

Run only necessary functional tests, compilation, hash and diff/status checks.
Do not modify any file. Do not run any security, adversarial, permission, path,
symlink, TOCTOU, malicious-input, destructive-state or penetration tests. Do not
start a service or touch medical-monitoring files.

Return `READY` or `NOT_READY`. List every issue as P0-P4 with exact file/line and
reproducible evidence. State explicitly that this is a confirmatory Task 1.3
acceptance, not either of the future two fresh P0-P4 discovery rounds.
