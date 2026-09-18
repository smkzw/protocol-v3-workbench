I'll start with the initial read set.

Bash is denied in this session — I'll note that as a capability limitation and work with read-only tools (Glob/Grep/Read).

I have enough evidence. Two final checks before writing.

# Conference Participant Output: mw_protocol_v3_3r4a_review_20260912 - general_single_object

## Boundary Check

**Identity and fallback (stated explicitly).** This pass was executed by CodeBuddy CLI, model `deepseek-v4-flash`, acting as the declared runner fallback `codebuddy` / `codebuddy-cli` / `deepseek-v4-flash` after the primary node (`opencode-go` / `muse-spark-1.3-contributor`) failed before a resumable session existed. I did not use the primary provider's tools or session. Role, source list, output schema, and the single-pass conference protocol were preserved unchanged. Effort was requested at `xhigh`; the fallback node's own effort policy applies (`max` per the runner chain), and I cannot independently attest the harness's internal effort setting — treat that as a runner-recorded fact, not my claim.

**Capability limitation (material to the verdict).** The `Bash` tool was denied in this session (non-interactive, no permission prompt available). I therefore **could not execute the authorized bounded read-only Python probes** (`runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=tests/protocol_v3:services/api:packages:.`) that the scope explicitly permits. Consequences:

- Every runtime-behavior claim below is **static analysis of source**, not an executed reproducer. I have not run pytest, not imported the modules, and not confirmed that the cited errors actually raise with the cited codes.
- I could not independently confirm the SHA-256 values in `source_hashes.json`. I verified frozen-vs-live equality only by content inspection of the two implementation files and by matching the catalog's structural counts (724 `canonical_path` entries, 14 `synopsis.*` entries, 10 explicit `boolean` entries) between the frozen copy and the live file.
- I did not and could not perform final visual/PPT/browser/clinical/regulatory acceptance. Codex retains that authority.

**What I actually read (all read-only).** `context/mw_protocol_v3_3r4a_review_20260912_conference_context.md`; `plans/codex_main_venue_mw_protocol_v3_3r4a_review_20260912.md` (still `TODO` throughout — it supplied no task decomposition, so I built my own audit from the objective and the frozen artifacts); the full frozen set under `runs/mw_protocol_v3_3r4a_20260912/frozen_review/` (`source_hashes.json`, `services/api/app/protocol_workflow/registries/fact_bindings.py`, `.../chapters.py`, `tests/protocol_v3/test_chapter_fact_binding.py`, `config/.../fact_bindings.json`, `.trellis/tasks/09-11-protocol-v3-3r4/prd.md`, `plans/mw_protocol_v3_implementation_plan_v3_20260912.md`); current sources `packages/contracts/workbench_contracts/protocol_v3.py`, `services/api/app/protocol_workflow/canonical/study_definition.py`, `config/.../tp_ma_07_v2/chapter_contracts/*.json` (targeted), `tests/protocol_v3/test_all_chapter_contracts.py` (targeted), `tests/fixtures/protocol_v3/chapter_content_v2/*.json` (targeted), `plans/mw_protocol_v3_design_v1.4_20260912.md` (targeted); run evidence `runs/mw_protocol_v3_3r4a_20260912/*.log`, `.../fact_inventory_worker/*`, `.../explicit_boolean_type_evidence.json`; reviews `reviews/codex_execution_mw_protocol_v3_3r4a_fact_inventory_20260912_review.md`. I did not read other participants' outputs, prior private worker reasoning, or any production path outside this workspace. I wrote nothing; the runner owns `runs/conference/.../general_single_object.md`.

## Independent Work Product

### 0. What I audited, and how I framed it

I did not accept the objective's framing at face value. "Frozen fact transport and canonical binding" is stated as if the contract were: *values move from the canonical store into chapter inputs without type loss*. My audit reframed it as three separable claims, because they fail differently:

1. **Addressing claim** — every contract fact path resolves to a real canonical location.
2. **Fidelity claim** — the value that arrives is the value that was stored, with the declared type honored, and `false`/`0`/`null`/missing/not-applicable kept distinct.
3. **Evidence claim** — the acceptance tests actually exercise the real contracts and would fail if the addressing or fidelity claim broke.

I then checked each claim against the frozen source and the current chapter contracts, prioritizing checks the existing test suite cannot make. The existing 37/52/65/72-pass logs tell me the *unit* behavior of helpers is green. They cannot tell me whether the shipped catalog binds the shipped contracts, because no test in `tests/protocol_v3/` calls `bind_chapter_input` with a real chapter contract — I confirmed that by searching for every consumer of `fact_bindings` (only `test_chapter_fact_binding.py` matches) and for `bind_chapter_input`/`load_fact_catalog`/`affected_chapter_fact_paths` in product code (only the defining module matches).

**Result: claims 1 and 3 fail. Claim 2 fails in a specific, narrow way. Four concrete defects below, ordered by impact.**

