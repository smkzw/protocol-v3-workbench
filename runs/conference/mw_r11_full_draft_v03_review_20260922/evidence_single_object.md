I'll start by reading the initial read set.

The source packet is large. Let me read it in chunks, starting with the structure.

Bash is unavailable; I'll use Read/Grep.

Now the candidate sections.

Now let me check the referenced product-goal and generator sources (named in the conference source-of-truth list), and quantify repetition.

Key product-goal and checkpoint context captured. Now let me verify the canonical section template against the 85 produced sections.

This is decisive for the missing-content question. Let me read the canonical template numbering and applicability rules.

Now let me verify against the frozen raw artifact itself.

Let me check how the greenfield section seed is defined, since the candidate's numbering has gaps.

Now let me quantify repetition, meta-text, and policy-leakage signals in the packet.

I have a complete evidence base. Writing the review now.

# Conference Output: mw_r11_full_draft_v03_review_20260922 - evidence_single_object

## Output

### 0. Read set and boundary statement

Read (in this order): the three declared files (`context/...conference_context.md`, `plans/codex_main_venue_...md`, `context/...source_packet.md` in full, all 85 sections). To execute two mandated success criteria ("whether the 85-card presentation supports the AI-lead user goal"; "whether 18 mandatory cards are proportionate") I additionally read four files that the conference context itself lists under **Source Of Truth**: `plans/protocol_v3_fork_execution_20260921/GOAL_PROMPT.txt`, `.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md`, and the two policy sources named in the context — `services/api/app/medical_writing_full_draft.py` and `services/api/app/medical_writing_protocol_template.py`. I did not read `ai_provider_secrets.json`, did not run any model, and modified nothing. Bash was withheld in this session, so I could not compute SHA-256 for the two declared hashes; the frozen JSON is a single line larger than my read-tool line limit, so its internal fields are reported here from the packet and the per-chunk records, not from direct parsing (see §8, V1–V3).

---

### 1. Verdict

| Question (from the objective) | Verdict | Basis |
|---|---|---|
| Adoption readiness of frozen v0.3 full draft | **FAIL** as a submission-bound full draft; **CONDITIONAL PASS** only as a partial scaffold | R1–R4 below; artifact covers 85 of the ~99 applicable canonical headings and 83/85 sections carry zero corpus evidence |
| Unsupported project-specific rules | **CONFIRMED, 4 instances** (2 inside mandatory cards) | R5 (4.4, 14.1, 9.5, 10.3) |
| Cross-section inconsistency | **CONFIRMED, 5 categories** | R6 |
| Excessive repetition | **CONFIRMED, quantified** | R7 |
| Missing submission content | **CONFIRMED, 14 headings absent** (10 body + 4 carrier nodes) | R1 |
| Are 18 mandatory cards proportionate? | **Not the right question — the set is mis-scoped, not oversized** | R2 |
| Review-only changes required | Yes; no source/runtime modification proposed | all remediations are text/decision-level |

**Highest-impact defect (my lead finding).** The frozen v0.3 artifact is not a complete full draft and the 18-card projection cannot see what is missing. Reconstructing the applicable section set from the canonical template (`medical_writing_protocol_template.py:398-523` combined with the conditional-prefix removal at `:525-533` and `:783`) yields ~99 headings; the artifact contains 85. Absent: `1.1 方案摘要`, `1.2 研究示意图`, `1.3 研究流程表`, `2.5 获益/风险评估`, `3.2 次要目的和次要终点`, `4.2 设计依据`, `5.1 计划入组人数`, `6.2 研究治疗给药`, `7.2 有效性评估`, `9.1 样本量`, `9.2 统计分析数据集`, `9.3 统计分析一般原则`, `9.4 有效性数据分析`, `13 参考文献`. I verified independently that none of the strings 计划入组人数 / 次要目的和次要终点 / 研究治疗给药 / 有效性评估 / 统计分析数据集 / 获益/风险评估 / 设计依据 occurs anywhere in the packet (not as a heading, not in an evidence note). The generator only targets *blank* applicable sections (`medical_writing_full_draft.py:175-205`, `_is_substantive` at `:124-126`), so these were either already substantive outside this artifact or marked not-applicable. Either way: **"raw coverage 85/85" is coverage of the target list, not of the document**, and the decisions with the highest consequence — 样本量, 剂量/研究治疗给药, 有效性评估, 次要目的和次要终点, 计划入组人数, 设计依据, 获益/风险评估 — have no card in the 18-card queue and no section in the frozen artifact. Their content survives only as duplicate prose inside §1, §4.2.1 and §9.

