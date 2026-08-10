# Task 0.8 — Microsoft Word 原生回执生产路径决策

日期：2026-08-10
状态：`P0-WORD_TECHNICAL_PASS_WITH_RESIDUALS`
边界：仅为 Protocol v3 的 Word 技术交付路径；不是研究方案内容质量或产品发布验收。

## 决策

选择 **目标 macOS 工作站上的受控 AppleScript bridge** 作为 Phase 0 的 Word 原生
回执生产器。它已在 Microsoft Word for Mac 16.111.3 上完成真实任务副本的打开、
全部可访问 story/header/footer 域更新、目录更新、重新分页、另存、关闭、重开、
PDF 导出、逐页证据和 OOXML 指纹，并完成一次真实 Word 文字修改后的回导与再导出。

Office Add-in 保留为后续产品化候选，不在 Task 0.8 中构建或选定。Microsoft 官方
文档证明其对象模型、OOXML 和 custom XML 能力存在，但当前仓库没有可直接复用的
兼容 scaffold，也没有目标工作站上的同合同实测；文档能力不能替代运行证据。

## 候选比较

| 候选 | 当前结论 | 直接证据 | 部署与数据边界 |
|---|---|---|---|
| AppleScript bridge | `PASS_CANDIDATE` | Word 16.111.3；CMS-UC-301 首次导出回执；真实文字修改后回导/再导出回执；相同 key 重放 | 项目自有代码；只打开任务副本；不关闭、不保存用户原有文档；本地执行，无数据外传 |
| Office Add-in / Word JavaScript API | `DOCUMENTARY_ONLY` | Microsoft 官方对象模型、OOXML、状态持久化资料 | 未构建、未安装、未在本机同合同实测；本阶段不选型 |
| LibreOffice、HTML 预览、仅下载 DOCX | `REJECTED` | 不满足冻结合同的 Microsoft Word 原生身份 | 不得标记为 Word 原生核验完成 |

## 实测矩阵

### CMS-UC-301 完整方案：通过

- 原始样本 SHA-256：`cd5d483a241932d2a5c92b9c6f07afcee17d779a7d345758d63695505ca0dd04`。
- 首次回执：`mwwr_v1_a8a815cb196ef9ed3c99e692a28e51ed`。
- 126→126 个域，更新错误 0，目录 1，27 页；5 个稳定业务书签，32 个已解析
  `PAGEREF`；第 9、10、14 页横向，其余纵向。
- 保存 DOCX：`bdf8b98224038fd66d02f74f94508b0da7379e9a5957d22034c341d2b1532d34`；
  Word PDF：`58ffbd2c1eb71b612389b3b9c1b5ef3d91f443ede4bfe64784df4f3358f1ef60`。
- 27 页全部可视化复核通过；任务文件在 Word 中实测可编辑，撤销后磁盘 hash 不变。

### 外部 Word 文字修改→回导→再导出：通过

- 在任务副本中通过 Word 将“监管管理部门”修改为更符合中文监管语境的
  “药品监督管理部门”；未修改结构、样式或临床事实。
- source / edited / reimported / re-exported artifact identity 四者不同，原始导出未覆盖。
  这里的“不相同”明确指四个 `artifact_id`；wording-only 文件在 immutable ingest 与
  re-export handoff 之间允许字节不变，因此 edited、reimported、re-export input 的
  SHA-256 均为 `d9309158…`。新的 Word 再导出产物由独立的 saved DOCX
  `06e43188…` 和 PDF `151c2812…` 绑定，不能把 artifact identity 误读为四个内容
  hash 必须不同。
- 合并语义版本：`semantic-document-cms-uc-301-wording-r2`。
- 当前再导出回执：`mwwr_v1_75c4311dfc1ac8c0af0d908726e34525`；较早的
  `mwwr_v1_234418ce286849ee898f18dc202605c6` 是 lineage 校验增强前的历史回执，
  不再代表当前 producer 实现。
- 126→126 个域，更新错误 0，目录 1，27 页；全部页面再次可视化复核通过。
- 输入/回导 SHA-256：`d930915819c7866d4209c1f7c03237895c0c603e711e8dc1c40fda086c3e2793`；
  Word 保存 DOCX：`4fdc8442ce871fc7df08d93e48cda1a3f56c09a5ef3e5afb6ed4533fc5fe7716`；
  PDF：`0738d7ec323e47f6960081a45cb78cc41ddb3c5db04cfcb1a01f6fe689d806a2`；
  normalized OOXML：`76327ed8f5c1011331d8f9911e5891558f96dcf875393e888ff77a939bacba7a`。
- 相同请求再次执行直接返回 `replayed`，未再次打开或修改 Word。

### TP-MA-07 模板：功能对象通过，视觉未通过

