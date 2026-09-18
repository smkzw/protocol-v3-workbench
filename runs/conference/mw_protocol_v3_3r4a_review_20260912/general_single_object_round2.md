# Conference Participant Output: mw_protocol_v3_3r4a_review_20260912 - general_single_object

**Round 2 (same-session follow-up).** Read-only. Bash denied in this session — **all verification below is static (Read/Grep/Glob) unless it is an artifact produced by the owner's own executed run, which I am reading, not running.** I did not execute Python, did not run pytest, and do not claim independent runtime execution anywhere in this report. I did not read other worker reports or the owner review.

---

## Boundary Check

**Identity.** CodeBuddy CLI, `deepseek-v4-flash`, acting as the declared runner fallback after the primary node failed before a resumable session. Same session `01a09654-5faa-76e6-b4fa-899fff6d8396`. Role, source list, output schema, and single-pass protocol preserved. I wrote nothing; the runner persists this report.

**Read set for this round.** `runs/mw_protocol_v3_3r4a_20260912/frozen_review_round2/` (all seven listed files: `source_hashes.json`, `packages/contracts/workbench_contracts/protocol_v3.py`, `services/api/app/protocol_workflow/registries/chapters.py`, `.../fact_bindings.py`, `tests/protocol_v3/test_chapter_fact_binding.py`, `config/.../fact_bindings.json`, `.trellis/tasks/09-11-protocol-v3-3r4/prd.md`, `plans/mw_protocol_v3_implementation_plan_v3_20260912.md`); `runs/mw_protocol_v3_3r4a_20260912/review_verification_receipt.json`, `.log`, `.xml`; `.../resolution_registration.json`; `.../all_real_contract_bind_probe.json`; `.../whitespace_fidelity_probe.json`; current `tests/protocol_v3/test_study_definition_reducer.py` (helper only). I did not re-read the owner review or any other participant output.

**Capability limit that still applies.** I could not recompute SHA-256, could not run the 111-contract probe myself, and could not execute the falsifiable reproducers I propose. Everything labeled "confirmed" below is confirmed **by source reading plus the owner's hash-bound artifacts**; everything labeled "assumption" is stated as such.

---

## Independent Work Product

### 0. Correction of my round-1 error (stated first, not buried)

**My round-1 D4 claim was wrong and I withdraw it.** I wrote that `_has_fact_value("false")` treats the string `"false"` as absent. It does not. Round-2 `chapters.py:156-166`:

```
def _has_fact_value(value: JsonValue) -> bool:
    if value is None: return False
    if isinstance(value, str): return bool(value.strip())
    ...
    return True  # Both false and zero are real supplied facts.
```

`"false".strip()` is `"false"`, non-empty, so `bool(...)` is `True`. The owner's executed probe is authoritative and records this explicitly: `all_real_contract_bind_probe.json:6` — `"string_false_has_value": true`. The probe's `nan_output_accepted: "nan"` field likewise records the pre-fix behavior that the new test now converts into a typed error. **My "same semantic value, two different presence verdicts" hazard does not exist.** What remains of D4 is a narrower and correctly scoped point (write-boundary type admission), which the owner has assigned to D/V1 and which I accept as such.

This matters beyond one line: my round-1 D4 secondary hazard was the only claim I presented with "medium-high" confidence that turned out to be simply false. I have re-derived every remaining claim below from the round-2 bytes rather than carrying round-1 conclusions forward.

### 1. Round-2 changes verified against the frozen bytes

**1a. Whitespace preservation — confirmed present and correctly scoped.**

Three coordinated changes, all consistent:

- `StudyDefinitionV3` now declares `model_config = ConfigDict(str_strip_whitespace=False)` with an explicit comment (`protocol_v3.py:647-651`): "Typed fact payloads are exact data, not labels. StableId/NonEmptyText keep their own explicit normalization; inherited JSON text trimming must not rewrite paragraph/table values while reopening a study."
- `ChapterSkillInput` now declares `str_strip_whitespace=False` (`chapters.py:277`).
- `ContentFact` now declares `str_strip_whitespace=False` (`chapters.py:174`).