**Second-highest (the one I would fix first, because it is a medical-accuracy risk).** Two mandatory cards contain requirements that revision 8 does not support, and in both cases the section's own evidence note warns against exactly that:
- §4.4 盲法与揭盲 (required) — "受试者、研究者、监查员及数据分析人员等对治疗分配保持盲态" and "任何个体揭盲均需记录触发原因、时间、处理措施和结果". Revision 8 has `blinding_mode: double_blind` but `blinded_roles: []` and `blinding_details: ""`. The role list and the individual-unblinding documentation duty are invented. The note itself says "所引证据未规定具体揭盲流程，不应将未确认流程写为既定要求."
- §14.1 避孕的规定与方法 (required) — "具备生育能力的受试者应维持持续、正确的避孕措施，…并在双盲治疗期及安全性随访期内保持执行" plus "确保避孕与妊娠管理在本研究各中心得到统一执行". Revision 8 provides no contraception rule, and §14.1's own note says methods/duration/pregnancy-test timepoints are undecided and that another project's Phase I list "不可直接沿用."

A user clicking "确认" on these two cards would be confirming fabricated project rules. That is worse than a missing section, because the workflow records the confirmation as an authoritative human decision.

---

### 2. R1 — Missing content (P0)

| # | Absent heading | Canonical source | Why it matters | Smallest correction |
|---|---|---|---|---|
| 1 | `3.2 次要目的和次要终点` | `template:413` | Study A *has* two key secondary and two other secondary endpoints; they exist only inside §1/§3/§9 prose | Create the section, move the secondary-endpoint block from §3, add multiplicity statement (see R6-3) |
| 2 | `7.2 有效性评估` | `template:460` | The section that must define PASI/sPGA/DLQI administration, evaluator, timing, training is absent while §7.3 安全性评估 exists — asymmetric chapter | Create it; §14.2 content is the natural seed, plus DLQI timing decision |
| 3 | `6.2 研究治疗给药` | `template:445` | Dosing administration (time of day, missed dose, rescue) is the section whose absence §6's own note flags ("给药时点、漏服处理…") | Create it; no new facts needed, only the open decisions |
| 4 | `5.1 计划入组人数` | `template:434` | 132例 (66/66) appears only inside other sections; a submission protocol states it as its own item | Create it from `sample_size_strategy` |
| 5 | `4.2 设计依据` | `template:422` | Artifact contains an orphan `4.2.1 确证性设计与假设依据` with no parent `4.2` — visible structural defect in the rendered document | Restore parent heading during adoption/rendering |
| 6 | `9.1–9.4 样本量 / 统计分析数据集 / 统计分析一般原则 / 有效性数据分析` | `template:485-488` | Analysis-population definitions (FAS/PPS/Safety membership) have no home; "全分析集包括所有随机受试者" (§9) is an inference, and safety-set membership is undefined | Create the four sections; make population membership an explicit decision |
| 7 | `2.5 获益/风险评估` | `template:410` | Required by the template for a confirmatory study; absent | Create as decision item |
| 8 | `1.1/1.2/1.3 方案摘要/研究示意图/研究流程表` and `13 参考文献` | `template:400-402,516` | Structurally excluded by `node_kind` filter (`medical_writing_full_draft.py:182`), so no full-draft run can ever produce them; a submission package needs the schema and SoA | Either state that these are produced by the template/export layer, or extend the generator's node_kind allow-list |

Confirmed **not** defects: `4.2 phase1 parts`, `4.5/4.6/4.7` (M11 numbering), `5.6 参与者替换`, `6.6.3/6.6.4`, `7.4–7.8`, `8.8 特别关注的不良事件`, `9.6–9.11` are conditional and correctly absent for a Phase III study without PK/PD/AESI/interim/multiplicity-feature flags. **One exception needs a decision, not silence:** `6.6.4 补救治疗` is absent because `feature:rescue_therapy` is unset, yet revision 8's `estimand_strategy` explicitly says "停药或使用救援治疗按复合策略判定为无应答". A rescEU definition therefore has no section and no decision (see Q3).

### 3. R2 — The 18-card set: mis-scoped, and the wrong granularity

