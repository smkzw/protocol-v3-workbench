# Conference Participant Output: mw_protocol_v3_replan_review_20260912 - general_single_object

## Boundary Check

- Worked inside runner cwd only. Read-only: no source/test/fixture/doc writes, no servers, no product/model/OCR calls, no web, no credentials.
- Read: `plans/mw_protocol_v3_design_v1.4_20260912.md`, `plans/mw_protocol_v3_implementation_plan_v3_20260912.md`, `plans/mw_protocol_v3_goal_prompt_20260912.txt`, snapshot manifest, `runs/mw_protocol_v3_full_review_20260912/{source_and_graph_summary.json, conditional_probe.json, conditional_probe.py, source_and_graph_probe.py (skim), worker_frontend/diagnostics_20260912.md, frontend_vitest.json (skim)}`, source files `services/api/app/protocol_workflow/registries/{chapters.py, dependency_graph.py}`, `packages/contracts/workbench_contracts/protocol_v3.py` (targeted ranges), `canonical/{study_definition.py, document.py}` + `application/service.py` + `storage/sqlite.py` (grep-targeted), one chapter contract `chapter_contracts/v2_n_11_4_9.json` (full), `runs/MW_PROTOCOL_V3_3R4_NO_LOSS_PAUSE_20260912_2322.md`.
- Did not read other participants' outputs. Did not verify: DOCX re-extraction bytes, R03 68-row claim, style-ID/bookmark bindings, frontend vitest log content, full 724-path ledger, all 14 overlap contracts.
- No final/professional/release acceptance claimed. Codex retains acceptance.

## Independent Work Product

**Verdict: the three frozen documents are directionally sound and the reported 3R.4 defects are genuine, but the plan has five concrete holes that will cause rework or silent scope loss if executed as written. Highest-impact first.**

### F1 (highest impact, blocks V1): the "no interim analysis" case cannot pass its own checker — and it is the common case

- Verified in source, not just diagnostics. `v2_n_11_4_9.json:16-94` declares 12 unconditional `required` fact_requirements (timing, information_fraction, purpose, rules, decision_responsibility, final_analysis_impact, efficacy_alpha_spending, safety_review_alpha_separation, idmc/endpooint-irc responsibilities, canonical_reference) plus one `forbidden` stale pointer.
- The conditional rule `conditional:v2-n-11-4-9:interim` (:219-245) lists 10 of those same paths as `required_when_active`, triggered by `statistics.interim.applicable` with human condition text only.
- The checker (`chapters.py:612-632`) enforces unconditional `required` with no conditional exemption; conditionals are explicitly deferred as `conditional_applicability_not_executed` (:857-858). Probe result confirmed: a truthful "本研究不计划期中分析" fails with `missing_required_fact` errors.
- Consequence for the user-selected sequence: any standard II/III pilot **without** interim analysis — extremely common — cannot reach "全部适用章节初稿" without fabricating interim details. The complete-path-first strategy is correct, but 3R.4B is on the critical path, not parallelizable with V1.3.
- Remediation (concrete): 3R.4B step 3 must (a) demote the 10 overlapping paths in this contract from unconditional-`required` to conditional-only, versioned (contract 3.3.0 → next); (b) define the explicit not-applicable disposition for the remaining unconditional paths — especially `statistics.interim.canonical_reference` (still `required`, :83-88): what value satisfies it when no interim exists? Specify a typed `{"applicable": false, "reason_ref": ...}` convention or split into `applicability` (always required) vs detail paths (conditional). A bare exemption without a canonical-reference disposition will push writers to stuff a dummy reference to turn the checker green. (c) Produce the per-contract matrix for all 14 overlaps before editing — plan step 1 says this, but acceptance must require the matrix as a committed artifact, because "不是删除14条义务" (design §4.2) understates the edit: it **is** deleting unconditional obligations, legitimately, and each deletion needs its trigger/false-disposition recorded.

### F2: string-typed fact plumbing corrupts booleans — the compat shim will perpetuate it unless specified

