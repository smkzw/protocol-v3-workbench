# 3R.3 batch1 修复验收（主owner裁定）— 2026-09-11

- 验收对象：12 contracts + 12 skills + batch1.json + test_chapter_batch1.py（2026-09-06 交付、
  2026-09-08 修复中断但已落盘、2026-09-11 ZCode 接管复核收尾）。
- Fresh 独立复核：codebuddy/deepseek-v4-flash:max（非GLM家族验证者，GLM产物隔离），
  报告 runs/mw_protocol_v3_3r3_batch1_fresh_20260911/report_codebuddy_batch1_fresh.md，
  VERDICT: ACCEPT_WITH_ACTIONS；ID改名裁决 ACCEPT_RENAME（以D2修复为条件）。

## 裁定：ACCEPTED（2026-09-11，ZCode主owner）

六项缺陷全部按复核者最小修复方案落实，逐项核对：

| # | 缺陷 | 修复 | 证据 |
|---|---|---|---|
| D1 | test:198-199 全局glob等值断言会在后续批次落盘时破裂 | 改为超集断言+注释指向组装测试 | test_chapter_batch1.py；batch2的16合同已共存，68/68通过实证 |
| D2 | fixture ID改名（下划线→连字符）无映射断言、未记录 | 对 pre-repair 快照（runs/mw_protocol_v3_3r3_batch1_20260906/assembled_batch1_registry.json）加1:1去规范化映射断言（48精确集合相等）+节注释记录改名与裁决 | test_original_forty_eight_ids_preserved_and_new_fixtures_explicit |
| D3 | batch1.json fact_vocabulary残留 document_control.protocol_id；守卫循环不含batch文件 | 删除词汇项；守卫循环扩至BATCH_PATH（精确单文件，不glob正在写入的共享目录） | batch1.json vocab 69→68；test_identity_facts_reuse_existing_framing_bindings |
| D4 | 5个wrong_source命名载体的missing族fixture仅被泛化断言失败 | MISSING_FAMILY_CODES显式错误码断言（front_1/3/6、n_1_2→missing_required_fact；n_1_1→missing_required_claim） | test_every_fixture_exercises_its_named_defect |
| D5 | 布尔触发事实带prose值（"true（合成示例…）"） | 5处规范化为裸true/false；合成标记保留在对象文本/locator；authority行记录编码决定 | batch1.json + authority |
| D6 | 测试名含identity半但只断言术语 | 改名 test_participant_terminology_across_batch_files，注释指向identity守卫测试 | 同文件 |

## 验证证据

1. 组合聚焦套件（主owner运行，非worker自报）：
   `runs/mw_protocol_v3_3r3_batch2_resume_20260911/main_owner_combined_batches12_20260911.xml`
   **68 passed in 1.78s** = batch1(17，含全部D修复) + batch2(38) + codex反例(13)。
2. 复核者残余风险"XML 30 tests vs 17 functions"已解释：30 = 17 batch1 + 13 codex
   （内容6+组装4+多批3），4文件合计；现组合68复计一致。
3. 越界审计：core/schema/assembler/lint 与 batch1 contracts/skills mtime 保持9月6-8日
   （batch2 worker 与主owner修复均未越界）。

## 接受范围与仍然有效的限制

- 接受的是：12载体的合同/技能/fixture结构、六类内容修复语义、fixture语义槽位48+4、
  组装与批次范围断言。
- 仍然deferred（不因本验收变为已实现）：条件医学适用性executor、真实来源准入/
  provenance、正文写作与跨章一致性、SVG/表格/Word视觉验收——均为3R.3后续批次与
  6R/7R阶段义务，复核者所列其余残余风险与此一致。
- partial lint 永远 status=incomplete；本验收不代表全注册表或产品验收。
