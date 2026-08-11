# Codex Review: mw_protocol_v3_p1g1_functional_gate_20260812

Date: 2026-08-12
Delegated-agent output: `runs/codex-subagent_mw_protocol_v3_p1g1_functional_gate_20260812.md`

## Verdict

`P1-G1_FUNCTIONAL_READY`. All non-security P1-G1 predicates are grounded. Task 1.11 is explicitly `USER_EXCLUDED`, never PASS; therefore the original frozen P1-G1 remains incomplete. Phase 2 may proceed only inside the repository/PoC boundary.

## Boundary Check

- Native Luna probe was explicitly unavailable; CLI compatibility route kept exact `gpt-5.6-luna:max` and session `019ff2a4-2a79-7921-9d01-6c0ef07273f1`.
- Hermes was not a declared route and was not invoked.
- Both verifier passes stayed read-only. No source/config/test changes, services, live databases or Task 1.11/security tests.
- No medical-monitoring path changed.

## Codex Verification

- Codex Task 1.10 anchor: 225 focused, 1,226 Protocol v3 and 3 API-isolation tests pass.
- P1 functional focused verifier anchor: 798 non-security tests pass; mapping has 7 families / 20 types / 0 issues.
- P0-CORE positive drift checks: 35/35 pass. Temporary functional restore rehearsal: 6/6 pass.
- Immutable inventory: 51,035 entries, unknown owners 0, mutation eligible/authorized targets 0; exact inventory SHA/fingerprint bound by protected manifest.
- Occupancy check over exact authorized target set `[]`: zero blockers on declared ports.
- Protected manifest: 5,992 assets, ownerless/unresolved/unknown-current/symlink-escape all zero; 12 stale-missing entries are explicit frozen allowlist.
- P0-WORD remains technical PASS_WITH_RESIDUALS; no release claim.

## Delegated-Agent Output Review

Luna first returned NOT_READY for missing H0/H1/H3 aggregate evidence. Codex reproduced the gap, created a hash-bound additive record without rewriting immutable inventory or moving live files, then resumed the same Luna session. Round 2 accepted the zero-target occupancy/H3 interpretation and returned READY. Codex accepts that reasoning because no mutation target exists and the frozen mutator contract makes occupancy a pre-apply target check.

## Residual Risk

- Original frozen P1-G1 is not fully passed because security is excluded.
- Product SQLite remains intentionally not ready; Phase 2 uses typed ports/deterministic fakes.
- No live hygiene move, live migration, route mounting, production activation or release is authorized.
