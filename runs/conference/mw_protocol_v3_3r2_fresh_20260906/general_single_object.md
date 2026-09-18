# Conference Participant Output: mw_protocol_v3_3r2_fresh_20260906 - general_single_object

## Boundary Check

- Work confined to runner cwd (`.`); all reads (` .trellis/...`, `packages/...`, `tests/...`, `.hermes/plans/...`, `runs/mw_protocol_v3_3r2_contracts_20260906/`) and all executions (allowed pytest command, in-memory counterexample scripts, `cmp`) inside authorized workspace.
- No source files edited; no worker reports / other reviews / production paths read.
- No secrets encountered. No final visual/clinical/regulatory acceptance claimed; verdict below is schema-review input to Codex, not task closure.

## Independent Work Product

**Verdict: REVISE** — one blocking schema defect (forbidden-only content accepted as complete) with exact reproduction and minimal remedy; six advisory observations deferred or exemptable by Codex decision.

### What was audited

Against PRD (`.trellis/tasks/09-06-protocol-v3-3r2/prd.md`), design (`design.md`), original Task3.2 micro-steps (`.hermes/plans/...md:938-952`), I checked the full v2 section of `packages/contracts/workbench_contracts/protocol_v3.py:1177-1546`, v1 bases (`:716-800`, `:185-263`, enums `:314-381`), full `tests/protocol_v3/test_chapter_contract_schema.py` (745 lines), `test_contract_models.py` builders, and `runs/mw_protocol_v3_3r2_contracts_20260906/v1_fixtures_{before,after}.json`.

### Verification results (evidence, all observed)

- **v1 compatibility INTACT:** pin JSON byte-equal + 6/6 material hashes pass; `v1_fixtures_before.json` vs `v1_fixtures_after.json` byte-identical (`cmp` clean); v1 classes contain no v2 fields (test asserts 7 names absent); v2 uses separate `Literal["mw_protocol_v3_contract_v2"]` + frozen + `extra="forbid"` base. Suite: **222 passed** via the exact allowed command (schema + contract-models + reducer + repository ×2).
- **Genuinely strong negative coverage confirmed:** same-path dual-obligation and same-claim dual-obligation rejected; qualified-without-conditions rejected; forbidden-claim-as-admission rejected *within* the content model; vacuous word rules / conflicting styles / vacuous conditional rules / undeclared repair deps / dangling CtQ→QC / empty QC list all rejected; material hash tracks content, ignores `canonical_state` (by `material_metadata_fields` design, `:225-239`).
- **Original Task3.2 element mapping:** required/optional/forbidden facts ✓; required/allowed/qualified/forbidden claims ✓; source roles + admission types + locator/context/quality floor ✓; all six object kinds (paragraph/table/SOA/figure/formula/instrument) in `StructuralObjectKind` ✓; dependency edges + repair owner + bounded attempts (1–5) ✓; Word style/bookmark/xref contract ✓; conditional applicability ✓; CtQ ✓; patient-participation DecisionRecord pin, AI-prepared reason, no max length ✓; registry-consistency eligibility obligations ✓; metadata/control path needs no fabricated medical evidence ✓.

### Blocking defect (HOLE-1): negative-only content validates as complete

- **Location:** `SubstantiveContentContractV2.validate_substantive_obligations_v2`, `protocol_v3.py:1420-1471`. The vacuity gate (`:1451-1459`) uses `any()` over the five obligation groups, so a contract whose fact requirements are *all* `forbidden` and claim requirements are *all* `forbidden` — zero positive obligations, zero evidence, zero objects, zero project elements — validates.
- **Reproduction (observed, in-memory):** `_content_contract_v2(fact_requirements=(FactRequirement("picos.outcome.primary", forbidden, …),), claim_requirements=(ClaimRequirement("marketing_claim", forbidden, …),), evidence_source_requirements=(), structural_object_obligations=(), project_specific_elements=())` → **accepted**, hash `c03af8978760`.
- **Why blocking:** v1's `any()` was safe because every v1 collection was positive (`required_*`/`minimum_*`/project elements). V2 introduced `forbidden`/`optional`/`allowed`, breaking that invariant. A forbidden-only contract is satisfiable by an *empty chapter*, directly violating PRD "No empty/pure-title contracts accepted as complete" and Task3.2 meta-gate ("required fact, required evidence/source role, project-specific object/claim obligation at least one, plus positive QC"). Same hole admits optional-only / allowed-only contracts (nothing checkable), though those at least anchor project-specific paths.
- **Minimal remedy (no v1 touch, ~10 lines + 2 tests):** in `validate_substantive_obligations_v2`, after the existing `any()` check, reject when no *positive* obligation exists — i.e. no fact requirement with obligation ≠ `FORBIDDEN`, no claim requirement with obligation ≠ `FORBIDDEN`, and no evidence/object/project-element entries. Red-first test: forbidden-only payload above must raise `ValidationError` (match e.g. `"positive obligation"`); control/metadata test (`test_v2_metadata_control_content_needs_no_fabricated_medical_evidence`, which carries project elements + structural obligation) must still pass. This preserves conditional-chapter flexibility (optional/allowed still count as anchored) while closing empty-completeness.

### Advisory observations (non-blocking; Codex to exempt or route to 3R.3)

