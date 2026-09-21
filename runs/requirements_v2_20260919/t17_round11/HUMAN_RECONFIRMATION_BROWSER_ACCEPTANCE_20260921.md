# Study A 既有竞品篮子复核浏览器验收

日期：2026-09-21

范围：隔离副本，不触碰 live 8910/5186/5285，也不写原 Study A 运行库。
执行模式：direct。问题是同一 React 页面内确定性的快照选择、自动检索条件和视觉顺序，真实数据与浏览器行为可直接裁决，不需要新增执行节点或独立主观会商。

## 发现并修复

1. 后端已返回 `reconfirmation.required=true`，但新检索计划的 `latest_snapshot_id` 为空时，前端没有使用 `discovery_basket_projection.snapshot_id`，因此隐藏了已有 59/256 人工篮子，只显示“执行公开竞品检索”。
2. 同一遗漏还让挂载时的自动研究 effect 把“无新快照”误判为“从未检索”，无人点击也会重新检索并启动父研究流水线。该问题只发生在第一次验收副本；服务随即停止，副本废弃并从未变化的源库重新制作。证据见同目录 `unexpected-automatic-research.json`。
3. 复核卡原本排在 420px 候选列表后，主操作位于首屏下方。现在复核卡排在候选列表之前，先给当前条件、59/256 汇总、可选展开和一次确认，再展示明细。

最小修订复用既有字段和组件：

- `MedicalWritingAuthoringJourneySetup.jsx` 统一采用 `search_plan.latest_snapshot_id || discovery_basket_projection.snapshot_id`；
- 自动检索 effect 在已有投影快照时直接返回；
- 旧快照存在时提示“无需重复检索”，检索按钮降为“按需重新检索”；
- `styles.css` 仅用现有 flex order 把确认卡前置，没有新增状态、服务或布局框架。

## 真实隔离验收

干净副本首次只读核对：journey revision 20，原快照 `wref_search_95d54c91e3c4fb21b234`，run `ct_run_64da04e8e33f89dc728f`，315 条候选，59 条保留、256 条排除，六项当前医学分诊条件齐全。

ego(lite) TaskSpace 12：

- 1920×1080：页面宽度与 scrollWidth 同为 1920，无横向溢出；
- 复核卡由绝对页面位置 1578px 前移到 800px，候选列表移到 1215px；
- 页面首要信息为“既有人工确认结果已全部预选：保留59项，排除256项”；
- 主操作为“确认当前315项分类”，无需填写自由文本；
- 浏览器 resource 记录未出现 ClinicalTrials.gov、20128 网关或 DeepSeek 资源。

执行一次确认后：

- journey revision 23，仍绑定原快照；
- 新确认 `ct_reconf_81450fa2caf9cf004f20`，类型 `human_reconfirmation`，来源确认 `ct_conf_64147b6c4d57d64cb9b9`；
- projection status `corpus_projected`，run 保持 `confirmed`；
- 59/256 分类未变化，`reconfirmation.required=false`；
- API 日志只有一次 reconfirm POST 和只读刷新，没有新检索、AI分诊、下载、OCR或翻译。

原 Study A 的 18 个 SQLite 文件在验收前后哈希清单完全一致；清单 SHA-256 为 `d00dde8ccf7efe59ac1c29c416a2dc0732cdb567a5a0e7addbc4c355b57e6740`。

## 集中验证

- frontend production build：1971 modules，通过；
- 正式 frontend inventory：15 个 Vitest 文件、110 项通过；48 个 Node 文件、65 项通过；
- `git diff --check`：通过。

ego(lite) 的 `Page.captureScreenshot` 三次均在 15 秒内部超时，因此本批次视觉截图为 `UNVERIFIED`；语义快照、真实 DOM 几何、宽度与交互结果已核对。没有为截图工具故障更换浏览器或伪造图片证据。

## 下一动作

将相同的确定性复核应用到原 Study A 隔离运行库，随后继续 F12 三研究身份与完整“资料→推荐→确认→初稿→当前Word→下载”旅程。无需重新检索或重跑既有分诊。
