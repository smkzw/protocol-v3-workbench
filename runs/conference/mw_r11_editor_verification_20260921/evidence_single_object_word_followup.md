Now let me look for the template structure and any prior evidence about the front-matter boundary.

Let me verify a load-bearing assumption: what `style.name` returns for this template's heading styles.

Bash is denied in this session, so no unzip/inspect of the real DOCX, no test run, no render. Everything below is from Read/Grep/Glob over the source, the template registry, and the repo's own template body dump. I did not rerun the owner's tests, did not open `cover-fixed.docx`, and do not claim native Word pagination or citation-interop validation.

---

# Conference Output: mw_r11_editor_verification_20260921 - evidence_single_object (WORD follow-up)

## 0. What I verified independently (not the owner's account)

I reconstructed the real front matter from `runs/mw_protocol_v3_3r4b_20260912/fresh_review_20260913/source_template_body.json` (same source sha as `config/.../tp_ma_07_v2/template.json:122`) and `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/node_tree.json`. It contradicts the owner's shorthand in two useful ways.

| body_child_index | content | source |
|---|---|---|
| 0–22 | 模板说明 / 如何使用此模板 / 删除说明 | `source_template_body.json:9-124` |
| 23 | cover title, contains `XXXXXX` + `安全性的` + `临床研究` | `:124` |
| 40, 41, 45, ~79 | listed instruction strings | `:209`, `:214`, `:234`, `:595` |
| **42** | **confidentiality notice, extracted text contains the phrase TWICE** (`…保密声明本文件包含重要的保密性商业信息…` repeated) | `:219` |
| 66 | 申办者签字页 | `:146` in `node_tree.json` |
| 84 | 临床试验相关单位联系方式 | `node_tree.json:178` |
| 99 | **`目 录` — note the ideographic space** (`node_tree.json:359` `title_zh: "目 录"`) | `source_template_body.json:867` |
| **100** | **the template's TOC field code AND its first cached entry + page number**: `TOC \o "1-3" \h \z \u  HYPERLINK \l "_Toc132623298" 方案修订历史记录 PAGEREF _Toc132623298 \h 5` | `source_template_body.json:872` |
| 101–118+ | remaining cached TOC entries (`目 录 … 11`, `表目录 … 16`, `图目录 … 17`, `1. 方案摘要 … 18`) | `:877-917` |

**The front-matter boundary itself is correct, and I want that on the record so it is not re-litigated.** `_find_toc_end` (`word_export_production.py:133-136`) normalises whitespace, so `目 录` matches `'目录'`; `front_limit` therefore lands on body child 99, and step 2 (`:248-253`) fires `seen > front_limit + 1`, which I recomputed: the first body `w:p` with index `front_limit+1` has `seen = front_limit+2 > front_limit+1`, so retained = paragraphs `0..front_limit` inclusive. **The TOC field `begin` lives in body child 100, i.e. outside the retained range**, so the old "cache treated as body / unclosed field" defect cannot recur from this arithmetic. The `front_limit -= instruction_end` adjustment (`:197`) and the per-removal decrement (`:241`) are both arithmetically right, and 1b's snapshot slice `[:front_limit + 1]` is consistent with its own decrements.

Non-gating boundary facts also worth recording: `doc.paragraphs` and step 2's `seen` counter are the same set (body-level `w:p` direct children), so the two index spaces agree; `_find_toc_end` returns the first match and the cached entry at body child 105 normalises to `目录11`, not `目录`, so there is no false boundary match; the 目录 heading is excluded from the cache by text (`:315`) while Word's regenerated `\o "1-3"` TOC will include it — the template's own cache listed `目 录 … 11`, so cache and post-update result will disagree by at least that entry.

---

## 1. Repairs that hold up