### D1 — CRITICAL: five of the thirteen synopsis projections address canonical keys that exist in no contract and in no registry vocabulary

`bind_chapter_input` resolves a fact by reading `study.facts[binding.canonical_path]` (`frozen_review/services/api/app/protocol_workflow/registries/fact_bindings.py:241`). For a projection binding, that canonical key is a **read target that must exist in the canonical store and must be a registered fact key**. Nothing checks this. The catalog validator only checks catalog coverage and registry identity (`fact_bindings.py:141-150`), and `FactBinding` (`fact_bindings.py:30-39`) carries no constraint tying `canonical_path` to `registry.fact_vocabulary`.

I checked all thirteen projection targets in the PRD table (`frozen_review/.trellis/tasks/09-11-protocol-v3-3r4/prd.md:26-47`) against the current chapter contracts and the catalog:

| Synopsis path | `canonical_path` in catalog | Canonical key present in any contract / vocabulary? |
|---|---|---|
| `synopsis.registration_classification` | `framing.registration_classification` | **No** (only occurrence in repo: catalog line 7568) |
| `synopsis.sponsor` | `contact.sponsor_organization` | **No** (only occurrence: catalog line 7591) |
| `synopsis.trial_institutions` | `contact.trial_institutions` | **No** (only occurrence: catalog line 7623) |
| `synopsis.overall_duration` | `framing.study_overall_duration` | **No** (only occurrence: catalog line 7524) |
| `synopsis.participation_duration` | `picos.participation_duration` | **No** (only occurrence: catalog line 7535) |
| `synopsis.principal_investigator` | `contact.principal_investigator` | yes (`v2_n_front_4.json`) |
| `synopsis.design` | `framing.structured_design` | yes |
| `synopsis.population_eligibility` | `picos.inclusion_modules` | yes (`v2_n_3_2_1.json`) |
| `synopsis.investigational_drug` | `intervention.product_identity` | yes |
| `synopsis.comparator_drug` | `picos.intervention_dose_regimen.comparator_regimen` | yes |
| `synopsis.interventions` | `picos.intervention_dose_regimen` | yes |
| `synopsis.sample_size` | `statistics.sample_size.reproducible_result` | yes (`v2_n_11_1.json`) |
| `synopsis.statistical_methods` | `picos.statistical_strategy` | yes |

Mechanism and consequence, exactly:

- All thirteen `synopsis.*` rows are declared `"obligation": "required"` in `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/v2_n_1_1.json` (I read all thirteen; the adjacent fourteenth row `synopsis.template_example_values` is `forbidden`, which is why the catalog holds 14 `synopsis.*` entries while the PRD table lists 13).
- For the five rows with unregistered targets, `binding.canonical_path not in study.facts` is true for any study that does not happen to carry those exact keys. Because the path is in `required` (`fact_bindings.py:212-215`), it lands in `missing` and raises `FactBindingError("missing_required_fact", [...])` at `fact_bindings.py:257-258`. The summary chapter `v2_n_1_1` becomes unbindable.
- The PRD states these five are "本次新声明的单一事实键" (single fact keys newly declared in this round) and that they are "仍在现有StudyDefinition.facts内" — inside the existing store. That is the right design, but the declaration was made **only in the catalog**, not in any contract, so the registry vocabulary never gained them. The catalog is therefore pointing at keys the contract layer has never heard of.
- Worse, this is invisible to the shipped test. `test_shipped_fact_catalog_covers_registry_and_binds_current_contracts` (`frozen_review/tests/protocol_v3/test_chapter_fact_binding.py:205-230`) asserts only `rebuilt == catalog`. `build_direct_fact_catalog` copies `canonical_path` and `value_type` verbatim from the declarations it is handed (`fact_bindings.py:126-131`); it never inspects or validates them. The assertion is a tautology with respect to the very field that is wrong — **the test would pass with all thirteen canonical paths pointing at nonsense**. It pins exactly one projection (`synopsis.sample_size`, line 223) and one boolean (`irc.applicable`, line 224) and nothing else.

**Proposed remediation (three parts, all small):**

1. Add a load-time invariant in `load_fact_catalog` (or a new `validate_fact_catalog`) that every non-null `canonical_path` is a member of `registry.fact_vocabulary`, and raise a distinct code (e.g. `fact_catalog_unregistered_canonical_target`) listing offenders. This converts a silent-at-load / fatal-at-runtime defect into a load-time failure, and it makes the shipped-catalog test meaningful.
2. Declare the five keys in the contract layer: add each to the contract vocabulary and to the chapter(s) that actually consume them (the summary row is the consumer for the synopsis side; the corresponding body chapters need the fact declared so the vocabulary union picks it up). Do not hand-edit `fact_bindings.json` alone — the whole point of the defect is that the catalog drifted from the contracts.
3. Add a test that binds **the real contract** rather than the synthetic objectives contract: for `v2_n_1_1`, construct a confirmed `StudyDefinitionV3` whose facts contain the canonical targets, call `bind_chapter_input`, and assert the thirteen synopsis paths appear in `resolved_facts` with the canonical values. Add the negative: with the canonical target absent, assert the exact `missing_required_fact` path list. That test is the acceptance evidence the current suite lacks.