The scoping claim ("explicit ID/text-label normalization retained") checks out: `StableId` (`protocol_v3.py:40-48`) and `NonEmptyText` (`protocol_v3.py:53`) carry their own `strip_whitespace=True` in `StringConstraints`, so identifiers and labels keep normalizing even under the loosened model config, while `ContentFact.value` (a `JsonValue`) is not a plain `str` field and was never subject to field-level stripping. The new test `test_fact_text_is_not_normalized_by_transport` (`test_chapter_fact_binding.py:243-251`) covers three shapes — bare string, dict-wrapped string, list of strings — and asserts both that the study round-trip preserves the value and that `ContentFact.fact_path` still normalizes (`"  study.objective  "` → `"study.objective"`). That is exactly the right test shape for this change: it pins preservation and normalization in one assertion pair.

The companion artifact `whitespace_fidelity_probe.json` documents the **pre-fix** behavior (`supplied` has `"  first\nsecond  "`, `canonical`/`skill_input`/`output_fact` show `"first\nsecond"`). Read as a pre-fix observation it is useful evidence; it should not be misread as current behavior. Flagging only so nobody cites it later as a live defect.

**1b. Nonfinite output — confirmed fixed, and fixed more broadly than my round-1 note assumed.**

Round-1 `validate_output_facts` built its conflict list in a comprehension, so a `NaN` output value reached `_json(fact.value)` (which passes `allow_nan=False`) and raised a bare `ValueError` instead of the typed error. Round-2 `fact_bindings.py:305-315` wraps the comparison:

```
for fact in output.facts:
    try:
        matches = (fact.fact_path in expected.resolved_facts
                   and _json(fact.value) == _json(expected.resolved_facts[fact.fact_path]))
    except (ValueError, TypeError):
        matches = False
    if not matches: conflicts.append(fact.fact_path)
```

Because `_json` is called on the whole value, this catches non-finite floats **nested inside dicts and lists**, not just at the top level — which a `math.isfinite` guard would have missed. `test_nonfinite_output_is_reported_as_fact_error` (`test_chapter_fact_binding.py:254-262`) pins it. Confirmed by reading; I did not execute it.

**1c. All-real-contract addressing test — confirmed present, and it does more than I expected.**

`test_every_real_contract_reads_confirmed_canonical_values_without_projection_copies` (`test_chapter_fact_binding.py:265-291`):

1. Rebuilds the registry from the on-disk contracts (`assemble_registries` over `chapter_contracts`, `chapter_skills`, and the 8 fixture batches) and loads the shipped catalog with `load_fact_catalog`. So the addressing check runs against the real registry hash, not a fixture registry.
2. Builds the synthetic canonical store from the catalog itself: `{b.canonical_path: (False if b.value_type == "boolean" else {"text": ...}) for b in catalog.bindings if b.canonical_path is not None}` — every canonical target supplied, including the five that appear in no contract.
3. Binds **every** entry in `registry.chapters` with the full catalog and asserts, for every resolved fact, `value == facts[by_path[path].canonical_path]` — i.e. the value that arrived is the value that was placed at the declared canonical address, for every path that resolved.
4. Asserts the negative: with `contact.sponsor_organization` removed, `v2_n_1_1` raises `missing_required_fact` with `fact_paths == ("synopsis.sponsor",)`.

Point 3 is the property I said was untested in round 1, and it is now tested. Point 4 pins the "missing material is reported, not silently absorbed" behavior. The owner's executed artifact agrees: `all_real_contract_bind_probe.json:3-5` records `"counts": {"bound": 111}`.

Two honest limits on this test, neither blocking:

- It asserts no chapter count. If `registry.chapters` ever shrank, the loop would still pass; the 111 count lives in the probe artifact, not in an assertion. A one-line `assert len(registry.chapters) == 111` (or a `>=` floor with a comment) would close it.
- The synthetic store is derived from the same catalog being tested, so step 2 cannot falsify a *wrong* canonical target — it can only falsify an unreachable or mistyped one. That is the right scope for an addressing test, but it should not be cited as evidence that the thirteen projection targets are the *correct* targets. The PRD table is the authority for correctness, and Codex's round-1 review already said those declarations "require implementation review."

### 2. Owner answers, challenged from source

**D1 — accepted, with one residual.** The premise I built round-1 D1 on was that `canonical_path` must be a member of the registry vocabulary. The owner's position — `StudyDefinition.facts` is an open dict (`protocol_v3.py:659`, `Annotated[dict[NonEmptyText, JsonValue], Field(min_length=1)]`), and the chapter vocabulary need not contain every canonical target — is **correct as a matter of the code**. I verified the helper used by the new test does not filter keys (`test_study_definition_reducer.py:66-84` passes `**overrides` straight into `StudyDefinitionV3`), so an open store is real, not an assumption. The five keys are declared in the PRD table (`frozen_review_round2/.trellis/.../prd.md:32-44`) and supplied by material admission; `missing_required_fact` is the designed report for their absence. **My round-1 D1 severity rating was wrong and I withdraw it.** The real defect it masked — no test bound a real contract — is fixed (1c).

