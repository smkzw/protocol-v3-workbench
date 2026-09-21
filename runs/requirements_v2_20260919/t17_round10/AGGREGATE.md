# T17 第十轮聚合报告（四场景：子宫内膜异位症/甲状腺眼病/IPF/痛风）

## 测试者结果总览
| 测试者 | 模型 | 场景/入口 | EXIT | 产品判定 |
|---|---|---|---|---|
| tester1 | opencode-go/muse-spark-1.3-contributor(max)（重派，原gemini配额429） | 子宫内膜异位症/入口A | EXIT=BLOCKED | 初稿停滞6/111章 |
| tester2 | cursor/cursor-grok-4.6 | 甲状腺眼病/入口B | EXIT=OK | FAILED（7章/104缺口仍导出） |
| tester3 | opencode-go/deepseek-v4.1-flash | IPF盲测+OCR/入口B | EXIT=BLOCKED | 门禁4轮不收敛+0/111章 |
| tester4 | zai/glm-5.2 | 痛风/入口B | EXIT=OK | FAILED（10/103章停滞） |

**AI通道修复（0112373/6de4afb）实战验证**：四测试者全部成功穿越"准备写作材料"（seed-generate）、设计要素生成等AI节点，第九轮的401/504/blocked全灭。第一站"needs_information补答"即为设计内流程。

## P0（分级汇总）
- **P0-A 初稿生成停滞（三测试者独立复现）**：tester1 6/111、"继续写作"×4零新增；tester3 0/111、生成3次中止（23-217s）；tester4 10/103冻结、"继续写作"点击5-10秒即停、fetch hook捕获0请求。=> 深挖方向：chapter-draft派发队列在多章批量下的停滞根因（r8遗留，未根治）。
- **P0-B 确认门禁不收敛（三测试者同族）**：tester3"剂量方案确认前需先处理"4轮补答不收敛（每轮生成新未决项、要求确认上一轮自身补答内容）；tester2给药确认键禁用+补答后"归属尚未核实"；tester4安慰剂卡重复列同一条两次且无作答控件。
- **P0-C 跨项目内容串染（docx QC实锤）**：tester2导出的TED方案"研究理论依据"章节含"本研究实际适应症为原发性IgA肾病（IgAN）、已确认机制方向为靶向补体通路"——IgAN为他轮测试项目内容。数据隔离或章节装配合并缺陷。

## P1
- **P1-A 缺口锚点全篇泄漏（docx QC实锤）**：导出正文含几十处"（缺口身份：v2_n_x_x）"，ac035b2的剥离修复未覆盖缺口成文路径。
- **P1-B 导入方案摘要挂死**：tester1卡"正在准备文档内容"13分钟无进度/超时/重试（r8遗留复现）。
- **P1-C 内部标识符UI直出**：按钮"资料准备（chapter-sources:f1a7fc03…）"（tester1）；历史记录同（tester4）。
- **P1-D 内容质量**：tester4正文"作用机制为继承性义务"病句且与已确认靶点矛盾（已确认"尿酸转运蛋白1抑制剂"正文却称未载明）。
- **P1-E OCR对图片型DOCX不可用**（tester3，重点模块a链路断）。

## P2
- 39项"确认以上全部"需先点"更新研究与文档状态"（tester1/tester4同款）
- 期中分析卡确认静默无效（tester4）
- 版本门禁开局阻塞约5分钟后自愈（tester3/tester4，环境噪声待查）
- 写作说明textarea被折叠面板遮挡（tester4）
- 点击未完成章节无反馈（tester1）
- 章节标题模板残留"有'状况/疾病'的试验参与者"（tester1）

## 重点模块(a)(b)(c)
四测试者一致结论：文献引用管理、可跳转目录/表图目录、研究流程示意图 **全部缺失或不可达**（部分因初稿停滞未达，部分为功能缺位——见各报告结论表）。

## docx QC（tester2导出产物 iga_protocol_work.docx）
- 24,538字符/572段/6表；GenOffice编辑保存往返成功（字节级内容保留）
- 占位符26处（显式缺口成文，设计内但需评估密度）
- 反拟合：IgAN×2命中（即P0-C串染实锤）
- 内部锚点：v2_n_*泄漏几十处（即P1-A）

## 会商要求
对以上发现逐项审阅：真缺陷/测试误报/环境噪声；深挖P0-A（生成停滞）与P0-B（门禁不收敛）的根因假设；举一反三（同类缺陷还可能在哪些环节）；给出修复优先级与验证方案建议。

---

## ⚠️ 会商审阅修正（2026-09-21 07:1x，详见 CONFERENCE_REVIEW.md）
以下两条聚合结论被独立会商复核**推翻/降级**，后续修复不要按本文件上文的原始表述执行：
1. **P0-C 跨项目内容串染 → 撤销（误报）**。QC 脚本在共享目录 /tmp/t17_tester2/ 取到了上一轮 IgAN 项目的产物（iga_protocol_work.docx，2026-09-20 11:04，早于本轮测试 17.5 小时），"IgAN 适应症正文"对 IgAN 项目自身是正确内容。tester2 真实导出 ted_t1_protocol_export.docx 经逐段复核 IgAN/补体零命中。**残留改进项**：导出 docx 应写入项目指纹（project_id/study_definition_id/document_sha256 → docProps/custom.xml），QC 产物目录按轮次分桶。
2. **P1-A 缺口锚点泄漏 → 降级为三个具体面**。段落导出路径已剥离生效（ac035b2，TED 导出实测 0 泄漏）；iga_protocol_work.docx 的 108 处系修复**前**的历史产物。仍需修：①表格路径未过 _redact_gap_paths（word_export_production.py:339-345）②UI 阅读面直出语义块内容 ③把剥离提升为导出前统一投影。
3. **P1-B 导入方案摘要"挂死 13 分钟" → 根因完全不同**。后端 125ms 内即以 HTTP 401 终结（legacy 摘要导入链路未走本轮网关修复，仍打 api.deepseek.com）；真正挂死原因是前端 StrictMode latch 一行 bug（MedicalWritingSynopsisProjectIntake.jsx:207 mountedRef 卸载后不复位，StrictMode 二次挂载后 start() 永久短路）。
4. **P0-A/P0-B 根因链已定位到文件:函数级**（见 CONFERENCE_REVIEW.md 第一、二节），且二者同根：UNKNOWN_OUTCOME 无产品恢复入口 + 按钮只 recover 不 retry + 门禁以模型自报为准。修复按 CONFERENCE_REVIEW.md 第七节 Top-13 清单执行。
5. **项目↔测试者映射更正**：tester1=proj_user_69d9156ab281（重派后）+26ea92f426a7（gemini 429 首轮遗留）；tester2=e3e097d072f0；tester3=5f800b8408f7；tester4=520b0aa75b22。
