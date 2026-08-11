Continue in the exact same Codex Luna CLI session. This is a bounded recheck of the H0/H1/H3 gap you identified, not a new assignment. Read and comply with workspace `AGENTS.md`.

Hard boundaries:
- Work only inside the current workspace root (`.`), read-only.
- Do not modify source, config, tests or task records.
- Do not run Task 1.11, security tests/scans, symlink/path/SSRF/secret/adversarial probes, services or live/runtime databases.
- Do not rerun the full suite. Use the new record and only the smallest read-only checks needed to falsify it.
- Runner-managed output path: `runs/codex-subagent_mw_protocol_v3_p1g1_functional_gate_20260812_round2.md`. Do not write it with tools; return the complete report.

Read these files only:
- `context/mw_protocol_v3_p1g1_functional_gate_20260812_context.md`
- `runs/MW_PROTOCOL_V3_P0_CORE_FUNCTIONAL_CLOSURE_CANDIDATE_20260812.md`
- `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`
- `tests/fixtures/protocol_v3/immutable_protected_assets.json`
- `scripts/qc/protocol_v3/apply_repository_hygiene.py`
- `tests/protocol_v3/test_repository_hygiene_mutator.py`

New evidence to challenge:
- Immutable inventory: 51,035 entries, unknown owner 0, mutation eligible 0; inventory SHA/fingerprint exactly bound by the protected manifest.
- Pure eligibility against that manifest: authorized target 0, blocked 51,035, skipped 0, no approval field.
- Current built-in occupancy checker on the exact authorized target set `[]`: zero blockers; no declared hygiene-port listener.
- Protected manifest: 5,992 assets, ownerless/unresolved/unknown current/symlink escape all 0; 12 stale-missing paths are explicit frozen allowlist.
- Positive P0-CORE checks 35/35; functional temporary-directory restore rehearsal 6/6.
- Actual Task 0.5 mutation set is empty. The two frozen pnpm quarantine files predate Task 0.5 and are toolchain inputs, not outputs of the hygiene mutator.

Task:
Decide whether this additive, hash-bound occupancy record and zero-authorized-target H3 interpretation closes the non-security P0-CORE gap without rewriting the immutable inventory or fabricating a live move. Apply the frozen predicate literally but recognize that occupancy is a precondition for mutation targets, not a demand to open-check 51,035 files that are prohibited from mutation. If the evidence is insufficient, return `P1-G1_FUNCTIONAL_NOT_READY` and name the smallest additional non-security evidence that can close it without changing product code or moving live files. If sufficient and all other predicates from your first pass remain unchanged, return `P1-G1_FUNCTIONAL_READY`. Never mark Task 1.11 PASS and never claim release readiness.

Output schema:
1. `# Codex SubAgent Recheck: mw_protocol_v3_p1g1_functional_gate_20260812`
2. `## Boundary Check`
3. `## H0 H1 H3 Recheck`
4. `## Gate Matrix Delta`
5. `## Residual Limits`
6. `## Next Action For Parent Codex`

Put the exact verdict `P1-G1_FUNCTIONAL_READY` or `P1-G1_FUNCTIONAL_NOT_READY` as the first line under `## Next Action For Parent Codex`.
