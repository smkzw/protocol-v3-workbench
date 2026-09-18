# Protocol v3 — 3R.1 模板抽取与旧章节映射

## Goal

Approved TP-MA-07 v2 deterministic registry, explicit legacy mapping and projection accounting; source read-only; independent review before current designation.

## Requirements

- Read-only approved TP-MA-07 v2 DOCX, exact SHA018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756.
- Deterministic candidate registry: hierarchy/order/identity, Word styles,
  sections, bookmarks/fields, tables and source locators. Preserve non-heading
  content obligations rather than interpreting 106 heading leaves as all content.
- Explicit two-way legacy mapping; every current legacy leaf accounted for,
  including PhaseI-only leaves outside this II/III template. No silent retirement.
- Legacy counts and projection implementation are observed from source, not
  forced to historical124/110 or about76 assertions.
- Conditional financial disclosure and distributed management responsibility
  declared with rationale; no fabricated project facts or new medical guidance.
- Candidate registry cannot self-designate current before independent review.

## Acceptance Criteria

- [ ] Failure tests before implementation; deterministic repeated output.
- [ ] Fixed sourcehash; unique IDs, no orphan, stable order and locators.
- [ ] Separate style headings/leaves, outlined extras, tables and semantic counts.
- [ ] Every legacy leaf and every new heading leaf has explicit mapping disposition.
- [ ] Legacy projection coverage reconciled from actual code, not a claimed count.
- [ ] No obsolete term in new template body; old mapping identity preserved exactly.
- [ ] Independent source-to-registry review before candidate promotion.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
