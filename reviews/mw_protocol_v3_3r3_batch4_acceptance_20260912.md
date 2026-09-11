# 3R.3 batch4 验收（主owner裁定）— 2026-09-11/12

- 验收对象：16个干预/程序载体（v2_n_6_*、v2_n_7_*、v2_n_8_*）：合同+技能+batch4.json
  （72 fixtures）+ test_chapter_batch4.py（29测试）。
- 执行血统：codebuddy/deepseek-v4.1-flash:max，报告
  runs/mw_protocol_v3_3r3_batch4_20260911/report_codebuddy_batch4.md。
- 主owner验证：组合套件97/97（时点1）、158/158（batch1-5共存，两时点）、独立组装语义
  复现、partial lint exit0、越界审计清白。
- Fresh独立复核：zcode/GLM-5.3-Flash（非deepseek家族验证者），报告
  runs/mw_protocol_v3_3r3_batch4_fresh_20260911/report_zcode_batch4_fresh.md，
  VERDICT: ACCEPT_WITH_ACTIONS。复核者独立复现29/29并逐条checker验证8条负例失败码。

## 裁定：ACCEPTED（2026-09-11 22:19，ZCode主owner，三缺陷修复后）

| # | 缺陷 | 修复 | 证据 |
|---|---|---|---|
| D1 | 16合同 word_rules.required_styles/required_bookmarks 为空，违背"Preserve exact node/bookmark/style IDs"（node_tree声明样式3/4与_Toc书签；checker不交叉校验所以一直绿） | 从node_tree程序化回填16合同精确样式+书签（v2_n_6_1_2含_Ref书签一并保留，忠实源声明） | 回填清单见执行日志；组合158/158 |
| D2 | 8条spec负例仅2条断言精确错误码；storage QC断言"空单位 or 单位"空真 | SOURCE_NEGATIVE_EXPECTED_CODES 8条全覆盖（subset断言）；or→and | test_source_specific_negatives_fail_for_their_named_reason |
| D3 | v2_n_6_2_2条件规则触发事实（regulatory_labeling_check/label_text）在vocab但未在合同fact_requirements声明=死规则 | 两事实以optional义务声明（对齐sibling模式），rationale记录修复缘由 | v2_n_6_2_2.json |

复核者残余风险裁定：max-dose折叠进dose_regimen/escalation逻辑、escalation声明性
required（声明适用性而非强制值）——均为可接受建模，不改；书签/样式checker交叉校验
缺失记为3R后续改进项（连同batch2复核同类观察）。

## 接受范围与仍有效的限制

- 接受：16载体合同/技能/fixture结构、个体vs试验级停药分型、救援-estimand一致、
  退出/失访语义、8负例定向失败。
- 仍然deferred：条件规则运行时执行、医学判断、真实来源准入、Word渲染（7R）；
  partial lint永远incomplete。
- 本验收不覆盖batch3（其fresh复核另行裁决时点）。
