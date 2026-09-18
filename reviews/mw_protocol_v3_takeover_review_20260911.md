# 医学写作子系统 Protocol v3 — ZCode 接管工程 Review 与 Plan 更新（2026-09-11）

- 作者：ZCode 接管主owner（用户显式授权完整接管 + 工程 review + 连续实施）
- 输入：HANDOFF_PROTOCOL_V3_20260911.md（逐字）、Trellis 3R.3 全记录、现场哈希/测试复核、
  组件结构现场验证。
- 性质：工程review与计划更新；不是任何产品验收。产品未达成"完整方案生成"目标。

## 1. 接管核对结论（全部通过）

| 项 | 结果 |
|---|---|
| Git HEAD / 脏条目 | 3d6772f / 349，与交接一致 |
| 7权威文件+6代码/fixture哈希 | 全部一致，9月11日无漂移 |
| 暂停快照 vs 现batch1 fixture | 52 ID 完全一致 |
| 聚焦测试基线（重跑） | 30 passed in 2.34s（resume_baseline_zcode_20260911_2115.xml） |
| 前后端结构 | 与交接§5地图逐项吻合（protocol_workflow 59个py文件；新前端目录仅API客户端） |

关键修正交接悲观预期：**首批修复实际已修绿**（worker在SIGINT前完成落盘），剩余缺口是
独立验收与文档收尾，不是继续修代码。

## 2. 组件含义与逻辑（验证有效的地图，摘记）

后端（services/api/app/protocol_workflow，59文件）：
- canonical/：StudyDefinition（已确认事实权威，CAS修订+确认绑定）、SemanticDocumentRevision、
  canonical hash（新旧版本并存，旧身份不重写）。
- ports/ + storage/：仓储接口 + 产品SQLite（迁移/约束/reservation生命周期）+ 显式测试memory后端；
  默认产品不可静默退回memory。
- events/：事件溯源与outbox/inbox（1R.4已去重，防重语义保留）。
- runtime/：模型调用合同、产品profile（glm-5.3-flash:max，凭证只在内存）、
  adapters/zhipu_api.py（1R.6探针SUCCEEDED）、reservations/idempotency（logical key对账）。
- application/ + api/：命令/读模型/事务编排；composition默认off挂载
  （WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED/DB/BUSY_TIMEOUT_MS）。
- graph/：typed facade三case持久化执行（2R.1验收，不是通用编排完成）。
- registries/：registry与章节合同加载、lint/内容结构验证（3R.2/3R.3 core验收范围有限）。
- agent5/ + artifacts/ + legacy/：控制面基础、制品持久化、渐进替换支撑。

前端（frontend/src/features/medical-writing）：
- 旧WritingPage为主链（App.jsx内），组件清单与职责见交接§5.5（23组件逐一核对在册）；
  已知缺陷（StrictMode挂载、过期Word预览误绿、失联删locator等）留6R修复。
- protocol-workbench/ 新目录仅有 protocolWorkspaceApi.mjs 客户端——新工作台页面未开始。

## 3. 当前工程问题清单与解决方案

### 3.1 本轮增量发现（交接未明说）

| # | 问题 | 解决方案 | 状态 |
|---|---|---|---|
| A1 | 首批修复无收尾文档/验收记录（worker报告未落盘） | 主owner复核+fresh独立复核，写reviews/mw_protocol_v3_3r3_batch1_repair_acceptance_20260911.md | 进行中（reviewer已派发） |
| A2 | fixture ID系统性改名（下划线→连字符），48语义槽位保留但字面ID未保留，且worker未记录改名理由 | 交fresh reviewer裁决：接受1:1映射（补记录）或机械回滚ID字符串 | 已入reviewer清单R5 |
| A3 | 9月工作无commit边界（349脏条目，恢复/审计困难——本次交接成本已证明） | 首批修复验收通过后，按文件归属做第一个可审阅commit（contracts/skills/fixtures/tests+packet），此后每批一commit；不用git add全部 | 验收后执行 |
| A4 | Trellis 00-bootstrap-guidelines仍in_progress、1R.2仍in_progress（遗留状态与实际不符） | 验收节奏内做一次状态对账：1R.2按已有functional+P1R证据收束；bootstrap不阻塞产品线，标注为低优先维护项 | 3R.3批次间隙 |

### 3.2 既有P1清单（交接§6.2确认仍有效，归阶段处理）

新前端未成形→6R；StrictMode导入挂载/过期Word预览误绿/同实例异步切章/失联删locator/
旧整稿hash不一致/逐章部分采纳回执/旧全稿崩溃窗口/QC禁词误报/字数机械门/Word回执弱→6R/7R；
全仓残留失败按scope处置→8R回归。本轮不重复展开，按Plan阶段推进。