- **Blank instruction page** — `instruction_end` takes the **last** page break before the title (`max(...)`, `:186-188`), so an earlier break inside the instruction block cannot be mistaken for the page end; the removal range is contiguous and the title paragraph's runs are all rewritten (`:191-196`), which also clears any `w:br[@w:type='page']` living in the title's runs (python-docx's `Run.text` setter clears run content). The mechanism is sound for the page-break representation it targets. Not verified: the rendered result (predates the final repair, and I did not open the artifact).
- **Balanced TOC field** — `begin`/`instrText`/`separate` each get their own run (`:317-327`) with `xml:space="preserve"` on the instruction text, `w:dirty` on begin, exactly one `end` (`:383-385`), and `w:updateFields` inserted **before** `w:compat` (`:425-431`) with the correct reason (settings.xml child sequence). The global depth walk in the test is a genuinely good oracle.
- **Nested textbox alternatives** — `next(node.iterancestors(qn('w:p')), None) is wp` (`:212-213`) is the right predicate: a `w:t` inside a nested textbox paragraph resolves to the inner `w:p`, so the outer anchor paragraph contributes no nodes and the Choice/Fallback branches are rewritten independently. Body child 42 confirms the defect was real (extracted text doubled).
- **`_expand_signature_pages` is not orphaned by this repair** — 申办者签字页 (body 66) and its terminator 临床试验相关单位联系方式 (body 84) are both **inside** the retained front matter, so the expansion still finds its section. Worth stating because the changed boundary could plausibly have killed it.
- **`_TABLE_REF_RE` / `_attach_ref_field`** unchanged and still field-per-run, i.e. schema-valid.

---

## 2. Concrete problems

### P1 (HIGH, oracle hole in the new textbox test) — the test cannot distinguish "de-duplicated" from "one branch deleted"

`test_production_export_ownership.py:168-172`:
```python
nodes=[node.text for node in doc.element.body.iter(qn('w:t')) if '本文件包含重要的保密性商业信息' in (node.text or '')]
assert nodes
assert all(text.count('本文件包含重要的保密性商业信息')==1 for text in nodes)
assert all('合成申办者' in text for text in nodes)
```
A "fix" implemented as *delete the `mc:Fallback` branch* leaves exactly one `w:t`, count `1`, sponsor present, user text intact → **the test passes**. The only oracle for branch survival is a count that the deletion reduces rather than raises. Since the stated repair is "replace per nearest paragraph so alternatives are not concatenated", the test must also pin that both representations survive: assert the number of `mc:Choice` / `mc:Fallback` containers (or `w:txbxContent` occurrences) reaching the export equals the template's, and that the two branches' text is equal after replacement. The oracle was correctly de-coupled from the concatenated phrase; it is still coupled to the wrong invariant.

### P2 (MEDIUM-HIGH, fail-open) — the bounded instruction list has no failure or report path, and leftovers are already observed

- Matching is exact whole-paragraph equality after `.strip()`: `para.text.strip() in template_instruction_texts` (`:238`). One punctuation or whitespace difference silently retains the instruction.
- `_find_toc_end` **fails closed** (`:168-169` raises `production_export_front_matter_unresolved`), and `_replace_in_headers_footers` swallows per part only. The instruction removal has **no** equivalent gate and no diagnostic — the receipt (`:437-445`) reports `engineering_marker_hits` but nothing about retained template instructions.
- The leftovers are not hypothetical: the round-11 handoff records them — `runs/requirements_v2_20260919/t17_round11/TAKEOVER_REVIEW.md:69` 「仍见模板蓝色说明残留」.
- The list is small relative to the retained region. The retained front matter is body children 0..99 and includes an entire example apparatus beyond the six listed strings: the bracketed 主要研究者签字页 example at body 51 (`[我已阅读此临床试验方案（方案编号：<编号>…）…`), the signature date line at body 58, and the confidentiality textbox at body 42 (retained deliberately — the test demands it). Some of these are legal/structural rather than instructions, which is exactly why the removal should be **reported** rather than silently enumerated.
- Fragile coupling from ordering: `:198` and the deep sweep `:208-224` both run **before** 1b, so the list is matched against placeholder-substituted text. None of the six strings currently contains a placeholder token, so it works today by luck; any future entry containing `<编号>`, `XXX`, `vX.X 版`, etc. stops matching after `:198` rewrites it.
- Smallest coherent repair: keep the list, but (a) match on the pre-sweep text, (b) emit a `retained_template_instruction_candidates` diagnostic (paragraph text + index) built from the same instruction markers, and (c) fail closed — or at least warn in the receipt — when the instruction-page anchor (`title_idx`, `:179-181`) is not found. Note the anchor is heuristic and silently fail-open today: if the cover title falls outside `paras[:40]` or loses `临床研究`/`XXXXXX`/`安全性的`, `title_idx` is `None` and the entire instruction page ships with no error.

### P3 (MEDIUM, unverified risk, high blast radius) — front-matter removals can destroy in-body section properties

`:189-190` and `:237-241` remove `w:p` elements outright. Only the **body-level** `w:sectPr` is explicitly preserved (`:259`). A `w:pPr/w:sectPr` carried by a removed paragraph is a section break, and deleting it merges sections — which can change which header/footer the cover uses and where page numbering restarts. The template has 8 sections with per-section header/footer refs and page-numbering types (`test_tp_ma_07_v2_registry.py:591-598`), and `_prune_orphaned_media`'s own comment (`:454-455`) confirms header/footer parts are bound through `sectPr` r:ids.

Two things make this worse than a theoretical risk: the **removal range changed in this repair** (the old behaviour removed non-empty paragraphs; the new behaviour removes the whole `0..instruction_end` span and the whole page), and **no test asserts the exported section count or that the cover still owns its header/footer**. Checkable in one pass: count `w:sectPr` before/after and diff `doc.sections`. Cheapest fix: before removing a paragraph, move its `w:pPr/w:sectPr` onto the nearest retained neighbour; at minimum, record the dropped-section count in the receipt.

### P4 (MEDIUM, unverified, load-bearing) — the "current heading cache" depends on a style-name casing convention that no test pins against this template

`word_export_production.py:314`: `p.style.name.startswith('Heading')`. The same convention is used at `:274` (`paras[i].style.name == 'Heading 1'`) to find the signature-page section end. The template's own extracted styles.xml records these headings as **`heading 1`** in lower case — `node_tree.json:357-359` (`style_id: "2"`, `style_name: "heading 1"`, `title_zh: "目 录"`), and the registry's extraction algorithm reads `w:name` verbatim from styles.xml (`template.json:76`).

The repo's tests that assert capitalised names (`tests/test_medical_writing_docx_pagination.py:564,607`; `test_medical_writing_style_profile.py:257,313`) all run against documents whose styles python-docx itself created, so they cannot settle the behaviour on a Word-authored template. If `style.name` returns the internal name for Word-authored built-in styles, then `toc_titles` (`:313-315`) contains **only** the titles appended at `:352` and none of the retained front-matter headings — and nothing detects it, because `test_generated_table_of_contents_has_balanced_fields_and_no_template_page_cache` asserts field balance and the absence of one cached string, but never that the front-matter headings are in the cache. The same wrong answer would also misplace the signature-section terminator at `:274`. This is a two-minute probe (print the style names of the exported front matter) and should be settled before the cache is called "current".

Secondary inconsistency in the same construct: `toc_titles` is collected **after** `_expand_signature_pages`, so the two clone headings enter the cache, and `目录` is excluded by text (`:315`) although Word's regenerated `\o "1-3"` field will include it. The pre-update cache is therefore not a faithful preview of the post-update TOC — acceptable as a placeholder, but it should not be described as the current heading list without that caveat.

### P5 (MEDIUM, content fidelity) — the per-paragraph rewrite flattens runs, so `w:br`/`w:tab` inside a rewritten paragraph are lost

Deep sweep `:216-224`: `joined = ''.join(w:t)` then `nodes[0].text = new_text` and every other node blanked. Any `w:br`, `w:tab` or `w:drawing` **between** those `w:t` nodes is no longer positioned between text, so a line break inside a paragraph that also contains a replaced placeholder disappears; a tab becomes nothing. The identical pattern existed at `:106-109`; the repair extends it to every body paragraph, including retained front-matter textboxes (body 42 is rewritten, since `<申办者名称>` → sponsor is exactly what the test asserts). The user body is added later (`:342-377`) and is therefore unaffected, so this is front-matter/cover fidelity rather than an R4 breach — but it is un-tested and it is a silent layout mutation. One targeted test is enough: a paragraph shaped `w:t("A" + placeholder)` / `w:br` / `w:t("B")` must keep the break after export.

### P6 (MEDIUM, contract boundary) — export-time generation of the signature pages is defensible but unreported and untested

`_expand_signature_pages` (`:265-309`) deep-copies the 申办者签字页 section twice, rewrites party lines (`'申办者：'`→`'合同研究组织：'` etc., `:298`) and overwrites the first paragraph's text (`:303`). R4 forbids 「在导出时重新生成内容覆盖人工编辑」; this is insertion, not overwriting, so it does not breach R4 — but it is content the user never wrote appearing at export, it is not mentioned in the receipt, and **no test in the file touches it**, including its dependency on `style.name == 'Heading 1'` (P4). Note also `wrapper.runs[0].text = new_text` drops any `w:br` inside that run, so a cloned signature page that started with a page break loses it.

### P7 (LOW, pre-existing test defect the oracle pass missed) — a vacuous assertion

`test_production_export_ownership.py:82`:
```python
assert '受试者' in text and '受试者' not in text.replace('受试者', '')
```
The second conjunct is unsatisfiable-by-construction and can never fail. This is the same class of defect the owner correctly fixed in the textbox oracle; it survived here. The meaningful replacement is available from the registry: `template.json:126-135` records `受试者: 0` and `试验参与者: 240` in the source template, so the assertion should pin exact occurrences in the exported text (e.g. `text.count('受试者') == <n from user blocks>` and, for a user document that never writes `试验参与者`, `'试验参与者' not in text`). Line `:79` already covers presence, so `:82` is currently buying nothing.

### P8 (LOW, pre-existing, unreported) — the two deliberate export-time mutations of user body text are not auditable from the receipt

`:366` passes user block content through `_redact_gap_paths`, which rewrites `【缺口：fact.path：` → `【待补充：` and deletes `（缺口身份：…）`; `:543` normalises whitespace inside the citation object (`见表 1` → `见表1`). Both are content-level changes to the user's current body. They are intentional, but `engineering_marker_hits` (`:409-420`) reports only marker hits, so a reviewer reading the receipt cannot tell that user text was rewritten. Add a small `body_text_adjustments` count/kind list. Also note the marker scan covers `doc.paragraphs` and table cells only — a marker inside a textbox is not reported.

---

## 3. Pre-existing vs. introduced by these repairs

- **Introduced or newly exposed by this repair**: P2's fail-open and the *observability* of retained instructions (the page removal now exposes the retained front matter, which is why leftovers became visible); P3's broader removal range; P5's extension of run flattening to every body paragraph; P1 and the missing boundary assertion (new tests).
- **Pre-existing, untouched, still open**: P4's casing convention and the signature/`toc_titles` dependency on it; P6's signature cloning and its run-flattening; P7's vacuous assertion; P8's unreported redaction; F7-style `bundleInstalled` behaviour from the previous pass is unrelated to this file.
- **Not problems** (checked, do not spend effort): the front-matter boundary arithmetic (§0); TOC field balance and run-per-field construction; per-nearest-paragraph textbox replacement; `_expand_signature_pages` not being orphaned; media pruning leaving header/footer/style parts alone.

---

## 4. Smallest coherent next step

Order by (blast radius × cheapness):

1. **Settle P4 with one probe** (print `.style.name` for the retained front-matter headings in an exported file). If it is lowercase, `:314` and `:274` both need `casefold().startswith('heading')`; if capitalised, add a one-line test that pins the front-matter headings into the TOC cache so it can never silently regress.
2. **Close P2**: match on pre-sweep text, add a retained-instruction diagnostic to the receipt, and fail closed when `title_idx` is `None` — mirroring the existing `production_export_front_matter_unresolved` posture.
3. **Check P3 with a sectPr/section diff** before changing anything; if a break is dropped in the retained range, relocate it rather than widen the surgery.
4. **Add one oracle per repaired defect that can survive a wrong fix**: both textbox branches present (P1); the retained front matter ends at the 目录 heading and contains no `PAGEREF`/tab+digit page-number cache; the title paragraph carries no leading break and no `w:pageBreakBefore`.
5. **Replace P7's tautology** and, while the oracle pass is open, decide whether `cover-fixed.docx` should be regenerated so at least one artifact postdates the TOC/textbox changes — the current artifact predates them, so no artifact in the packet exercises this round's field or textbox work.

Everything above is source-level. The render, the section diff, the style-name probe, and the exported-artifact regeneration all require execution I cannot perform here; the owner retains final Word/visual acceptance.