### D2 — HIGH: the alias is a one-way pointer, so a value that exists under the projection key is silently dropped

The alias consistency check at `fact_bindings.py:246-249` runs **only when the canonical path already resolved**. The resolution branch above it (`fact_bindings.py:241-244`) has no alias fallback:

```
if binding.canonical_path not in study.facts:
    if path in required: missing.append(path)
    continue                       # <-- alias never consulted
```

So when a study carries `synopsis.sample_size` but not `statistics.sample_size.reproducible_result`:
- if the path is optional in that contract, the fact is **silently omitted** from `resolved_facts` and the skill writes the chapter without it, with no diagnostic at all;
- if the path is required, it hard-fails even though a value is present.

This is exactly the reading the PRD forbids on the writer side: "已有重复值与规范值矛盾时报告，不自动覆盖" (report the contradiction, do not auto-overwrite). Reporting a contradiction presupposes that the duplicate value is *seen*. Here it is not seen; it is discarded. The PRD's own projection table shows the design intent is a single readable source, but the implementation makes the projection key a dead end rather than an alias.

**Proposed remediation:** when the canonical path is absent and the alias path is present, use the alias value and record the provenance (`value_source: "alias"` or a parallel `alias_used` tuple on `BoundChapterSkillInput`) rather than dropping it. Keep the canonical path authoritative when both exist and they agree; keep the hard conflict error when they disagree (see D3 for how that should surface). Add tests for the two currently-untested directions: alias-present/canonical-absent (must resolve, with provenance) and both-present/equal (must resolve silently).

### D3 — HIGH: the alias-conflict error has no sanctioned repair path, so an anticipated conflict permanently blocks the chapter

`fact_bindings.py:249` raises `FactBindingError("fact_alias_conflict")` — a hard abort of the whole chapter binding — the moment a study holds both a projection key and a canonical key with different values. The PRD anticipates precisely this state and asks for a *report*. Meanwhile the reducer provides no way to clear it:

- `StudyDefinitionV3.facts` is frozen (`packages/contracts/workbench_contracts/protocol_v3.py:674`, `_freeze_json_value`).
- The only fact-mutation path is `StudyDefinitionReducer.apply_decision` → `_merge_facts`, and `_protected_fact_paths` (`services/api/app/protocol_workflow/canonical/study_definition.py:688-715`) refuses any update that changes an existing fact while the definition is `CONFIRMED` or `FROZEN` — which is exactly the state `bind_chapter_input` requires (`fact_bindings.py:203-204`). There is no fact-removal or fact-retirement operation anywhere in the reducer.

**Net effect:** a project whose facts already contain, say, `synopsis.sample_size` (a plausible outcome of AI extraction from a synopsis table, which is the scenario the PRD is written for) can never produce `v2_n_1_1` chapter input, and no supported operation can resolve it. This is not a hypothetical I can dismiss: the fact keys entering `study.facts` are chosen upstream by whatever builds `fact_updates` (`study_definition.py:356`, `:475`), and nothing in the read path constrains them to the vocabulary.

**Proposed remediation (pick one, and record the choice):**
- **(a) Soften the surface:** keep canonical-authoritative resolution (bind the canonical value), and emit the alias conflict as a structured diagnostic on the bound input (or a separate report object) that the caller must surface to the user, instead of aborting. This matches the PRD wording literally.
- **(b) Add a repair path:** a decision-scoped alias retirement (or fact supersession) in the reducer that lets a confirmed study drop a projection key it must no longer carry, with an audit record. This is more work and touches 3R.4D territory, so if chosen it should be scoped there rather than smuggled into A.
- **(c) Do both**, with (a) as the immediate behavior and (b) as the D-phase repair.

Whichever is chosen, the current behavior — hard abort with no escape — must not ship as the 3R.4A behavior.

### D4 — MEDIUM-HIGH: declared `value_type` is enforced only at read time, and the fixtures show the declared type contradicts the existing encoding

The catalog asserts `"value_type": "boolean"` for exactly ten paths (`runs/mw_protocol_v3_3r4a_20260912/explicit_boolean_type_evidence.json`; catalog lines with `"value_type": "boolean"`), each backed by a contract rationale saying 「裸 true/false 编码」. `_typed_value` (`fact_bindings.py:172-182`) enforces that with `type(value) is bool` — a **strict Python-type identity test**, not a truthiness test.

But the actual fixtures encode those same facts as **JSON strings**:

```
tests/fixtures/protocol_v3/chapter_content_v2/batch6.json
    "fact_path": "statistics.interim.applicable",
    "value": "false"
tests/fixtures/protocol_v3/chapter_content_v2/batch5.json
    "fact_path": "irc.applicable",
    "value": "false"   (and "true")
tests/fixtures/protocol_v3/chapter_content_v2/batch8.json
    "fact_path": "quality.risk_management_plan_applicable",
    "value": "true"
```