Provenance reconstructed from `medical_writing_full_draft.py:56-86,357-396`: `required` = (heading matches one of 25 whitelist patterns) **or** (`corpus_spans>0` **and** `_CORPUS_CONDUCT_RE` matches the body). Verified: 18 = 17 heading-based + `12.7 质量控制与保证` (corpus-triggered, reason "正文使用跨项目语料支持研究实施规则"). Consequences:

1. **Whitelist targets sections that do not exist here.** The whitelist names `样本量.*`, `(主要)?估计目标.*`, `非劣效.*`, `期中分析.*`, `多重性.*`, `剂量选择.*`, `对照选择.*`. No section heading in the artifact matches any of them, so those mandated confirmations (GOAL_PROMPT.txt line 15: 样本量假设、估计目标及伴发事件策略、剂量、对照…"需要逐项可见的人审确认") are silently absent rather than satisfied. They are only tangentially covered inside §1 and §4.2.1.
2. **Corpus escalation is a keyword artifact.** Among the three sections that actually cite cross-project corpus text, only one is escalated: §12.7 (corpus 2) fires because its body contains "不良事件记录"; §12.3 稽查和核查 (corpus 2) and §10.3 数据质量保证 (corpus 1) do not match the regex and stay `standard`, although §10.3's body imports another project's QA/audit division of labour.
3. **False positives in the adjacency rule.** `_DESIGN_RESTATEMENT_SIGNALS` fires on the bare words 随机/双盲/mg/主要终点/计划入组N例. §4.3 随机化 and §4.1 总体设计 are therefore advised to "压缩" for using their own topic vocabulary, while genuinely duplicative sections (§7.1.2, §5.2, §12.1–12.6) are not flagged at all.
4. **Granularity is inverted.** One card = one whole section: §1 方案概要 is a single card bundling ~20 discrete facts (title, phase, region, design, five eligibility thresholds, N=132, 1:1, 16-week duration, 100 mg QD, four endpoint tiers, three study periods, visit grid, CMH/FAS/NRI, no-interim). Meanwhile §4.6/§5.5/§7.1.3/§8.4–8.7 (pure scope prose) are also cards. So the queue mixes "confirm a scientific choice" with "read a paragraph", with no visual separation beyond the reason string.
5. **Click budget.** GOAL_PROMPT.txt line 17 caps critical-path clicks at ≤20. 18 sequential mandatory confirmations leaves ~2 clicks for import → confirm facts → generate → adopt → export. That is the concrete proportionality problem, not the number 18 per se.

Recommended alternative (bounded, no new subsystems): keep section cards for reading, and derive the mandatory queue from **decision items** rather than headings — i.e., confirm the ~10 scientific choices the GOAL already names (primary endpoint, estimand/ICE incl. rescue handling, sample-size assumptions, comparator, dose, core population, no-interim/alpha, multiplicity, efficacy-assessment instruments/timing), each attached to the section that owns it, with §1 downgraded to a summary card that carries no confirmable decision. That both shrinks the queue and removes the current double-counting of a decision (once in §1, once in its owning section).

### 4. R3 — 67 vs 18: the projection is not reconciled (P0 integrity)

The packet records `Raw coverage: 85/85; raw required cards 67` in the same "Identities" block as `Current read-time review projection: protocol_full_draft_review_v0_2; required cards 18`. The artifact persists its own `coverage.required_review_count` computed at write time (`medical_writing_full_draft.py:771-792`), while the v0_2 reading path recomputes from the persisted per-section `evidence_summary` (`:441-458`). A 73 % reduction between the number stored in the frozen artifact and the number the current code shows to the user means the mandatory count the user sees depends on which code version renders it, and no reconciliation is recorded anywhere I can read. This must be resolved before any acceptance statement about "18 cards", because both the proportionality discussion and the "was the user asked to confirm the right things" claim depend on it. **Verification command for Codex** (I could not run it): `python -c "import json,pathlib;d=json.loads(pathlib.Path('<frozen full-draft.json>').read_text());print(d.get('review_policy_version'),d['coverage']['required_review_count'],[s['section_number'] for s in d['sections'] if s.get('review_level')=='required'])"`.

### 5. R4 — The corpus is used where it is most dangerous and unused where it matters most (P1)