- Verified: `StudyDefinitionV3.facts: dict[NonEmptyText, JsonValue]` (`protocol_v3.py:654`) vs `ChapterSkillInput.resolved_facts: Mapping[str, str]` (`chapters.py:259`) vs `ContentFact.value: Optional[str]` (:158) and `ContentCell.value: Optional[str]` (:189). Probe: `False`/`True`/`0.5`/`{applicable:False}` all rejected (`string_type`); `"false"` accepted.
- The corruption: `"false"` passes the checker's non-blank test (`(supplied.value or "").strip()`, :615) as *present content*, and `bool("false") is True` in any downstream Python truthiness use. A false boolean round-trips as truthy. Design §4.1 correctly prescribes JsonValue retention + projection for display.
- Hole in plan 3R.4A step 2 ("兼容原字符串输入版本"): with no specified falsy-string rule, the shim preserves the bug. Require: explicit versioned converter `str→JsonValue` with `"false"/"False"/"0"/""/"null"` handling (`"false"→False`, `"0"` ambiguous → reject or map by declared path type from the 724-ledger, never truthy-default), plus widening or typed-parse-back for `ContentFact.value` **and `ContentCell.value`** (plan omits cells; numeric table cells stay strings otherwise). Historical events keep old bytes; converter applies at read boundary with version tag.

### F3: `impact_sha256` is misdocumented in code as an adoption key — plan's fix is right but underspecified on traversal

- Verified: `dependency_graph.py:42` and `impact():308-312` docstrings claim `impact_sha256` is the "adoption key — one adoption per fact update". The digest (:366-376) covers only `(registry_sha256, changed paths, affected sets)` — no project/study-revision/values (evidence summary `hash_scope` confirms). Two confirmed revisions changing the same path collide. Design §5 / plan 3R.4C-step-5 correctly demote it to projection hash.
- Verified traversal defect: `impact()` BFS (:344-360) propagates through consistency edges transitively; summary confirms `bridge_false_positive_c: true` (C{y} pulled in via B when only x changed). Design's A{x}/B{x,y}/C{y} analysis is correct.
- Underspecification: plan step 2 "传播保留具体changed paths" names the ledger, not the algorithm. Require per-path attribution: consistency neighbour admitted **only if it shares ≥1 changed path** with the already-affected set (single-hop-per-path for consistency; keep transitive closure for scheduling dependents). Each affected contract records `via_paths`. Also unexamined: `MembershipSource.CONDITIONAL_WHEN_ACTIVE` (:117) — if conditional facts mint consistency edges, unknown-state facts over-connect the graph. Verification needed (see Q-codex below); if so, exclude unknown-state conditional memberships from consistency edges until the trigger resolves.

### F4: adoption machinery exists and is reusable — but impact→invalidation granularity is unmapped

- Verified present: `StudyDefinitionReducer` CAS replay + `DecisionEffectLedger` (`canonical/study_definition.py:1-27`), service `replay_or_apply`/`build_and_apply` one-transaction CAS+event+outbox (`application/service.py:21-24,445-483`), `save_with_expected_revision` + committed reservation repo (`storage/sqlite.py`). Plan 3R.4D "复用…不建立新平台" is feasible and correctly scoped.
- Hole: CAS identity is `(decision_record_id, snapshot_sha256, expected_state_revision)`; impact reports *contract sets*. Plan step "将typed事实变化、适用性和impact接入一次采用" never states the replay-vs-invalidation rule. Required rule: exact replay returns prior result **only if** no impact since that revision marks the replayed decision's fact paths stale; otherwise the replay path must surface "confirmation stale, re-confirm" instead of silently returning the old result. Without this, 3R.4C's "用户确认已失效" distinction (design §5) has no enforcement point. Add an explicit 3R.4D acceptance case: stale-confirmation replay after an upstream fact change does not no-op.

### F5: the 20-click budget contradicts the shipped UI in two pinpointed ways — both need explicit supersession

