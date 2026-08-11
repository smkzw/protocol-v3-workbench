# Execution Output:

`P1-G1_FUNCTIONAL_READY`

The additive H0/H1/H3 evidence closes the non-security P0-CORE gap for the explicitly amended functional gate. The original frozen P1-G1 remains incomplete because Task 1.11/security is `USER_EXCLUDED`.

## Boundary And Context Check

- Same-session bounded recheck; no broad exploration or new session.
- Read-only workspace operation; no source, config, tests, or task records modified.
- No full suite, mutator tests, security probes, services, live files, or runtime databases executed.
- Runner-managed report path was not written.
- Parent Codex remains final authority.

## Work Performed

- Reviewed the new P0-CORE closure candidate, frozen plan clauses, immutable protected manifest, hygiene mutator implementation, and permitted mutator-test sections.
- Independently verified the frozen plan hash and protected-manifest hash.
- Independently parsed the protected manifest summary and inventory binding.
- Executed only the built-in occupancy checker against the exact authorized target set `[]`.
- Confirmed the zero-authorized-target H3 interpretation against the mutator’s eligibility, PATH_MAP, apply, and restore contracts.
- Preserved the first-pass P1 functional evidence unchanged: 798 focused non-security tests passed.

## Artifacts And Evidence

| Area | Disposition | Evidence |
|---|---|---|
| H0 inventory/occupancy | PASS | Candidate record `runs/MW_PROTOCOL_V3_P0_CORE_FUNCTIONAL_CLOSURE_CANDIDATE_20260812.md:15-22`; inventory SHA/fingerprint binding at `:9-12`. |
| H1 protected authority | PASS | Candidate `:24-29`; manifest summary `tests/fixtures/protocol_v3/immutable_protected_assets.json:443504-443548`. |
| H3 recoverable hygiene | PASS | Candidate `:39-44`; actual authorized/move/delete sets are empty; temporary recovery evidence is contract-scoped. |
| H2/H4/H5/H6 and permanent corpus | PASS/unchanged | Candidate `:31-37`; prior accepted evidence remains unchanged. |
| P1 non-security predicates | PASS/unchanged | Prior focused functional run: `798 passed`. |
| Task 1.11/security | USER_EXCLUDED | Never treated as PASS. |
| Original frozen P1-G1 | Not literally passable | Security predicate remains excluded. |
| Amended P1-G1_FUNCTIONAL | READY | All non-security predicates are now grounded. |

Protected manifest independently reports:

- 5,992 assets
- ownerless: 0
- unresolved: 0
- unknown current path: 0
- symlink escape: 0
- explicit stale-missing allowlist: 12

## Commands And Observations

- Hash and manifest verification:

  - Frozen plan SHA: `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`
  - Protected manifest SHA: `f4b385d444d4cf922f20b9934e87f6b72c0ad932fc767b5c86045b7e8c0ace7f`
  - Embedded inventory SHA: `29321ad4595dd5093e1477449568ce93b3ffe9fb52dc6a0483db4404fbfd6621`
  - Embedded inventory fingerprint: `38b7684664274949a1f53598d9fa420e2858e304d9df05a2a3e4ac901045339e`

- Direct occupancy check:

  - Declared hygiene ports: `(8910, 8911, 5173, 5174)`
  - Target set: `[]`
  - Result: `occupancy_blockers=[]`

- Mutator contract observations:

  - Eligibility computation is read-only at `scripts/qc/protocol_v3/apply_repository_hygiene.py:656-716`.
  - PATH_MAP and eligible-set equality is enforced at `:912-917`.
  - Occupancy is checked before apply at `:1193-1245` and `:1406-1411`.
  - Temporary restore/no-write/replay/idempotency/round-trip tests are located at `tests/protocol_v3/test_repository_hygiene_mutator.py:883-898,1793-1811,1887-1900,1985-2008,2097-2114`.

## Blockers Or Missing Environment

No material blocker remains for the amended non-security functional gate.

Residual limits:

- Task 1.11/security remains excluded; therefore the original frozen P1-G1 cannot be declared fully passed.
- No live hygiene move, cleanup, migration, product storage activation, or release readiness is implied.
- The external immutable inventory bytes were not reopened because the permitted read set excluded that path; its SHA/fingerprint binding was independently verified through the protected manifest.
- The candidate’s historical “1,226 full tests passed” statement was not reused as current full-suite evidence. The prior focused result of 798 non-security tests remains the operative P1 anchor.

## Rerun Requests Or Next Step

No H0/H1/H3 rerun is requested. Parent Codex may accept `P1-G1_FUNCTIONAL_READY` for the explicitly amended non-security gate and proceed only within the repository/PoC boundary.

Keep the original frozen gate, production activation, live migration, security acceptance, and release readiness separately blocked.
