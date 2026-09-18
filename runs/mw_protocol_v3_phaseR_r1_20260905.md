# Phase R / R.1 权威路径重锚定检查点

日期：2026-09-05。状态：R.1 实现与离线复核完成；H-R 综合门另行判定。不是原始逐条 Session 的恢复，也不是产品验收。

## 权威与范围

- current supersession：design v1.3（d97a0d3de6f4a5cf3ed9b8c17d43e35895c04910605605be9f668aba0f80efc5）+ Plan v2（040eb6ad323047737e8be6a3a23344fdb719dc85230ef7994b96c9af29257607）。
- frozen plan 保留：fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914。
- frozen immutable manifest 保留：f4b385d444d4cf922f20b9934e87f6b72c0ad932fc767b5c86045b7e8c0ace7f。
- frozen protected rules 保留：16012ec0960ea096f86db6db65bb5dd77b33f215f3cee2377e5dfb28a6cb4ece。
- 新清洁模板：018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756。
- 仅隔离区 QC 脚本、附加 manifest、测试、执行证据变更；live、SOP 源文件、产品 app/frontend/contracts、旧 immutable rows/runs/records/logs/evidence 无写入。

## R.1 实现

13 项旧 CMSS 物理路径迁移至 SOP 树，逐文件哈希一致。附加 manifest 保存 old_locator/new_locator/hash/owner/read_only；旧 manifest 的逻辑路径与字节不改写。

新增保护：TP-MA-07 清洁版、追踪版、SVG，以及指定五份修订 SOP/QC/模板/指南（合计 8 项）。追踪版与 SVG 只是佐证；修订 I 期模板仍为待用户确定的候选，未自动升为权威。

拒绝项：不匹配哈希、缺文件、重复映射、越界相对路径、符号链接、缺只读/所有者声明、CMSS 树新增未声明文件。SOP 树有意采用冻结集合：后续新增受控文档必须追加 amendment，不能静默混入本次基线。

| 新/变更文件 | SHA-256 |
|---|---|
| config/medical_writing/protocol_v3/authority_amendment_20260905.json | ab0ac7a988d2a2c24a6a145917b3d17265a5eae75c039137fe59fe5374b556fb |
| scripts/qc/protocol_v3/authority_locator_amendment.py | aba846105ca28d5fb54dea553d33e5bd7e99586b9bf38ef5dbd6c4504b28d91f |
| scripts/qc/protocol_v3/build_frozen_authority_manifest.py | 0d56689cc350915a8ebaf53b61fd239ddcb0b8c8dbb76ef7b3a39c7ecbdd2567 |
| tests/protocol_v3/test_authority_locator_amendment.py | 633a12bdff49dae00d97bb33feadb34b31de56d179ef791fe0e699459ca7fe48 |

## 验证与 lineage

- 原三个 authority 路径失败已复现；新路径/负向测试先红后绿，未降低任何 expected，未 xfail 或删除负向 fixture。
- R.1/R.2/R.3 聚焦测试 183 passed；Protocol v3 全套 1240 passed + 101 subtests，2 warnings；独立 reviewer 实际复现。
- Task 2.1 七文件哈希均与 2026-08-12 暂停记录完全一致；75 tests passed；JUnit 位于 runs/mw_protocol_v3_phaseR_20260905/task21_verification.xml。
- 独立工程会商：Pi / Cursor / default，session 01a06fea-7774-7000-94e3-1dec8c8e1a17；动态 selector 的底层模型不据此宣称已知或多模型独立性。
- reviewer 第一次结论 H-R NOT_READY：缺本记录和 R.2 语义处置；保留原报告不覆盖。补齐后须复核综合门。
- 执行期最新全局 AGENTS（12:39:42 版）允许一名独立 reviewer、Codex 主集成，无最低 worker 数。guard 12:59:29 已变更；已启动健康会商保持原 packet，不重派。

## 不重复阶段 / 下一安全动作

不重跑旧分诊、下载、OCR、翻译及五失败项，不启动服务/Word/产品模型，不继续旧 r42 planner 路线或旧 Task 2.2。先完成 H-R，然后按 Plan v2 1R.1 产品 SQLite；用户已允许工程审阅 Agent，产品模型禁令仍按阶段执行。