- Evidence (worker_02 diagnostics, file/line-cited, credible): v3 backend unreachable from UI (`protocolWorkspaceApi.mjs` zero consumers); legacy path measured ≈120–135 clicks vs 20 budget; one-shot full-draft adoption exists only for greenfield. The budget therefore **requires** the 6R AI-lead rewrite — plan V1.4 admits "旧链逐步抽离" but carries no click-count measurement artifact. Require a click-count assertion harness (worker T5 proposal) before any "V1 meets budget" claim.
- Two concrete contradictions the frozen docs do not resolve:
  1. The 8-card list (design §6.3) includes 非劣效界值 unconditionally, yet design §6.2 says "八类均适用的标准测试必须计入". A superiority trial has no NI margin. Either the card is conditional (same §4.2 logic — needs an N/A-with-reason disposition) or the budget must state whether N/A disposition costs a click. Currently unspecified; a forced NI card on superiority designs fabricates science to satisfy UX math.
  2. "理由AI预填，可改，无最低字数" (design §6.3, Goal §二) vs shipped validators requiring ≥10-char reasons (corpus override, study rebind, template upgrade — App.jsx refs in diagnostics). Unless V1 explicitly supersedes those validators, the build fails the Goal's own rule. Goal §二 must name the supersession; plan V1.4 must list the validator call-sites as in-scope edits.

### F6: broken entry pointer — Goal §一 and plan §9 cite a review file that does not exist

- `reviews/mw_protocol_v3_full_review_20260912.md` not found (glob shows only `codex_execution_mw_protocol_v3_full_review_20260912_review.md`). Correct the pointer to the existing evidence: `runs/mw_protocol_v3_full_review_20260912/{source_and_graph_summary.json, conditional_probe.json, worker_frontend/diagnostics_20260912.md, all_chapters_review.txt, chapter_semantic_inventory.json}`. Small fix, high annoyance cost at resume.

### F7: re-assembly step missing after 3R.4B contract edits

- Design §2 leans on "重新组装…完全相同 / full lint 0错误" as the integrity anchor. Correct scope — but lint checks structural conformance, not semantic executability (it coexists with F1–F3 by construction). After 3R.4B versions ~14 contracts, the assembly hash **must** change. Plan has no explicit re-assemble → re-lint → re-baseline step in 3R.4B acceptance. Add it, or the "组装等于历史制品" anchor silently rots.

### What I endorse (to bound the challenge)

- Complete-path-first sequencing with V1/V2 obligation table (plan §5–§6): preserves obligations on paper; no excluded-safety restoration found in plan text. The 1R.5 `USER_EXCLUDED` guard with "不换名再建" + retained science/format correctness (Goal §六, design §9) is the right line; 3R.4C-step-4 consumer-rejection tests stay inside functional correctness.
- Fact-binding ledger as vocabulary (design §4.1: "合同词汇与事实解析规则，不建新事实数据库") — right non-proliferation call; but 724 rows need an explicit unsupported-path runtime behavior (refuse-with-list vs warn), currently missing.
- Alias/projection warning (`synopsis.sample_size` vs `statistics.sample_size.reproducible_result`): could not verify the alias pair in sampled contracts (sample_size paths confirmed present in `v2_n_11_1.json`); treat as provisional pending ledger.
- `v2_n_13_x` dangling-target claim (plan 3R.4B step 5): my grep over `chapter_contracts/` did not surface it — unverified, see questions.
- R03 "68行/54编号/14无编号", style-ID/bookmark bindings: not independently verified; design §7's ID-vs-name warning is sound regardless.

## Evidence And Assumptions

**Direct evidence (read):**
- Type defect: `chapters.py:150-159, 245-276` (str-only `ContentFact.value`, `Mapping[str,str]` input) vs `protocol_v3.py:654` (`JsonValue` facts); probe `conditional_probe.json:2-30` (bool/number/object rejected, `"false"` accepted).
- Interim defect: `v2_n_11_4_9.json:16-94` (12 unconditional required) vs `:219-245` (conditional rule, 10 overlapping paths); checker `chapters.py:612-632, 857-858`; probe `conditional_probe.json:31-63` (`missing_required_fact` on timing/information_fraction/… for truthful no-interim statement).
- Impact defect: `dependency_graph.py:306-386` (BFS closure, digest scope) vs docstrings `:42, 308-312`; `source_and_graph_summary.json:270-345` (`bridge_false_positive_c: true`, digest inputs, `hash_scope`).
- Adoption exists: `canonical/study_definition.py:1-27, 75-186`; `application/service.py:10-24, 191-194, 441-483`; `storage/sqlite.py:37-54, 1005-1032`.
- UI gap: `worker_frontend/diagnostics_20260912.md:18-23, 44-52` (zero-consumer API, 120–135 click count, dead 风险 tab, dual pollers).
- Pause/handoff: `runs/MW_PROTOCOL_V3_3R4_NO_LOSS_PAUSE_20260912_2322.md` (3R.3 closed, 3R.4 in-flight, HEAD 84488d3).
- Counts: summary `:7-20, 270-275` (111/111, 558 all-defer, 49 conditions, 724 paths, 111/41/43).