- 原始样本 SHA-256：`a28e95d738ffad9199eee44a965164d89a04022dbcac7ea01a999bde5cf34f5e`。
- 302→302 个域，更新错误 0，目录 1，62 页，Word 保存/重开/PDF/指纹均完成。
- 逐页复核发现第 2 页页脚“第2页/共62页”的右侧部分被裁切；因此候选保持
  `pending_visual_qc`，未生成最终回执。生产器不能用机器成功掩盖真实版式缺陷。

### D017 骨架：确定性阻断

- 原始样本 SHA-256：`bae34f096ef5769a8d025ac03f72d9dfed06278d03faef97dff33beaae9705e9`。
- Word 已完成 219→219 个域、目录、保存、重开和 PDF；但只有会随目录更新变化的
  隐藏书签，没有稳定业务书签目标，生产器返回 `WR_BOOKMARK_EVIDENCE`。
- 同一请求恢复时复用既有 Word 完成事件，未重复调用 Word。D017 仍受永久失败语料
  的“骨架文档”业务阻断，不得升级为可提交方案。

## 兼容性与失败恢复

- Word 16.111 for Mac 对部分 collection 的直接 `count`、带 successor 的
  `next story range` 行为不稳定。bridge 改为读取 collection 后计数，并显式遍历
  document-level story types 及每节 first/even/primary 页眉页脚。
- 目录更新可能合法增加目录域，因此“更新前”基线在目录重建后采集；后续保存重开
  仍必须保持域数量一致且错误为 0。
- 每次运行先写 reservation，再写 Word 完成事件。若 Word 已成功而后处理被中断，
  只核对 exact identity/artifact/lineage 后恢复后处理，不重复 Word 副作用。已存在
  staging、reservation、candidate 或 final receipt 时，source/edited/reimported/re-exported
  hash、语义版本或 lineage 任一不一致均以 typed error 停止，不能借旧回执重放。
- 既有用户文档在运行前后按名称、路径、保存状态精确比对；任务执行只关闭任务副本。
- Word 原生 `field_count` 是逐 document story 与逐节页眉页脚执行的更新操作数；链接
  页眉页脚可能按节重复计数。OOXML 解析器统计的是包内唯一 complex/simple field，
  CMS 当前为 Word 126 次更新操作、OOXML 59 个唯一字段。两者用途不同；合同要求
  Word 更新操作前后稳定且错误为 0，OOXML 路径用于书签、引用和结构核对。

## 页面证据依赖

- `pypdfium2 5.12.1`，许可证 `Apache-2.0 OR BSD-3-Clause`。
- 上游与许可来源：<https://github.com/pypdfium2-team/pypdfium2>。
- 用途：本地渲染 Microsoft Word 导出的 PDF 为逐页 PNG；数据外传：无。
- 旧 PyMuPDF 路径未被沿用或自动升级为生产依赖。

## 残余边界与回滚

- AppleScript bridge 是当前工作站可验证的 Phase 0 实现，不代表已解决跨平台分发、
  签名、Office Add-in UX 或产品 API 接线；这些属于后续 Phase 6–7。
- 当前显式覆盖 document-level story 和每节页眉页脚；未来出现 text-frame/批注/
  修订等新样本时必须扩展代表性 corpus 并重新验证，不能外推。
- 任何 producer 代码、Word 版本、输入 DOCX、模板版本或语义版本变化都会生成新 key
  和回执；旧回执只保留为历史，不覆盖。
- 回滚方式：停用 AppleScript producer 选择，保留冻结合同和 immutable evidence，
  回到 `NO_RELEASE_WORD_BLOCKED`；不需要回写或恢复任何源文件。

## Gate 建议

独立功能验收已经完成：Pi/cms-model 返回 `READY`，Grok Build 在同一 session 两次
恢复后返回 `READY_WITH_RESIDUALS`；Codex 随后增强 lineage/replay 校验并在新 producer
身份下重新核对 67 项功能测试、当前严格合同回执、27 页视觉证据、三个原始样本 hash
和 Word 用户文档 inventory；原 Pi session 又对当前身份返回一次针对性 `READY`，因此接受
`P0-WORD_TECHNICAL_PASS_WITH_RESIDUALS`。当前冻结的 producer implementation
SHA-256 为 `9e214a167b7f0bf67e417e0c75e4b71b8a6c9b98cf5b5e3b5f81aba7f90fc12b`；
较早的 `f7d9d8b1…`、CMS 首次回执的 `1fd1fb09…` 均只保留为历史身份，不能替代
当前指纹重放。

该结论只解除 Word producer 这一项阻断，不等于 Protocol 内容、A+C 工作台、
Phase 6–8 或最终发布通过。text-frame、批注、修订等新样本仍需按 corpus 扩展重新
验证；它们是范围残余，不倒推当前代表样本失败。

本任务未运行或派发任何安全、对抗、权限、路径、符号链接、竞态、恶意输入或
破坏性状态测试。
