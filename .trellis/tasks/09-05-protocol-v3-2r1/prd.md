# Protocol v3 — 2R.1 typed facade与真实恢复矩阵

## Goal

Offline typed facade over accepted case contracts and product SQLite; committed reservations, v1_1 contracts, three-case kill/replay/concurrent decisions; independent verification before closure.

## Requirements

- Consume all three accepted graphs without editing their seven historical files.
- New product OrchestratorPort and runtime have no product import of pocs.
- Thin PoC adapter converts accepted graph vocabulary; do not duplicate scheduler.
- Product SQLite, committed reservation factory and compact_dependencies() v1_1
  contracts must be in executed construction/persistence, not unused wrappers.
- Persist/reconstruct from events/results; checkpoint never independently certifies
  completion. Bind project/branch/graph version/material and current input versions.
- Human decision pauses are states in the product, not agent self-approval.
- Offline synthetic calls only; use standard library/existing dependencies.

## Acceptance Criteria

- [ ] Failing tests recorded before implementation.
- [ ] All three real graphs execute through typed services/output schema checks.
- [ ] Each kill-before, kill-after, duplicate resume, concurrent decision path
  tested with actual own-process death/reopen where persistence is claimed.
- [ ] One effective artifact lineage per logical key; unknown never auto-redispatches.
- [ ] Old graph rejected; split event/checkpoint state detected and repaired from
  authoritative event/result data; existing history retained.
- [ ] Reviewer execution identity/context separate from writer in case runtime.
- [ ] Focused tests and existing v3 +75case contracts pass; independent verifier.

## Notes

- No UI/Word/clinical/product release acceptance implied. P1R legacy delta review
  remains a separate task; launch amendment explicitly permits disjoint offline work.