**Assumptions / unverified (marked):**
- [INFERENCE] 14-overlap count and full overlap list: probe JSON truncated at 63/337 lines; accepted from probe + plan, not hand-counted.
- [UNVERIFIED] `v2_n_13_x` dangling reference location; R03 68-row split; style/bookmark bindings; `synopsis.sample_size` alias pair; frontend ≥10-char validator call-sites (via worker_02 citations only).
- [INFERENCE] Consistency-edge construction from conditional memberships (membership source enum seen; edge-build code `build_dependency_graph` :504-664 not fully read).

## Risks, Gaps, And Verification Needs

1. **Pilot selection risk**: if the V1 pilot happens to include interim analysis, F1 is dodged, not fixed. Verification: require pilot criteria recorded before V1.1, including at least one interim-free instance (see Q1).
2. **Silent fabrication risk**: post-exemption, writers may fill detail paths with template-flavored text to satisfy shape checks. Verification: 3R.4B acceptance must include a negative case (no-interim content carrying timing/alpha details → flagged as surplus/unapplicable, not passed).
3. **Idempotency-collision risk**: any code already treating `impact_sha256` as a dedup key inherits cross-revision collisions. Verification: grep consumers of `impact_sha256`/`projection_sha256` before 3R.4C; fix docstrings at `dependency_graph.py:42, 308-312` in the same change.
4. **Confirmation-staleness bypass** (F4): replay path must consult impact. Verification: new integration case — upstream fact change → downstream replay returns stale-confirmation signal, not silent prior result; SQLite-backed, concurrent CAS one-win case per plan.
5. **Budget-fabrication risk**: claiming 20 clicks without harness. Verification: click-count assertion artifact in V1.4 evidence; N/A-card click accounting decided upfront (Q3).
6. **Anchor-rot risk** (F7): post-edit assembly divergence misread as regression. Verification: re-assemble/re-lint/re-baseline as 3R.4B exit criterion with new hashes recorded.
7. **Validator-supersession risk** (F5.2): legacy ≥10-char gates silently violate Goal. Verification: explicit supersession list (Q4).

## Recommended Next Step

1. **Codex corrections to fold before unpausing product work** (docs-only, in scope of this review turn): fix Goal/plan pointer to existing evidence files (F6); add to plan 3R.4B acceptance — per-contract overlap matrix artifact + not-applicable disposition for `canonical_reference` + surplus-detail negative case + re-assemble/re-lint step (F1, F7); specify the `str→JsonValue` falsy-string rule and include `ContentCell.value` in 3R.4A (F2); replace traversal description with per-path attribution rule and fix the two `impact_sha256` docstrings in the 3R.4C change (F3); add replay-vs-invalidation rule and stale-replay case to 3R.4D (F4); record pilot criteria, N/A-card click accounting, and validator-supersession list (F5).
2. **Bounded questions for Codex (safe provisional path in parentheses):**
   - Q1: Which V1 pilot instance(s)? Must at least one be interim-free? (Provisional: require one interim-free pilot; V1.3 not accepted on an interim-only instance.)
   - Q2: Exact contract/field of the `v2_n_13_x` dangling target? (Provisional: keep 3R.4B-step-5 open, do not assert it in acceptance until pointed.)
   - Q3: Is the NI-margin card conditional for superiority designs, and does N/A disposition consume budget clicks? (Provisional: treat as conditional with zero-click auto-N/A only when trigger facts decide it; any manual N/A costs one click.)
   - Q4: Authorize modifying the legacy ≥10-char reason validators to honor "无最低字数"? (Provisional: list call-sites in V1.4 scope; do not touch until authorized.)
   - Q5: Intended content of the missing `reviews/mw_protocol_v3_full_review_20260912.md` — rename of an existing file or a new synthesis Codex will write? (Provisional: cite the `runs/` evidence files directly.)
   - Q6: Should conditional-when-active fact memberships contribute consistency edges while the trigger is unknown? (Provisional: exclude unknown-state conditional memberships from consistency edges.)