Evidence counts in the packet: 83/85 sections report `corpus 0`; only `10.3` (1) and `12.3` (2) report corpus spans >0. Meanwhile the earlier job's chunk record (`mwjob_ca1eb8feb6baceb8d4fb9eb7/chunks/chunk-0001` `source_ids`) shows `company_corpus:cms_cn_protocol_corpus_20260715_v1:…` bindings were attached. So the corpus was available and was ignored almost everywhere, appearing only in two management-boilerplate sections where cross-project carryover is exactly the risk the product warns about. Combined with `FULL_DRAFT_MINIMUM_BODY_CHARS = 80` (`:49`) and the instruction "每章至少{minimum_body_chars}个中文字符" (`:333`), the observable behaviour is: sections whose real content class has no admissible source (`2.1 疾病背景及治疗现状`, `2.2 作用机制及同类药物研究进展`, `2.3.1 非临床研究结果`, `2.3.2 既往临床研究结果`, `2.4 本研究的理论基础`) were filled with design restatement to clear the length floor. §2.1 contains no epidemiology, disease burden, or treatment landscape; §2.2 contains no mechanism, target, or competitor data; §2.3.1/§2.3.2 contain no nonclinical or prior-clinical findings; §2.4 contains no rationale. That is minimum-length compliance masking missing content — the defect pattern the objective calls "omission hidden by generic prose." Recommended fix: mark such sections as **source-gap** items (a third state with a named required source class), excluded from the length gate and excluded from "coverage", instead of filling them with neighbouring sections' facts.

### 6. R5 — Unsupported or mis-registered rules and statements

| ID | Section | Statement | Revision 8 state | Fix |
|---|---|---|---|---|
| R5-1 (P0) | §4.4 (required) | blinding role list; mandatory documentation of every individual unblinding; "预先规定的程序" | `blinded_roles: []`, `blinding_details: ""` | Delete role list and documentation duty; convert to open decisions or a clearly labelled placeholder |
| R5-2 (P0) | §14.1 (required) | ongoing contraception requirement for all subjects of childbearing potential; system-wide uniform execution | no contraception/washout rule in `picos` (`washout_rules: []`) | State only the supported part (pregnancy/lactation excluded); list methods/duration/testing as pending decisions |
| R5-3 (P1) | §9.5 (standard) | "按系统器官分类和首选术语对不良事件进行汇总", "安全性数据以描述性统计为主，不进行正式的优效性检验", separate tabulation rules | revision 8 gives only "安全性集按实际治疗分析" | Mark as SAP-backing statements requiring SAP agreement, or move to the SAP |
| R5-4 (P1) | §10.3 (standard) | QA/audit division of labour ("研究中心质量保证人员…抽查", "申办者…不同范畴的稽查") | not in revision 8; section's own note says corpus examples "不应外推" | Same treatment as §12.7, or remove the specific role split |
| R5-5 (P2) | §4.6 (standard) | "不宜以固定清单或时限替代个案评估" | no rule in revision 8 | Normative commentary, not protocol text; replace with an explicit "待研究者与申办者确定" decision, or accept as deliberate |
| R5-6 (P2) | §10.1 | "与PASI、sPGA和DLQI等评价时点保持一致" | DLQI timing is undefined (only "第16周DLQI评分较基线的变化") | Add DLQI timing to the open-decision list |
| R5-7 (P2) | §4.2.1 / §9 | "采用CMH方法" as the primary comparison with **no** stratification factor declared anywhere | `randomization_details: "随机分配"`, no strata field | Resolve: either name the stratum (e.g., centre) or switch to an unstratified test. §4.3's note asks about stratification, but no body text or decision records it |

Instrument registration gap (P1): `picos.assessment_instruments` registers **only PASI** (with `rights.status: unknown`, `translation.status: unknown`, `version_label: ""`). sPGA is used as a key secondary endpoint with a scoring rule (0/1, ≥2-grade improvement) and DLQI as an other secondary endpoint, but neither exists as an instrument record. §14.2 (standard, not required) is the only section defining them, and PASI's licence/Chinese-version status is never surfaced. Add instrument records for sPGA and DLQI, and surface the PASI rights/translation state as a decision.

### 7. R6 — Cross-section consistency