Residual, non-blocking: the five keys now exist as read targets with a PRD row but no type, unit, timing, or admission-source declaration anywhere in the frozen set. `resolution_registration.json` records them as `projection` with their canonical path and consuming contract, which is the right level for A. Their typed definition belongs to admission (D/V1) and I am not asking for it here — but "declared" currently means "named in a table," and the admission step will need a typed contract for them.

**D2/D3 — accepted as policy, and the reasoning is sound on its own terms.** The owner's position: an alias-only input is not an authorized confirmed canonical fact, so automatic fallback would manufacture authority; the alias must not be silently upgraded, and the conflict must not be hidden by a canonical-wins rule. Checked against the code: `bind_chapter_input` reads only `study.facts[binding.canonical_path]` (`fact_bindings.py:241`), never the projection key, and the conflict check at `:246-249` fires only when both exist. So the current behavior is *report, never invent* — which is the conservative side, and it is internally consistent with the reducer's refusal to mutate confirmed facts (`canonical/study_definition.py:688-715`). The recovery gap is real and the owner has now written it into the PRD as a D/V1 obligation with a concrete shape: an explicit fact revision / projection-alias retirement preserving history, CAS and ledger receipts, plus recoverable diagnostics, verified against real SQLite before V1 (`frozen_review_round2/.trellis/.../prd.md:54`; `plans/...implementation_plan_v3_20260912.md:179`). That is the right home for it. **Judging D2/D3 as A defects would be judging an unimplemented D obligation; I do not.**

**D4 — my claim corrected (see §0).** The owner's added requirement — "事实确认写入前按目录验证native JSON类型；legacy转换显式声明来源格式...只读取时校验是A边界，不是完整写入产品的验收" (`prd.md:55`) — is the correct boundary. Native booleans required, legacy source format explicit, fixtures structural only. Accepted.

**D5 — accepted, with a low-severity finding.** `resolution_registration.json` exists and its counts reconcile exactly against the catalog: **724** `"fact_path"` rows = **711** `"resolution": "canonical_direct"` + **13** `"resolution": "projection"` + **0** unsupported, and **714** `"value_type": "json"` rows matching `legacy_type_unresolved_paths`. The derivation-from-`canonical_path` argument (None → unsupported, equality → direct, otherwise → projection) is defensible and the file is generated rather than hand-maintained in spirit. The `resolution` field is therefore derivable and the owner's refusal to duplicate it into `FactBinding` is reasonable. **But** see §3 finding F1: nothing in the repo binds this file to the catalog.

**D6 — accepted.** The helper is documented as a canonical-change translator ("Translate actual canonical changes into the contract vocabulary", `fact_bindings.py:154`), the PRD assigns projection-key edits to D admission as rejected-or-migrated, and the test pins both the canonical-change fan-out (`synopsis.sample_size` and `statistics.sample_size.reproducible_result` both returned) and the unrelated-path no-op. Judging it against a bidirectional mutable alias would be judging an API that was never declared. Withdrawn as a defect.