1. **Cross-model contradictions unchecked (confirmed):** content forbidding `picos.risk.pregnancy_contraception` and a chapter `ConditionalApplicabilityRule` requiring the same path when-active both validate independently — no joint lint exists. Same class: CtQ `linked_fact_paths`/`linked_claim_types` are free text with no registry check (dangling anchor `picos.ghost.nonexistent` accepted). *Provisional path:* accept as 3R.2 schema limitation; mandate a cross-contract lint when the 110 registries land in 3.3 (Task3.3/3.4), not a schema change now.
2. **Case-variant style bypass (confirmed):** `required_styles=("Heading 2",)` + `forbidden_styles=("heading 2",)` accepted — conflict check is exact-string. *Remedy if desired:* compare on normalized (casefold + whitespace-collapsed) keys; note OOXML `styleId` is case-sensitive, so normalize for comparison only, never rewrite.
3. **Dependencies without repair policy (confirmed):** `_chapter_contract_v2(dependency_repair_policy=None)` with `dependency_ids=("contract:background:v1",)` validates — including the control-page chapter, whose background dependency looks like builder default leakage. PRD lists "repair owner and bounded attempts" as obligations. *Options:* require policy when `dependency_ids` non-empty, or explicitly exempt template/control provenance chapters.
4. **Object-cell detail demoted to free text:** v1 `required_object_cells` (e.g. `soa:visit:week12`) has no typed v2 counterpart; `StructuralObjectObligation` carries kind + count + free-text spec. Kind-level typing satisfies the Task3.2 micro-step, but SOA row/cell obligations stay uncheckable. *Flag for 3.3:* consider typed cell selectors when authoring the 110 contracts.
5. **Free-text anchors throughout** (`fact_path`, `claim_type`, `admission_claim_types`, `registry_name`, QC `rule`): contradiction/anchor checks rely on exact string equality, so near-duplicates bypass. Consistent with v1 (also free text); acceptable at schema level, but the 3.3 registry lint should canonicalize path vocabularies.
6. **Non-contiguous repair sequences accepted** (`1,3` with no `2`); `max_repair_attempts` upper bound 5 is arbitrary but explicit and tested. Trivia; suggest contiguity check only if repair executor assumes dense ordering.

## Evidence And Assumptions

- **Evidence (observed):** 222-test green run output; `cmp` identical fixtures; six in-memory probes (HOLE-1/HOLE-3/HOLE-5/OBS-8 confirmed; OBS-2/OBS-4/OBS-6/OBS-7 confirmed after correcting one probe bug — initial OBS-7 rejection was `StableId` min-length 3 on my `s1`/`s3` IDs, not a contiguity check; re-probe with valid IDs confirmed acceptance); exact pin JSON and hash constants in `test_chapter_contract_schema.py:50-61`; validator source ranges cited above.
- **Inference:** HOLE-1 is a genuine invariant regression vs v1 (positive-only collections → mixed-obligation collections under an unchanged `any()` gate). Cross-model gaps are architectural (two independent models, no joint validator), not oversights in any single validator.
- **Assumptions (uncertainty, stated):** (a) `optional`/`allowed`-only contracts treated as weak-but-anchored, hence my remedy counts them as positive — Codex may instead require a `required`/evidence anchor per the strict meta-gate wording; (b) PAGE-locator exclusion and formula/instrument-locator absence judged benign on the theory that such evidence cites body/table/figure — no Word-domain confirmation performed (out of scope, Codex owns it).

## Risks, Gaps, And Verification Needs

- **Risk 1 (blocking):** forbidden-only contracts let empty chapters hold "complete" contract pairs (forbidden-only word rules + generic QC text also validate — OBS-8, hash `cf4896ef8503`). Static schema cannot judge QC *specificity*, but it can require *positivity*; without the fix, the 110-contract rollout in 3.3 inherits a vacuity loophole. Needs the HOLE-1 validator + red test before closure.
- **Risk 2:** 3.3 authors 110 free-text-anchored contracts with no cross-lint → dangling CtQ anchors and content/conditional contradictions scale silently. Needs a registry-level lint (anchor resolution + forbidden/required cross-check) as a 3.3 acceptance item.
- **Risk 3:** deps-without-policy chapters (notably the control-page default) leave repair ownership undeclared at scale. Needs Codex ruling: mandatory policy vs documented exemption.
- **Not verified (out of scope per packet):** native Word acceptance of style/bookmark obligations; reducer/repository consumption of v2 types (untouched by design); whether `minimum_quality_score` floors or `require_context_window` semantics match Agent① admission gates.

## Recommended Next Step

- **Bounded questions for Codex:** (Q1) Accept the minimal HOLE-1 remedy (positive-obligation gate counting optional/allowed as positive) or require a strictly `required`/evidence anchor per the Task3.2 meta-gate? (Q2) Mandatory `dependency_repair_policy` when `dependency_ids` non-empty, or approved exemption for template/control provenance chapters? (Q3) Confirm cross-model contradiction lint is routed to 3R.3 registry work, not this schema task.
- **Safe provisional path:** apply HOLE-1 fix as specified (optional/allowed count as positive — least restrictive close of the hole), add the red-first test, re-run the allowed five-file pytest command, and record Q2/Q3 rulings as 3R.3 acceptance inputs. No other schema changes needed for 3R.2.
- **Exact resume point if continued in-session:** edit `validate_substantive_obligations_v2` (`protocol_v3.py:1420-1471`), add tests to `test_chapter_contract_schema.py` near `test_v2_rejects_vacuous_and_generic_object_only_content` (`:503-543`), re-run the allowed command.
