# 3R.3 batch6 验收（主owner裁定）— 2026-09-11

- 验收对象：13个统计载体（v2_n_11_1..3、v2_n_11_4_1..9）：合同+技能+batch6.json
  （61 fixtures）+ test_chapter_batch6.py（8测试）。
- 执行血统：omp/pi openai-codex/gpt-5.6-luna:xhigh，报告
  runs/mw_protocol_v3_3r3_batch6_20260911/report_omp_batch6.md。
- 主owner验证：组合1-6套件166/166、独立组装13章/61 fixtures、核心未动。
- Fresh独立复核：codebuddy/deepseek-v4-flash（非OpenAI家族验证luna产物），报告
  runs/mw_protocol_v3_3r3_batch6_fresh_20260911/report_codebuddy_batch6_fresh.md，
  VERDICT: ACCEPT_WITH_ACTIONS。F1-F8裁决：F1/F3/F4/F5 PASS；F2/F6/F7/F8 PARTIAL。
  8测试覆盖性获确认（"test count alone is not a defect"）。

## 裁定：ACCEPTED（2026-09-11 22:40，ZCode主owner，六缺陷修复后）

| # | 缺陷 | 修复 |
|---|---|---|
| D1 | 11_1条件规则引用未声明事实 interim_alpha_adjustment | 以optional义务声明（sibling模式） |
| D2 | 11_4_6确证性链接义务无强制（reconciliation要求确证性必须链接主/次分析合同，不可改标探索性） | 3条pk/pd/er规则required_when_active加入confirmatory_analysis_link；新增forbidden claim confirmatory_relabeling_forbidden并登记闭词汇表 |
| D3 | 测试SOURCE_SPECIFIC死代码；9条负例中3条仅断言失败未断言命名原因 | 9项映射+expected_code子集断言，内联字典移除 |
| D4 | statistics.interim.applicable四处prose值违反裸布尔约定 | 4处规范化为"true" |
| D5 | 过时14.6引用解析仅prose，无禁止回写 | project_specific_element指名接受规范目标+forbidden事实stale_reference_pointer（登记词汇表） |
| D6 | statistics.*新事实根无归属声明（batch3 D3先例） | 13合同各补归属声明句 |

修复过程两次被闭词汇表lint当场拦下（claim/fact词汇登记），即时补正——组合套件
166/166（post_repair_combined_1to6_v2.xml）。

复核者残余风险：Bash被拒无法自跑测试（依XML+静态核验，主owner运行补足）；两段RED
中第一段为collection error（已在context标注，第二段为实质RED）。

## 接受范围与仍有效的限制

- 接受：13载体合同/技能/fixture结构、样本量全要素分型、分析集三分、SAP不豁免、
  多重性族、期中alpha/IDMC-IRC分离、PK/PD/ER继承与确证性链接强制、9负例定向失败。
- 仍然deferred：条件规则运行时执行、统计有效性判断、真实计算复现（3R.5/5R.2）、
  Word渲染。partial lint永远incomplete。