The worker inventory states this flatly: "All 2487 fixture fact values across 558 fixtures are JSON strings (no null, no boolean/number/list/object)" (`runs/mw_protocol_v3_3r4a_20260912/fact_inventory_worker/fact_inventory_summary.md:45-46`). So in the only concrete encoding evidence that exists today, `irc.applicable` is the string `"false"`, and the catalog's `boolean` declaration would reject it under `native_json`. That is defensible as a *forward* declaration ("the canonical store must hold bare booleans"), but three things are missing for it to be safe:

1. **No enforcement at the write boundary.** The declared type is never checked when facts enter the store; the mismatch is only discovered when a chapter binds, which is after the study is already `CONFIRMED` and therefore unrepairable (same trap as D3). The failure surfaces far from its cause.
2. **The legacy converter cannot rescue the fixture encoding.** Under `source_format="legacy_strings_v1"` the string `"false"` does convert (`json.loads("false") → False`, covered by `test_legacy_conversion_requires_explicit_declared_type`, test line 115-126). But under `native_json` — the default and the product path — the string form is a hard `fact_type_mismatch`. Which format the product actually uses for existing projects is not stated anywhere in the frozen set, and the two behaviors differ.
3. **The declared type is not covered by a test against real data.** The only boolean test is `assert ... == "boolean"` on the catalog (test line 224). Nothing binds a study containing `"false"` against `irc.applicable` and asserts the resulting error, and nothing asserts that a *conforming* study with bare `False` binds cleanly.

There is a second-order fidelity hazard in the same area worth stating precisely: `_has_fact_value` (`frozen_review/.../chapters.py:156-166`) treats the string `"false"` as **absent** (blank-string rule) while treating the boolean `False` as **present** ("Both false and zero are real supplied facts"). So the same semantic value `false` is "supplied" or "not supplied" depending purely on whether it was stored as a string or a boolean. That divergence is invisible until the deterministic checker runs, and it is the reason the declared type matters more than it looks.

**Proposed remediation:**
- Validate `value_type` at fact acceptance (the same place `fact_updates` is validated before the reducer commits), using the catalog as the type map, so a mis-typed fact fails before it can become an unrepairable confirmed fact.
- Decide and document the encoding contract: either the canonical store holds bare JSON booleans (then add a one-time, explicit, tested conversion for projects holding string `"true"`/`"false"`, driven by the declared type, not by guessing), or the catalog declares these paths as `"string"` and the applicability predicates in 3R.4B parse them. Do not leave both encodings plausible.
- Add tests: string `"false"` under `native_json` → exact error code and path; bare `False` → binds; `"false"` under `legacy_strings_v1` with declared `boolean` → binds to `False` (this last one exists); and a negative for `"TRUE"`/`"False"` casing so the non-guessing rule is pinned.

### D5 — MEDIUM: the per-path resolution registration required by Plan v3 and design v1.4 is not implemented, and the catalog schema has no place to put it

Plan v3 §3R.4A step 3 requires registering **all 724 paths** by resolution method: canonical direct read, deterministic derivation/alias, or explicitly unsupported, with the note that an unsupported path must have an explicit list rather than a blanket "unified attribution" statement with no reader (`frozen_review/plans/mw_protocol_v3_implementation_plan_v3_20260912.md:34-43`). Design v1.4 states the same requirement and names the fields: canonical path, value type, unit/timing when needed, **取得方式 (method of acquisition)**, source, and consuming chapters (`plans/mw_protocol_v3_design_v1.4_20260912.md:35`).

`FactBinding` (`fact_bindings.py:30-39`) has `fact_path`, `canonical_path`, `value_type`, `source_refs`, `unit`, `timing`. It has **no acquisition-method field**, and `unit`/`timing` are `null` on every entry. Consequently:

- 714 of 724 bindings are `value_type: "json"` with `canonical_path == fact_path`, i.e. every path is implicitly declared "direct read" whether or not that is true;
- there is no way to express "explicitly unsupported" — `canonical_path: None` is the only hint, and it exists only to make a *required* path fail with `unsupported_required_fact` (`fact_bindings.py:237-239`), not to publish an unsupported list;
- the delivery requirement "尚不支持字段有明确清单" has no artifact.

The worker inventory deliberately did **not** produce this either — `fact_inventory.json` records membership, source locators, conditional roles, and the absence of type evidence, but no per-path resolution method (I searched it: no `resolution`, `resolution_method`, `canonical_direct`, `alias`, or `derivation` fields; its top-level keys are provenance/counts/`conditional_only_paths`/per-path membership).

**Proposed remediation:** add `resolution: Literal["canonical_direct", "projection", "derivation", "unsupported"]` to `FactBinding`, and either a `method`/`notes` free field or a `derivation_ref`. Then generate and commit the 724-row registration table (a script that reads the catalog plus the contracts and emits one row per path with `fact_path`, `resolution`, `canonical_path`, `value_type`, `source_refs`, `consuming_contracts`) so the "explicitly unsupported list" is a produced artifact, not a claim. This is also the natural place to record the D1 five keys as `projection` with a registered target.