1. **Contraception, contradiction between two sections.** §14.1 requires subjects of childbearing potential to maintain contraception throughout treatment and follow-up; §7.3.4 妊娠检查和避孕问询 explicitly declines to state any contraception requirement and lists it as undecided. Two sections, opposite postures, one of them a mandatory card.
2. **Body contradicts its own evidence note.** §4.4 and §14.1 (as above); §3.3 asserts "本方案不将未经确认的指标列为探索性终点" while its note says the project "未单独列出探索性目的或探索性终点" — the body converts an unpopulated field into a negative design decision.
3. **Secondary-endpoint inference.** §9 lists key secondary endpoints but states no testing strategy; §4.2.1 declares superiority for the primary only. For a confirmatory study with two key secondary endpoints, the alpha strategy is a required project decision and is absent from revision 8 — it must appear as a decision, not as silence.
4. **Estimand wording appears only inside summary sections.** "治疗策略…停药或使用救援治疗按复合策略判定为无应答" is quoted in §9 (and echoed in §1); it never becomes its own confirmed item, and the rescue-therapy section was dropped as not-applicable (R1 note).
5. **Adaptive design unaddressed.** `structured_design.adaptive_design.planned` is `null` and `adaptive_type` is `"undecided"`; no candidate section mentions adaptive design at all. The artifact neither states nor denies it, and the canonical design-rationale sections (`4.2.5 适应性或新颖试验设计的依据`, `4.2.6 期中分析的依据`) are outside the produced set.

Verified consistent (no divergence found): every number in the 85 sections matches revision 8 — 132例 (66/66), 60 %/30 %, α=0.05 two-sided, 90 % power, 15 % dropout, 100 mg QD day 1–week 16, 1:1, 16-week double-blind period, 4-week safety follow-up, visits weeks 2/4/8/12/16 and week 20, PASI/sPGA at baseline and weeks 4/8/12/16, PASI≥12, BSA≥10 %, sPGA≥3, age≥18, duration≥6 months, PASI 75 primary, sPGA 0/1 + ≥2-grade and PASI 90 key secondary, PASI change and DLQI change other secondary, FAS/CMH/NRI/sensitivity analyses, safety set by actual treatment, no interim analysis. The stated sample size is also arithmetically consistent with its own assumptions (≈56 evaluable per arm, ÷0.85 → 66). This fidelity result is a genuine strength of the candidate and should be carried into any remediation so that repairs do not disturb it.

### 8. R7 — Repetition, quantified

- 11 sections carry the advisory "本节重复了多项总体设计事实" (§2, §2.2, §2.3, §2.3.1, §2.3.2, §2.4, §4.1, §4.2.1, §4.3, §6, §9); 8 carry "本节提及高影响设计信息" (§2, §2.1, §2.2, §2.3.2, §2.4, §3.3, §8.1, §14.2) — 19 advisories over 15 distinct sections, i.e. **18 required + 15 advised = 33 of 85 sections carry review signal**, on top of the reading load of the other 52.
- "基线及第4、8、12、16周" appears on 17 lines of the packet; "132例" on 5; "基线及第1天…第20周" visit grid on 4+; the inclusion-criteria sentence is restated in §1, §2, §2.1, §5, §5.2, §5.3, §7.1.1.
- The generator's own instruction already forbids this outside four headings: "除方案概要、研究设计、目的终点和样本量章节外，不要重复整套样本量、剂量、主要终点、随机和盲法信息，只写与本章节直接相关的事实" (`:350-351`). The background chapter violates it systematically.
- Separately, 73 lines contain 本章节/本部分/本节 and 6 contain 本节应覆盖 — the draft's body reads in places as a scope memo ("本章节界定…范围", "本节应覆盖…", "本节为严重不良事件…提供概念与范围基础") rather than protocol text. That register is a direct readability cost for the target user.
- Positive control: no placeholder tokens (待补充/待确认/TBD/不适用/由方案规定) and no internal transport vocabulary (当前项目已确认/公司语料/章节包/候选正文) were found in section bodies; those strings occur only in user-facing evidence notes, which is where they belong.

### 9. R8 — The 85-card presentation against the AI-lead user goal

The goal is a "lazy, visually sensitive, computer-and-AI-inexperienced senior medical writing" user who must reach "格式标准、内容有依据、能够进入申报审核" mainly by clicking. Against that: 85 section cards, 18 sequential confirmations inside a ≤20-click budget, 33 sections carrying review signal, and a background chapter (§2–§2.4) whose five cards contain no usable substance. The presentation therefore spends the user's attention on sections that cannot be acted on and starves the sections that can (missing 样本量/剂量/有效性评估/次要终点 sections). My recommendation is the three-state presentation in §3 above plus a **gap list ordered by submission impact** — that is the artifact that would let this user act, and it is a rendering/projection change, not a content rewrite.

---

### 10. Objections, decision points, bounded questions