**D7 — accepted, and the evidence is genuinely bound.** `review_verification_receipt.json` now carries what round 1 lacked: exact `command` (interpreter path, `-m pytest tests/protocol_v3 --ignore=.../test_chapter_applicability.py -q --junitxml=...`), exact `env` (PATH, HOME, `TMPDIR=/var/folders/...`, LANG, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONNOUSERSITE=1`, `PYTHONPATH=tests/protocol_v3:services/api:packages:.`), `started_at`/`finished_at`, `returncode: 0`, and identical `before`/`after` hashes for all five product sources — and those five hashes match `frozen_review_round2/source_hashes.json` exactly. The log records `1902 passed, 1 warning in 98.33s`, with the run duration (≈99 s) matching the receipt's timestamps. The `scope_exclusion` field states the B exclusion explicitly: "15 B predicate tests are intentionally red, module not implemented; not claimed green or accepted." **D7 is closed. I do not claim 3R.4B completed anywhere in this report.**

**D8 — accepted.** "Missing output facts remains structural checker obligation, never claimed adoption-complete" is consistent with the code: `validate_output_facts` iterates `output.facts` (`fact_bindings.py:306`) and is a fact-equality/snapshot checker only, while `evaluate_chapter_content` owns `missing_required_fact` (`chapters.py:638-650`) and `skeleton_content` (`chapters.py:830-851`). I confirmed the division rather than assuming it. One note for future wiring: nothing in the product calls `validate_output_facts` yet (only the test module does), so its guarantee is currently exercised only by tests.

### 3. Remaining A-local findings

**No confirmed A-local blocking defect remains.** I looked specifically for one and could not find one. What I can substantiate is one low-severity artifact-integrity gap and a set of coverage notes.

**F1 (LOW, non-blocking) — `resolution_registration.json` is not bound to the catalog by any test or generator.**
A repo-wide search for `resolution_registration` returns only three files: the implementation plan, the conference prompt for this round, and the frozen copy of the plan. No script generates it, no test reads it, and no test asserts that its rows match `fact_bindings.json`. The catalog itself is well protected — `load_fact_catalog` binds `template_id`, `template_sha256`, and `registry_binding_sha256` (`fact_bindings.py:141-150`), and `test_shipped_fact_catalog_covers_registry_and_binds_current_contracts` rebuilds and compares — but the 724-row registration table is a sibling artifact that can drift silently if the catalog is ever rebuilt.

*Why it is low severity:* nothing reads it at runtime; the PRD cites it as an A deliverable and its counts reconcile today (724 = 711 + 13 + 0; 714 legacy-unresolved).
*Proposed remediation (small):* add either a generator under `scripts/qc/protocol_v3/` or a test that rebuilds the registration from the loaded catalog and asserts equality, so the deliverable is reproducible rather than re-derived by hand. This is the same discipline the catalog already gets.

**F2 (LOW, wording) — the `unsupported` category is unreachable by construction.** `build_direct_fact_catalog` sets `canonical_path=path` for every undeclared path and copies declarations verbatim (`fact_bindings.py:123-131`); the shipped catalog contains zero `"canonical_path": null` entries (verified by grep). So `resolution: "unsupported"` and `unsupported_fact_paths` can only be non-empty if someone hand-authors a `null`. The PRD's framing of the registration as "direct/projection/unsupported" (`prd.md:52`) is therefore accurate about the schema and vacuous about the third value. Not a defect — the `unsupported_required_fact` path at `fact_bindings.py:237-239` is live and correct for a future `null` — but the artifact's own header should say the category is empty by construction rather than leaving a reader to wonder whether the derivation failed.

**F3 (coverage note, not a defect) — three small assertion gaps in the round-2 tests.**
(a) No test asserts `ContentFact.value` string preservation when the fact is nested inside a `ChapterSkillOutput` (which still declares `str_strip_whitespace=True`, `chapters.py:312`); the existing whitespace test constructs `ContentFact` directly. Pydantic v2 honors a nested model's own config, and the code reads correctly, but the specific nesting path is unpinned. (b) No test covers a non-finite value nested inside a list or dict — the code handles it because `_json` serializes the whole value, but the test only covers a top-level `float("nan")`. (c) `test_every_real_contract...` asserts no chapter count (see §1c). All three are one-to-three-line additions; none blocks A.

### 4. Assumptions I am holding (not verified)

- **A1.** I assume `source_hashes.json` (round 2) accurately describes the frozen bytes. I could not recompute SHA-256. Corroboration: the receipt's `before`/`after` blocks reproduce all five product-source hashes from `source_hashes.json` exactly, and the receipt's `returncode: 0` with matching before/after means the run did not mutate the sources.
- **A2.** I assume the 1902-passing run covers the round-2 test file. Corroboration: the command runs all of `tests/protocol_v3` except the B module, and the new tests live in `test_chapter_fact_binding.py`; the log shows no failures, errors, or skips in its summary line.
- **A3.** I assume Pydantic v2 semantics for nested-model config precedence (`ContentFact(str_strip_whitespace=False)` inside `ChapterContentPayload(str_strip_whitespace=True)`). The owner's executed run is consistent with this, and the test at `test_chapter_fact_binding.py:243-251` exercises it; I did not execute it myself.
- **A4.** I assume the five new canonical keys are intended to be supplied as typed values by material admission, not derived. The PRD says so (`prd.md:46`, `:53`); no admission code exists yet.

---

## Evidence And Assumptions

**Observation (read directly, no inference):**

1. `frozen_review_round2/source_hashes.json` — seven entries; `fact_bindings.json` hash (`182868…0250`) is byte-identical to round 1, so the catalog did not change between rounds; `protocol_v3.py`, `chapters.py`, `fact_bindings.py`, the test file, and the PRD all changed.
2. `protocol_v3.py:647-651` — `StudyDefinitionV3.model_config = ConfigDict(str_strip_whitespace=False)` with the "exact data, not labels" comment; `StableId` at `:40-48` and `NonEmptyText` at `:53` retain their own `strip_whitespace=True`.
3. `chapters.py:277` (`ChapterSkillInput`, `str_strip_whitespace=False`), `:174` (`ContentFact`, `str_strip_whitespace=False`), `:312` (`ChapterSkillOutput`, still `True`), `:245` (`ChapterContentPayload`, still `True`).
4. `chapters.py:156-166` — `_has_fact_value` returns `True` for any non-blank string, including `"false"`; comment: "Both false and zero are real supplied facts."
5. `fact_bindings.py:305-315` — per-fact `try/except (ValueError, TypeError)` around the `_json` comparison, converting non-finite output into `output_fact_mismatch`.
6. `fact_bindings.py:241`, `:246-249` — canonical-only read; conflict raised only when both keys exist.
7. `fact_bindings.py:123-131` — `build_direct_fact_catalog` preserves declared `canonical_path`/`value_type`; the shipped catalog has zero `null` canonical paths (grep).
8. `test_chapter_fact_binding.py:243-251` (whitespace), `:254-262` (nonfinite), `:265-291` (all-real-contract + missing-target negative).
9. `review_verification_receipt.json` — exact command, env (including `TMPDIR`), timestamps, `returncode: 0`, before/after hashes matching `source_hashes.json`, `scope_exclusion` naming the 15 B tests.
10. `review_verification.log:35` — `1902 passed, 1 warning in 98.33s`; no failures, errors, or skips.
11. `resolution_registration.json` — `unsupported_fact_paths: []`, `legacy_type_unresolved_paths` (714 entries), `rows` with 724 `fact_path`, 711 `canonical_direct`, 13 `projection`, 714 `value_type: json`, plus `consuming_contracts` per row.
12. `all_real_contract_bind_probe.json` — `"counts": {"bound": 111}`, `"string_false_has_value": true`, `"nan_output_accepted": "nan"` (pre-fix observation).
13. `whitespace_fidelity_probe.json` — pre-fix stripped values.
14. `frozen_review_round2/.trellis/.../prd.md:51-55` — the 2026-09-13 A-disposition section; `plans/...implementation_plan_v3_20260912.md:179-180` — D/V1 recovery case and the resolution-registration/admission split.
15. `test_study_definition_reducer.py:66-84` — the study helper passes arbitrary fact keys through unfiltered.
16. Repo-wide search: `resolution_registration` appears only in the plan, this round's prompt, and the frozen plan copy; no generator script or test references it.

**Inference:**

- That the round-2 changes close my round-1 D4 (nonfinite) and D7 (evidence binding) findings follows from the code and receipt above; I did not execute the tests.
- That F1's drift risk is real follows from observation 16 plus the absence of any equality assertion; its *severity* is my judgment, based on the fact that nothing reads the file at runtime.
- That the five canonical keys are "declared but untyped" follows from the PRD table plus the absence of any contract, type, or admission mapping for them.

**Assumption:** A1–A4 in §4.

**Uncertainty:** whether a future `canonical_path: null` will ever be authored (F2 is latent capability, not a current state); whether `ChapterSkillOutput`'s `str_strip_whitespace=True` could strip a nested `ContentFact` string value in some path my reading missed (F3a) — I judge it cannot, but I flag it as unexecuted.

---

## Risks, Gaps, And Verification Needs

| # | Item | Status | Severity |
|---|---|---|---|
| D1 | Projection targets unregistered | **Withdrawn as a defect**; premise wrong (`facts` is an open dict); the real gap (no real-contract test) is closed by `:265-291` | — |
| D2/D3 | Alias fallback / conflict recovery | **Withdrawn as A defects**; owner policy accepted; recovery now a written D/V1 obligation with SQLite acceptance | — |
| D4 | Write-boundary type admission | **Corrected**; my `_has_fact_value("false")` claim was false; read-time-only validation accepted as the A boundary, admission assigned to D/V1 | — |
| D5 | 724-path registration | Delivered; counts reconcile | F1 LOW, F2 LOW (wording) |
| D6 | Canonical-change-only helper | **Withdrawn**; matches the declared API | — |
| D7 | Evidence binding | **Closed**; receipt carries command, env, time, before/after hashes, JUnit; 1902 passed | — |
| D8 | Missing output facts | **Accepted** as structural-checker obligation | — |
| F3 | Test coverage gaps (nested-output whitespace, nested nonfinite, chapter count) | Open, small | LOW |

**Gaps in acceptance evidence (all minor):**

1. No machine binding between `resolution_registration.json` and the catalog (F1).
2. No assertion that all 111 chapters were bound in the addressing test (F3c) — the count lives in the probe artifact.
3. No test for whitespace preservation through the `ChapterSkillOutput` nesting path (F3a) or for nested non-finite values (F3b).
4. The five new canonical keys have no typed declaration anywhere yet; that is D/V1 scope, but it is the one place where "declared" currently means only "named in a PRD table."

**Verification I could not perform:** recomputing the seven SHA-256 values; executing the three falsifiable reproducers below; confirming Pydantic's nested-config behavior directly (A3).

**Falsifiable reproducers for the findings I am *not* claiming as bugs (offered so Codex can close or reopen them):**

- **F1:** load the catalog, regenerate the registration from it, and assert equality. If the regeneration differs from the committed file in any row, F1 is a real drift, not a hypothetical.
- **F2:** construct a `FactBinding(fact_path=<a required path>, canonical_path=None, value_type="json", source_refs=("test",))`, call `bind_chapter_input` on a contract requiring that path, and assert `FactBindingError.code == "unsupported_required_fact"` with the exact path. This pins the latent branch at `fact_bindings.py:237-239`.
- **F3a:** `ChapterSkillOutput(chapter_contract_id=..., node_id=..., facts=(ContentFact(fact_path="x", value="  a\nb  "),))` then read `output.facts[0].value` and assert it is `"  a\nb  "`. If it comes back stripped, F3a is a real defect and `ChapterSkillOutput` needs the same treatment `ContentSkillInput` received.

---

## Recommended Next Step

**For Codex:**

1. **Accept 3R.4A as mechanically complete for the A scope**, on the strength of the hash-bound receipt (1902 passed, before/after hashes matching `frozen_review_round2/source_hashes.json`, B explicitly excluded) plus the new real-contract addressing test. My round-1 objections D1–D3 are withdrawn as A defects; D4 was factually wrong on my side and is corrected; D7 is closed.
2. **Do not treat this as product, medical, or Word acceptance.** The addressing test is synthetic by its own docstring ("Synthetic addressing test, not medical acceptance"), the fixtures are structural only, and the five new canonical keys have no typed declaration yet. Product/medical/full-Word acceptance remains open exactly as stated.
3. **Close F1 with one test or one generator** so the 724-row registration is reproducible from the catalog rather than re-derived. This is the only remaining artifact-integrity gap I found, and it is cheap.
4. **Fold F3a/F3b/F3c into the next test increment** — three small assertions that pin nesting paths and the chapter count.
5. **Keep D2/D3 recovery on the D/V1 critical path** as written: explicit fact revision or projection-alias retirement with preserved history, CAS and ledger receipts, recoverable diagnostics, verified against real SQLite before V1. The current read-only behavior is conservative and correct; it must not be mistaken for a resolved workflow.
6. **Carry the five new canonical keys into admission with a typed definition** (type, unit/timing where needed, admission source), so "declared" becomes actionable rather than nominal.

**Bounded questions (none blocking):**

- **Q1 (F1).** Is `resolution_registration.json` intended to be regenerable from the catalog (generator/test), or is it a one-time A artifact that later rounds will not re-derive? *Why it matters:* it determines whether F1 needs a fix now or a note in the plan.
- **Q2 (F3c).** Should the all-real-contract test assert the 111 count, or is the count deliberately kept in `all_real_contract_bind_probe.json` as the binding evidence? *Why it matters:* without an assertion, a shrinking registry would silently weaken the test.

**Resume point.** The pass completed within budget; no step boundary was hit. If Codex wants the F1/F2/F3 reproducers executed rather than proposed, the exact requirement is a read-only Python session with `PYTHONPATH=tests/protocol_v3:services/api:packages:.` — blocked in this session only by the Bash denial, not by source access.
