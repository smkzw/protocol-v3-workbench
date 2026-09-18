# Protocol v3 — 3R.2 章节合同v2

## Goal

Extend existing contracts with typed content obligations, applicability, Word rules and patient participation, preserving historical v1 hashes.

## Requirements

- Extend existing ChapterContract/SubstantiveContentContract via explicit v2 types;
  preserve existing v1 serialized bytes, hashes, negative tests and consumers.
- Required/optional/forbidden fact paths; required/allowed/qualified/forbidden
  claims; source roles, admission types and locator/context evidence requirements.
- Typed paragraph/table/SOA/figure/formula/instrument obligations; Word styles,
  bookmarks and references; dependency/impact, repair owner and bounded attempts.
- Conditional applicability and rationale; CtQ items; patient-participation decision
  record (not body chapter); registry-consistency obligations for eligibility.
- Nonvacuity retained: substantive fact/evidence/project-object-or-claim obligation
  plus positive QC. No empty/pure-title contracts accepted as complete.
- No product models/services or new security features. No fabricated clinicalfacts.
- Patient-participation record is approved product traceability, not a claim that
  ICH3.1.3 literally mandates documenting nonparticipation reasons. AI-prepared
  rationale, no arbitrary text length; no additional user-form requirements here.

## Acceptance Criteria

- [ ] Red-first substantive tests, then minimal schema implementation.
- [ ] Existing v1 serialization/material hashes unchanged, old tests intact.
- [ ] Contradictory fact/claim requirements and vacuous content rejected.
- [ ] Typed object/evidence/Word/applicability/dependency obligations roundtrip.
- [ ] No fabrication of medical evidence for metadata/control content.
- [ ] Independent reviewer checks before task closure; no stage pause.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
