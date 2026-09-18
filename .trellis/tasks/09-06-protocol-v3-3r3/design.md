# Design

Use the accepted nested ChapterContractV2 JSON directly. Add only a small local
registry loader/linter and typed fixture/skill I/O models, reusing existing enums
and immutable Pydantic conventions. No second workflow engine or database.

Separate infrastructure from per-leaf clinical authorship: first implement the
loader/linter and representative test data under tests/runs; then author the eight
ordered batches into candidate chapter_contracts, chapter_skills and fixtures.
The loader must never turn an incomplete batch into full-coverage acceptance.

Schema validation proves shape and positivity, not scientific truth. Fixture
validation must inspect actual provided facts/claims/evidence/objects rather than
trust a supplied `passed=true`. Where semantic judgment remains necessary, retain
the explicit obligation for later product QC; do not claim it has been evaluated.

Use a shared typed skill I/O schema with dedicated per-node identities and prompt
requirements. Avoid110duplicate Python classes or110independent model platforms.
OOXML IDs remain exact; names and IDs are separate. Metadata/control provenance
is project/template/document provenance, not invented medical evidence. Reusable
contracts cannot contain invented project approval receipts.

Source preparation: reviews/mw_protocol_v3_3r3_source_preparation_20260906.md and
reviews/mw_protocol_v3_3r1_codex_source_checks_20260906.md; accepted mapping retains
source owner/carrier distinctions and partial obligations that need expansion.