### D6 — MEDIUM: `affected_chapter_fact_paths` ignores changes made under the projection key, so a real change can fail to reopen the summary chapter

```
def affected_chapter_fact_paths(bindings, changed_canonical_paths):
    changed = set(changed_canonical_paths)
    return tuple(sorted({b.fact_path for b in bindings if b.canonical_path in changed}))
```
(`fact_bindings.py:153-158`)

Only `canonical_path` is consulted. If a change arrives keyed by the projection path (`synopsis.sample_size`), the function returns `()`. The PRD explicitly makes this the C-phase obligation: 「C阶段必须经affected_chapter_fact_paths把规范事实变更映射至含synopsis投影的合同路径」 (`frozen_review/.trellis/tasks/09-11-protocol-v3-3r4/prd.md:48`). The shipped test covers one direction only (`statistics.sample_size.reproducible_result` → both paths, test line 233-240) and asserts the reverse direction returns `()` for an *unrelated* path (line 240) — it never asserts what happens for the projection path itself.

**Proposed remediation:** treat the alias path as a recognized key of the same fact: include bindings where `canonical_path in changed` **or** `fact_path in changed`. Add the two missing assertions: changing `synopsis.sample_size` returns both paths; changing an identity path returns itself. Note the tension with D2 — if the alias is not readable (D2) and not change-detectable (D6), the projection is decorative.

### D7 — MEDIUM: the acceptance evidence is not bound to the reviewed artifact

`runs/mw_protocol_v3_3r4a_20260912/` contains `typed_values_red.log`, `typed_values_red_valid.log`, `typed_values_green.log`, `canonical_binding_first.log`, `catalog_typed.log`, `catalog_binding.log`, `projection_binding.log`, `empty_structures_red.log`, `empty_structures_green.log`, `catalog_rebuild_red.log`, `catalog_rebuild_green.log`, `catalog_rebuild_green_final.log`, `intermediate_regression.log`, `tmpdir_followup.log`.

Every one of them is a bare progress-dot plus a count line. Representative:

```
empty_structures_green.log:        ............ [100%]   /   72 passed in 2.30s
catalog_rebuild_green_final.log:   ..................................... [100%]  /  37 passed in 0.78s
```

No command line, no `PYTHONPATH`, no interpreter path, no environment, no timestamp, no git revision, no test-ID list. The context says test logs are a source of truth and that "Sources and test behavior outrank test counts" (`context/mw_protocol_v3_3r4a_review_20260912_conference_context.md:31`), but these logs cannot be tied to the frozen artifact under review: a `72 passed` line is equally consistent with the pre-change tree, the post-change tree, or a different working copy. There is also no session/command record in `metrics/mw_protocol_v3_3r4a_fact_inventory_20260912_execution_metrics.md` or the execution context that names them (I searched both). The `intermediate_regression.log` does contain a failure, and it is the known `TMPDIR` omission documented in Plan v3 (`.../implementation_plan_v3_20260912.md:148`), so that one is explained.

I want to be fair about severity here: the logs' *content* is consistent with the code, and the red logs show a red→green sequence, which is the right discipline. The defect is evidentiary, not behavioral. But the task's stated success criteria include recording "session, usage/tool observations" and the whole point of a frozen review is that the evidence binds to the frozen bytes.

**Proposed remediation:** re-run the two authoritative suites (the binding/chapter suite and the full `tests/protocol_v3` suite) with the exact env from Plan v3 line 146 and capture, into the same run directory, the command line, `PYTHONPATH`, interpreter path, `TZ`/`LANG`, wall-clock, the six source SHA-256s from `source_hashes.json` (recomputed), and `--collect-only` output. Store the JUnit XML that `intermediate_regression.xml` already demonstrates the harness can emit. Codex must own this, not a worker.

### D8 — LOW: `validate_output_facts` cannot detect an output that drops bound facts

`validate_output_facts` (`fact_bindings.py:305-311`) builds `conflicts` by iterating **`output.facts`** — the output's own list. An output that emits *fewer* facts than `resolved_facts` (or none at all) produces an empty `conflicts` and passes this validator. The docstring is honest that this is "fact equality/snapshot checking only; callers must also run chapter/evidence/applicability/medical checks before adoption," and `check_skill_output` → `evaluate_chapter_content` does catch missing required facts with `missing_required_fact`. So this is a layering decision, not a bug.

But it is worth naming because of D1/D4: the *only* thing that would catch an empty or fact-starved chapter is the deterministic checker, and no test in the frozen set exercises the full chain `bind_chapter_input` → skill output → `validate_output_facts` → `check_skill_output` with a real contract. The two `check_skill_output` tests in `test_all_chapter_contracts.py` (lines 1019, 1029) use the synthetic objectives contract, not a bound input.