### 3.3 流程问题（交接§11.3已承认）与接管后纪律

- 过细短回合、等用户说"继续"：接管后连续实施，仅3R.6Ⅰ期模板、生产激活、真实cutover等
  真决策点提问。
- 重复重锚定/全量重读：按AGENTS节奏重读全局AGENTS+当前任务记录；其余按hash与变更范围读。
- 文档时代混杂：Trellis为唯一执行状态，tracking只做索引（本日已更新指针）。

## 4. 功能与技术路线建议（更新）

维持（有依据，不换）：React+Tiptap受控语义编辑、Python领域服务、SQLite、typed facade、
五类Agent职责、只读预览+原生Word回流。不引入：LangGraph（typed facade不够用时才有界对照）、
MAF、浏览器Word分页引擎、多数据库/分布式队列/每章自主Agent。

建议新增落实进4R–7R（继承交接§6.3七项）：事实导入并排差异、设计变更影响预览、证据就地查看、
样本量复算卡、稿件锁定/撤销/可恢复导出、材料版本提醒、低负担长任务页面。

建议退出主流程（继承）：任意字数理由门、重复资料准入确认、逐章手动开始生成、逐文件下载/OCR
确认、技术模型参数大面板、从零逐格搭SoA。

接管新增建议：
1. A3的commit纪律（见上）。
2. 每批交付后由主owner跑一次assemble+lint并留存当日产物哈希，降低"worker自报绿"风险。
3. batch3–8继续批次化并行，但同一时刻至多2个执行worker+1个reviewer（避免3会话以上
   对同一订阅的压力与上下文交叉）。

## 5. Plan 更新（任务顺序不变，执行状态刷新）

Plan v2（040eb6ad…）+ review_amendment 仍为需求权威；Trellis为执行状态权威。
当前串行位置与批次：

1. **3R.3（进行中）**：batch1修复验收（fresh复核进行中）→ batch2交付（worker进行中）→
   batch3(10)/batch4(16)/batch5(19)/batch6(13)/batch7(13)/batch8(12)逐批"RED→实现→GREEN→
   fresh复核→Trellis同步→commit"；跨批继承义务crosswalk随批核对；总计111载体。
2. **3R.4** 依赖/影响图 → **3R.5** R03 QC registry（68行拆原子）→ **3R.6** Ⅰ期模板问题卡
   （**用户决策点**，预选T02修订版）→ **3R.7** 术语库/缩略语/L1检查。
3. **4R** 资料链（ResearchSeed→指南）→ **5R** 设计推荐与确认（8高风险逐卡）→
   **6R** 受控编辑面+写作链+新WritingPage（20点击/5自由文本硬预算）→ **7R** QC/Word闭环 →
   **8R** shadow/切换/E2E（真实浏览器计数验收）。

Goal 表述（ZCode时代延续，替代旧文"从1R.2开始"的过时定位）：
> 在隔离区内连续完成 Protocol v3 从3R.3起的逐批构建与验收，直至形成适合用户个人使用的
> 完整研究方案工作台：AI读材料→提取事实→推荐→完整初稿→受控修改→QC→原生Word→文档就绪；
> 标准Ⅱ/Ⅲ期路径≤20次关键点击、≤5处必填自由文本；8类高风险逐卡人审；只有真实用户决策点
> 才暂停。native codex Goal保持paused不动（其API无objective更新操作，Trellis承载执行状态）。

## 6. 执行/会商机制（ZCode接管后）

- 路由：zcode-route-manifest v1.3.0；off-peak finite_code_task本次取codebuddy/deepseek-v4.1-flash:max
  （mlx-serve首选项因64k输入门限跳过并记录）；GLM产物由非GLM家族fresh复核（verifier isolation）。
- 长等待：后台单次派发+完成事件通知，无固定间隔轮询，不因慢重派。
- 每worker prompt带Delegated mode前缀+preflight通过；输出schema固定；主owner做最终验收。
- 证据：每run目录留dispatch.json（路由身份/probe/时间）+stdout流+最终报告。

## 7. 阶段性清理策略（按用户本次授权细化）

立即执行（100%可再生）：__pycache__、.pytest_cache等解释器缓存。
永不触碰：runs/、rows/、evidence、session数据、暂停快照、历史XML/报告（审计证据）。
灰区（列清单不删，除非单项确认）：旧组装注册表副本、重复venv。每阶段收尾出一份体积清单。