**Objections to the current framing.**
1. "Is 18 proportionate?" is unanswerable while 67 is also recorded for the same artifact (§4). Resolve the count first, then judge scope.
2. A verdict of FAIL/UNVERIFIED on the artifact risks being read as "the content is wrong". The opposite is true for fidelity: the produced text tracks revision 8 numerically everywhere I checked. The failure is *coverage and decision-scoping*, so acceptance language should separate "content fidelity" (largely PASS) from "document completeness and review scoping" (FAIL).
3. Codex's plan step 2 states "Review all 85 sections …" — that inherits the artifact's self-defined scope. Add step 2b: reconcile the produced set against the canonical applicable set before reviewing, otherwise the missing-section class is invisible to the whole conference.

**Bounded questions for Codex (each blocks a conclusion).**
- **Q1.** Does the project document (isolated runtime) actually contain `3.2/4.2/5.1/6.2/7.2/9.1–9.4/2.5/13` as sections with substantive working-copy text, or were they filtered as not-applicable? *(Determines whether R1 is "artifact is a partial fill" or "seed/applicability is wrong". Safe provisional path: treat all 10 body headings as unverified-coverage and do not accept a completeness claim either way.)*
- **Q2.** Which count is authoritative for acceptance — the persisted 67 or the read-time 18 — and which review policy version will render the user's queue? *(Determines whether the user was asked to confirm the right decisions.)*
- **Q3.** Is rescue/background therapy intended to exist in this study? `6.6.3/6.6.4` were dropped while `estimand_strategy` references rescue treatment. If yes, the rescue definition is a required decision that currently has no section and no card.
- **Q4.** What stratification factor, if any, backs the CMH test (§4.2.1/§9), and who owns the multiplicity strategy for the two key secondary endpoints?
- **Q5.** Are sPGA and DLQI intended to be registered instruments (version, scoring range/direction, licence, timing), and is the PASI Chinese-version licence/translation state (`unknown` in revision 8) an accepted open decision?

**Safe provisional path while waiting:** do not adopt v0.3; freeze it as evidence; apply R5-1/R5-2 as content corrections and R2/R3 as projection corrections; treat R1 as an explicit, user-visible gap list rather than filling it silently.

### 11. Uncertainty and unverified items

- **V1** — Candidate SHA-256 `c2e98124…` and StudyDefinition state SHA-256 `3989470f…` were not recomputed (no shell in this session). Identical-quantity checks rely on the packet.
- **V2** — The frozen `full-draft.json` internals (`coverage.required_review_count`, `review_policy_version`, per-section `review_level`) were not parsed directly; my 67-vs-18 finding rests on the packet's Identities block.
- **V3** — The canonical applicable-set count (~99) is my reconstruction from `_COMPANY_CHAPTERS` + `_CONDITIONAL_PREFIXES` + the renumbering rule at `:783` and the comment at `:396-397`. The "14 missing" list is a difference of two reconstructions, not a direct read of a document manifest; it should be re-derived by Codex against the project's actual document.
- **V4** — Corpus-vs-admission state: the checkpoint records that Study A stopped before corpus admission and was later reconfirmed with `projection: corpus_projected`; earlier chunk evidence shows corpus source bindings were attached. I did not verify whether the frozen run's corpus usage was admissible under that projection, so §5 is stated as an observation about usage patterns, not a governance breach.
- **V5** — I did not verify the rendered Word/Office artifact, so "orphan 4.2.1 renders as a defect" is an inference from the heading list; Codex owns rendered inspection.

Compact evidence trail: packet lines 406–1634 (85 sections, headings/self-reported evidence counts/reasons); packet lines 15–403 (revision 8 extract: `blinded_roles: []` L320, `comparator_summary` L258, `estimand_strategy` L259, `sample_size_strategy` L289, `statistical_strategy` L293, `visit_strategy` L299, `intervention_dose_regimen` L268, `assessment_instruments` L199-255, `unresolved_paths` L384-402); `GOAL_PROMPT.txt` L15/L17; `checkpoint.md` L9/L86; `medical_writing_full_draft.py` L49, L56-86, L124-126, L175-205, L324-351, L357-396, L441-458, L771-792; `medical_writing_protocol_template.py` L396-397, L398-523, L525-533, L783; earlier job chunk `mwjob_ca1eb…/chunks/chunk-0001` (corpus source bindings, same first-chunk section ids); frozen job chunk `mwjob_ccfa…/chunks/chunk-0001` (`corpus_spans: 0`, `project_fact_spans: 20`).