**Proposed remediation:** either document the division of responsibility on `validate_output_facts` explicitly ("omission is the checker's job") so no future caller assumes completeness, or add an opt-in completeness check. Then add one end-to-end test on a real contract, which also serves D1 and D7.

### Secondary observations (lower confidence, flagged as such)

- **`_json` on a `NaN` output fact.** `_typed_value` rejects non-finite floats for *bound* values (`fact_bindings.py:181`), but `ContentFact.value` has no finiteness guard (`chapters.py:169-182`) and `_json` uses `allow_nan=False` (`fact_bindings.py:70`). An output fact of `float("nan")` would make `_json(fact.value)` raise a bare `ValueError` inside `validate_output_facts` rather than a typed `FactBindingError`. I could not confirm reachability (Pydantic's `JsonValue` treatment of NaN, and whether any upstream path can produce it) because I cannot execute probes — **mark this as unverified inference, not a confirmed defect.**
- **`validate_output_facts` uses the caller's `bindings` argument.** Both `bound` and `expected` are rebuilt through the same `bindings` parameter, so a stale bindings set is self-consistent; the mismatch is only caught via `fact_bindings_sha256` inside the `bound`-vs-`expected` comparison (`fact_bindings.py:301`). That works, but it means the validator's guarantee is "the same bindings produce the same input," not "the shipped catalog was used." Passing the catalog rather than a raw iterable would remove the ambiguity.
- **`load_fact_catalog` does not bind to the contract files on disk.** It verifies `template_id`, `template_sha256`, and `registry_binding_sha256` against the registry it is handed. A caller that hands it a registry assembled from stale contracts gets a clean load. The shipped test sidesteps this by reassembling from disk (`test_chapter_fact_binding.py:210-214`), which is good practice but is test-only.
- **`unit`/`timing` are dead fields today.** All entries are `null`. They are the right fields for design v1.4's "单位/时点（需要时）," but with no entry populated and no consumer, they currently assert nothing.

### Explicit statement of what is *not* a defect

I checked these and they hold, so I am recording them to keep the review honest about scope:

- Type fidelity for the JSON primitives the plan cares about is genuinely preserved through bind → serialize → reopen: `False`, `True`, `0`, `0.5`, `[False, 0]`, `{"applicable": False}`, `"false"` (test lines 35-42), and frozen nested values resist mutation (lines 61-74). `integer` correctly rejects `bool` (`type(value) is int`), and `number` correctly excludes `bool`.
- `0` and `False` are not treated as missing by the bound-input validator (`_is_resolved_fact`, `chapters.py:151-153`), which is the specific defect 3R.4A step 1 targeted.
- The canonical store is not rewritten by binding: `bind_chapter_input` reads only, and the test asserts the projection key is absent from `study.facts` (test line 112).
- Dotted paths are never split — lookup is a literal dict key read (`fact_bindings.py:241`), matching the inventory's finding that canonical facts are a flat dictionary.
- The catalog is closed and deterministic: `extra="forbid"`, frozen, unique-path validator (`fact_bindings.py:53-66`), sorted rebuild output (`fact_bindings.py:121`), and a registry hash covering template, vocabulary, and per-contract material hashes (`fact_bindings.py:73-81`).
- `chapters.py`'s `ChapterSkillInput.resolved_facts: Mapping[str, JsonValue]` with `_freeze_json_value` (lines 283-301) is the right shape for the typed-transport goal, and `ContentCell.value` remains display text, matching design §4.1's separation.

## Evidence And Assumptions

**Observation (read directly from files, no inference):**

1. `fact_bindings.py:241` reads `study.facts[binding.canonical_path]`; there is no alias fallback branch.
2. `fact_bindings.py:246-249` runs the alias consistency check only inside the already-resolved branch, and raises `fact_alias_conflict` on disagreement.
3. `fact_bindings.py:153-158` filters on `canonical_path` only.
4. `fact_bindings.py:30-39` — `FactBinding` has no acquisition-method field; `unit`/`timing` are nullable and null throughout the catalog.
5. `fact_bindings.py:141-150` — `load_fact_catalog` validates coverage and registry identity only; no constraint on `canonical_path`.
6. `fact_bindings.py:126-131` — `build_direct_fact_catalog` preserves declared `canonical_path`/`value_type` unchanged.
7. `fact_bindings.py:305-311` — `conflicts` iterates `output.facts`.
8. `config/.../v2_n_1_1.json` — all 13 `synopsis.*` rows are `"obligation": "required"`; a 14th `synopsis.template_example_values` is `forbidden`.
9. `config/.../fact_bindings.json` — 724 `canonical_path` entries, 714 `"value_type": "json"`, 10 `"value_type": "boolean"`, 14 `"fact_path": "synopsis.*"`; the five unregistered targets appear at lines 7524, 7535, 7568, 7591, 7623.
10. Repository-wide search: `framing.registration_classification`, `contact.sponsor_organization`, `contact.trial_institutions`, `framing.study_overall_duration`, `picos.participation_duration` occur **only** in `fact_bindings.json` (live and frozen copies) — not in any `chapter_contracts/*.json`, not in `fact_inventory.json`, not in product code.
11. `tests/fixtures/.../batch5.json`, `batch6.json`, `batch8.json` — `irc.applicable`, `statistics.interim.applicable`, `quality.risk_management_plan_applicable` carry string `"true"`/`"false"`.
12. `study_definition.py:688-715` — `_protected_fact_paths` blocks changing existing facts in `CONFIRMED`/`FROZEN`; `apply_decision`/`_merge_facts` is the only fact-mutation path; no removal operation exists.
13. `tests/protocol_v3/test_chapter_fact_binding.py:205-230` — the shipped-catalog test asserts `rebuilt == catalog` plus one projection and one boolean; `test_all_chapter_contracts.py` defines `_objectives_contract`/`_objectives_positive_content` for a synthetic contract.
14. Only `test_chapter_fact_binding.py` references `fact_bindings` anywhere under `tests/protocol_v3/`; no product module outside `fact_bindings.py` calls `bind_chapter_input`, `load_fact_catalog`, `affected_chapter_fact_paths`, or `validate_output_facts`.
15. The six `*_green*` logs contain no command, environment, revision, or timestamp.
16. `plans/codex_main_venue_mw_protocol_v3_3r4a_review_20260912.md` is entirely `TODO` (no decomposition, no checklist), and `reviews/codex_conference_mw_protocol_v3_3r4a_review_20260912_review.md` is entirely `TODO`.

**Inference (my reasoning over the observations):**

- D1's runtime consequence (required path → `missing_required_fact`, optional path → silent drop) follows from reading the control flow at `fact_bindings.py:212-258`; I did not execute it.
- D3's "permanent block" follows from combining observation 2, observation 12, and `bind_chapter_input`'s confirmed-state precondition (`fact_bindings.py:203-204`). I did not execute it.
- D7's judgment that the logs cannot be bound to the frozen bytes is a documentary inference from observation 15, not a claim that the tests did not pass.

**Assumption (stated, not verified):**

- I assume `source_hashes.json` accurately describes the frozen artifact. I could not recompute SHA-256 without a shell. My content-level cross-check (the two implementation files and the catalog's structural counts matching between frozen and live copies) is consistent with it but is not a hash verification.
- I assume the PRD's "newly declared single fact keys" meant *declared in the contract layer*. If Codex intended them to live only in the catalog and be supplied by a later, not-yet-written module, then D1's severity drops to "documented forward dependency" — but the five keys are still unresolvable today, the 13 rows are still `required`, and the `fact_catalog_unregistered_canonical_target` invariant is still worth adding. **This is my first bounded question to Codex.**

**Uncertainty:**

- I cannot confirm or refute the `NaN`-output `_json` path (unverified inference).
- I cannot confirm the product's actual `source_format` for existing projects; the D4 severity depends on it. If every existing project is read as `legacy_strings_v1`, the boolean declarations convert cleanly and only the write-boundary gap remains.

## Risks, Gaps, And Verification Needs

**Risks, ranked:**

| # | Risk | Trigger | Consequence |
|---|---|---|---|
| R1 | Summary chapter unbindable | any real study lacking the five unregistered canonical keys | `v2_n_1_1` cannot produce chapter input at all (D1) |
| R2 | Silent content loss | optional projection path with only the alias populated | chapter written without a fact that exists; no diagnostic (D2) |
| R3 | Unrepairable confirmed study | projection key present with a differing value | permanent hard abort; no reducer path out (D3) |
| R4 | Type failure discovered too late | string-encoded boolean reaches the canonical store | failure after confirmation, when it can no longer be fixed (D4) |
| R5 | Stale chapter not reopened | change keyed by the projection path | summary chapter keeps stale content (D6) |
| R6 | Acceptance cannot be re-verified | logs unbound to the artifact | Codex cannot certify the frozen bytes from the record (D7) |
| R7 | "Unsupported" list absent | design v1.4 / Plan v3 step 3 requirement | the supported/unsupported boundary is unstated (D5) |

**Gaps in the current acceptance evidence (what is missing, precisely):**

1. No test binds **any** real chapter contract with `bind_chapter_input`. The suite's contract is synthetic (`_objectives_contract`), so contract-level addressing errors cannot surface.
2. No test asserts that catalog `canonical_path` values are registered fact keys — the one property that would have caught D1.
3. No test covers the alias-present/canonical-absent direction (D2).
4. No test asserts what happens to a chapter after an `fact_alias_conflict`, i.e. that the block is (or is not) recoverable (D3).
5. No test asserts write-time type enforcement for the ten boolean paths, and no test asserts the fixture's string encoding against the declared boolean type (D4).
6. No test covers `affected_chapter_fact_paths` keyed by the projection path (D6).
7. No end-to-end test spans `bind_chapter_input` → `validate_output_facts` → `check_skill_output` (D8).
8. No 724-row resolution registration artifact exists (D5).
9. No log or record binds the reported test results to the frozen revision (D7).

**Verification I could not perform and am explicitly requesting:**

- Run `bind_chapter_input` for all 111 contracts against a synthetic confirmed `StudyDefinitionV3` whose facts are the 724 vocabulary paths, and report per-contract outcome (`ok` / `missing_required_fact` path list / other code). This single probe would confirm or refute D1 at the contract level rather than by reading.
- Confirm the `NaN` path for `ContentFact.value`.
- Recompute the six SHA-256s in `source_hashes.json` and diff against the frozen files.
- Determine the product's `source_format` for existing projects.

## Recommended Next Step

**For Codex (decision authority):**

1. **Block 3R.4A acceptance on D1 and D3.** D1 makes the summary chapter unbindable for realistic studies; D3 makes the resulting conflict unrepairable. Neither is a polish item. D2 and D6 should be fixed in the same change because they share the alias mechanism.
2. **Approve the three-part D1 remediation** (load-time registered-target invariant; declare the five keys in the contract layer; add a real-contract binding test) — this is small, local, and turns the defect class into a load-time failure.
3. **Choose the D3 policy** — (a) report-not-abort, (b) add a repair path in D, or (c) both with (a) now and (b) in D. Do not ship the current hard abort as the 3R.4A behavior.
4. **Decide the D4 encoding contract** (bare boolean in the store vs. string with declared type) and place the `value_type` enforcement at fact acceptance, not only at chapter binding.
5. **Approve D5's schema addition** (`resolution` field + generated 724-row registration artifact) so the Plan v3 step-3 deliverable exists as an artifact.
6. **Re-run and bind the evidence (D7)** with the Plan v3 line-146 environment, capturing command, env, interpreter, timestamps, recomputed hashes, and JUnit XML into the run directory. Codex owns this.
7. **Fill in the main-venue plan and conference review files**, which are currently `TODO`. The participant assignment table in the plan still lists `opencode-go/muse-spark-1.3-contributor` as the primary for this role; the runner's fallback to `codebuddy-cli/deepseek-v4-flash` should be recorded there with the failure reason, so the routing record matches what happened.

**For the chair:** no sub-venue chair exists for this object, so these are Codex decisions directly.

**Bounded questions for Codex (each blocks a conclusion):**

- **Q1 (D1, blocking).** Were the five canonical keys (`framing.registration_classification`, `contact.sponsor_organization`, `contact.trial_institutions`, `framing.study_overall_duration`, `picos.participation_duration`) intended to be declared in the chapter contracts / registry vocabulary in this round, or is a later module expected to supply them? If later, is the 3R.4A acceptance claim explicitly "projections declared but not yet resolvable," and is `v2_n_1_1` allowed to be unbindable until then? *Why it matters:* it determines whether D1 is a blocker or a documented dependency — and the thirteen rows are `required` today either way.
- **Q2 (D3, blocking for the fix design).** What is the sanctioned way for a user to resolve `fact_alias_conflict` on a confirmed study — a new accepted decision that retires the projection key, an explicit "canonical wins, record the divergence" policy, or something already planned in D? *Why it matters:* without an answer I cannot tell whether the fix belongs in A (soften) or D (repair), and shipping the current abort means the product can enter a state it cannot leave.
- **Q3 (D4, blocking for the test design).** Is `value_type` meant to be enforced when facts are confirmed (write path), or only when a chapter binds (read path)? *Why it matters:* if read-only, the ten boolean declarations can only ever produce late, unrepairable failures, and the acceptance test must be written as "confirmed study with string `\"false\"` fails with this exact code" rather than "bad facts are rejected at entry."
- **Q4 (D5, non-blocking but needed for completeness).** Does the 724-path registration table already exist somewhere I was not authorized to read, or is it still to be produced? *Why it matters:* Plan v3 step 3's "explicitly unsupported list" is a stated deliverable and I found no artifact for it.

**Safe provisional path if Codex cannot answer in-session:** treat D1/D2/D3 as blockers to acceptance, keep D4/D5/D6/D7/D8 as required-but-unblocked fixes, and record the 3R.4A status as "implementation present, acceptance withheld pending addressing and alias-policy decisions." Do not mark 3R.4A complete, and do not let the `72 passed` / `37 passed` logs stand as the acceptance record for the frozen artifact until they are bound to it.

**Resume point:** I completed the whole-workflow pass within the single conference pass; no internal budget boundary was reached. If Codex wants the D1/D2/D3 claims converted from static analysis to executed reproducers, the exact probe to authorize is a read-only Python session with `PYTHONPATH=tests/protocol_v3:services/api:packages:.` that (i) loads the real registry and catalog, (ii) binds all 111 contracts against a synthetic confirmed study, and (iii) prints per-contract outcome plus the five unregistered canonical targets. That probe is blocked only by the Bash denial in this session, not by missing source access.
