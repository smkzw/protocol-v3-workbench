# Evidence Summary: mw_protocol_v3_3r2_contracts_20260906 / worker_01

Task3R.2 explicit versioned chapter-contract v2 extension, red-first, additive over v1.

## Artifacts

- `packages/contracts/workbench_contracts/protocol_v3.py` — one additive v2 section
  before `__all__` plus `__all__` extension. No v1 class body, field, default,
  or validator was modified; the pre-existing uncommitted DependencyBoundModel
  work in this file was preserved untouched.
- `tests/protocol_v3/test_chapter_contract_schema.py` — new, 14 tests, imports via
  the `protocol_v3` submodule path (package `__init__.py` is outside the
  authorized edit set, so v2 names are not yet re-exported at package root).

## V2 schema surface

- `CHAPTER_CONTRACT_V2_SCHEMA_VERSION = "mw_protocol_v3_contract_v2"`.
- Enums: `FactObligation` (required/optional/forbidden), `ClaimObligation`
  (required/allowed/qualified/forbidden), `PatientParticipationStatus`.
- Typed entries: `FactRequirement`, `ClaimRequirement` (qualified claims require
  qualifying conditions), `EvidenceSourceRequirement` (source roles, admission
  types, chapter-admissible locator kinds body/table/figure only, context-window
  flag, quality floor), `StructuralObjectObligation` (kind, minimum occurrences,
  mandatory project-specific specification), `WordFormattingRules` (styles,
  bookmarks, cross references; required∩forbidden styles conflict; non-vacuous),
  `ConditionalApplicabilityRule` (triggering fact paths, condition, rationale,
  non-vacuous when-active obligation sets), `RepairStep` + `DependencyRepairPolicy`
  (declared dependencies, downstream impact, ActorType owner, attempts bounded 1..5,
  unique step ids/sequences), `PositiveQcRule`, `CriticalToQualityItem` (must anchor
  to fact paths or claim types), `PatientParticipationObligation` (ties to existing
  DecisionRecord by id + sha256; AI-prepared reason, NonEmptyText, no max length),
  `RegistryConsistencyObligation` (registry name, eligibility fact paths, rules).
- Containers: `SubstantiveContentContractV2` and `ChapterContractV2`
  (schema_version literal `mw_protocol_v3_contract_v2`; frozen-state discipline as
  v1; cross-checks: repair policy dependencies ⊆ contract dependencies, CtQ QC-rule
  references must resolve, duplicate fact/claim obligations rejected as conflicts,
  forbidden claim cannot be an admission requirement, object-only content requires
  project-specific elements, vacuous content rejected, positive QC mandatory).

## Verification

- v1 fixtures captured BEFORE implementation: `v1_fixtures_before.json`
  (ChapterContract, SubstantiveContentContract, legacy + compact
  SemanticDocumentRevision / ChapterLockSnapshot / NodeExecutionContract:
  model_dump_json, material_sha256, JSON schema).
- Red run: `pytest_red.log` — ImportError (cannot import name 'ChapterContractV2').
- Green run: `pytest_green.log` — 14 passed.
- Focused regression per execution context: `pytest_focused_full.log` — 222 passed
  (test_chapter_contract_schema, test_contract_models, test_semantic_document_reducer,
  test_repository_contract, test_repository_backends).
- v1 fixtures re-captured AFTER implementation: `v1_fixtures_after.json`;
  `diff` against before-file is empty — v1 serialization and material hashes
  byte-identical.

## Notes for Codex

- `runs/.../v1_pin_constants.py.txt` is the scratch used to extract pin literals
  embedded in the test; kept as evidence, not imported by anything.
- Package-root re-export of the v2 names would require editing
  `packages/contracts/workbench_contracts/__init__.py` (outside the authorized
  edit set) — proposed as a follow-up if consumers need root imports.
- Not done (out of scope): runtime/consumer integration, task closure, registry
  or production writes, independent review (Codex-owned).
