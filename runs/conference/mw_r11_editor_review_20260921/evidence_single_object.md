I'll start by reading the provided context files.

Bash is unavailable in this session; I'll work with read-only search tools.

I have enough evidence. Report follows.

---

# Conference Output: mw_r11_editor_review_20260921 - evidence_single_object

## Output

| Field | Value |
|---|---|
| Role | `evidence_single_object`（重要证据审阅） |
| Agent/provider/model | `codebuddy` / `codebuddy-cli` / `deepseek-v4.1-flash` (effort max) |
| Mode | serial, one bounded pass |
| SOURCE_HEAD read | `24c1ed1`（context 声明值；本轮未 git 校验，Bash 在本会话被拒绝） |
| Method | 只读源码审阅（Read/Grep/Glob）；未运行、未联网、未写任何文件 |
| Product changes | **无**（唯一写入为空） |
| Verdict | GenOffice 渲染器是**真实引擎接入**，不是简化 facade；但**「当前文档身份」在链路上是断的**，宽屏密度与 AI 提示层级为**源码可定位的既有问题** |

---

## 0. 直接回答三个审阅问题

1. **宽屏信息密度**：不是"卡片太多"，是**一个 1100px 居中单列容器**在 1920–2560px 屏上浪费 40–56% 宽度，叠加 16px/1.65–1.8 正文与 12px×16px 按钮内边距。定位见 §1。
2. **AI 提示层级**：`ManuscriptWorkspace` 单列内 **15 个平级块，其中 9 处是 AI/缺口/核对解释性散文**，且同一解释重复出现在 3 个位置；代码库内已有 `ul` 分点模式（`RegimenProposalCard.css:224`）但正文区没用。定位见 §2。
3. **GenOffice 真实文档编辑链**：引擎是真的（上游 renderer bundle + docx-engine 可行性证据齐全），但**接入链是半成品**：研究基线 pin 传错字段且无人接收、当前文档身份在两个编辑器/两条导出链接之间分叉、`mapping_status` 永久 `pending`、宿主拿不到保存回执。定位见 §3。

---

## 1. 宽屏信息密度 —— 源码定位

**测量依据（全部为 CSS 常量，非目测）**

| 位置 | 值 | 影响 |
|---|---|---|
| `frontend/src/features/medical-writing/protocol-workbench/ProtocolIntakeWorkspace.css:22-24` | `.pvi-workspace{max-width:1100px;margin:0 auto;padding:32px}` | 整页**硬上限 1100px 居中** |
| 同上 `:26-27` | `font-size:16px; line-height:1.65` | 全局正文/UI 基线 16px |
| 同上 `:123` | 唯一媒体查询是 `max-width:700px` | **没有任何宽屏分支** |
| `frontend/src/styles.css:58-60` | `.app.writing-active{grid-template-columns:64px minmax(0,1fr)}` | 写作页侧栏收窄到 64px，可用宽度 = 视口−64 |
| `ProtocolIntakeWorkspace.jsx:236-244` | 4 个子工作台顺序平铺 | 全部竖向堆叠，无并行 pane |
| `RegimenProposalCard.css:22-27` | 又一个 `max-width:1100px;margin:0 auto;font-size:16px` | 卡中卡，双重居中收窄 |
| `ChapterDraftPreview.css:1` | `.pcd-preview{max-width:900px;margin:24px auto;padding:32px 40px;font-size:16px;line-height:1.8}` | 章节正文再收一层 |
| `ManuscriptWorkspace.css:1,9,11` | `padding:24px`；`grid-template-columns:minmax(180px,240px) minmax(0,1fr)`；`gap:24px`；nav `max-height:70vh;position:sticky` | 稿区两列（目录+正文） |
| `ManuscriptWorkspace.css:4` | `button{padding:12px 16px}` | 按钮约 44px 高 |
| `office/GenOfficeFrame.css:3,32` | `.gz-office-frame{margin:16px 0;padding:12px}`；`iframe{height:78vh}` | 真文档编辑器被塞进卡片、固定 78vh |

**实测推算（1920px 视口）**：可用 1856px → 容器 1100px（**空置 756px，41%**）→ 减 `.kz-manuscript` 左右 48px、目录列 240px、gap 24px = 788px → 再减 `.pcd-preview` 左右 80px ≈ **708px 正文列**。16px/1.8 下约 44 个中文字/行。2560px 屏空置达 1396px（**56%**）。

**反证（项目自身的桌面密度基准）**：同一前端已有多 pane 网格，例如 `frontend/src/styles.css:404` `minmax(390px,0.82fr) minmax(580px,1.4fr)`、`:1383` 三列 `minmax(260px,.74fr) minmax(360px,1.25fr) minmax(260px,.8fr)`。协议 v3 工作台是**唯一把桌面写作用 1100px 单列承载的子系统**，与 `frontend/AGENTS.md:10-13`（desktop-first、preserve desktop information density）和 `:60`（用宽屏做并行 pane、减少 padding/行距/重复 AI 解释）直接冲突。

---

## 2. AI 提示层级 —— 源码定位

`ManuscriptWorkspace.jsx` 正文区在章节列表之前有 **15 个平级兄弟块**，其中 **9 处是解释性散文**：

| 行 | 内容 | 问题 |
|---|---|---|
| `:499-500` | eyebrow + h2 + 「保留已确认的研究选择，按模板撰写全部适用章节。」 | 与 §:512 重复说明 |
| `:504-508` | readiness 门禁三种文案 | 与 §:546-554 的"研究信息更新"段落**重复同一语义** |
| `:509-513` | 「关键设计已确认：N 章直接撰写，M 章带显式缺口成文…」 | 这是**唯一真正有决策信息**的一条，却被散文淹没 |
| `:514-518` | 补齐按钮 + 「缺失的章节级事实由模型…也可以直接生成初稿…」 | AI 建议解释 #1 |
| `:519-534` | 残余信息：intro 句 + ul + 展开按钮 + 「确认前可展开逐项查看…」+ 确认按钮 | AI 建议解释 #2、#3，同一 block 内两条散文夹一个按钮 |
| `:536-538` | 阶段状态句 | — |
| `:539-545` | blocked + 未完成章节列表 + 继续按钮 | — |
| `:546-554` | 研究变更 + 内嵌 readiness 说明 | 第 3 次重复"设计冲突/缺口不阻止其余内容" |
| `:556-561` | 完成状态句（含缺口解释） | 第 4 次出现"缺口"解释 |
| `:562-563` / `:564-566` | 保存按钮 / 「完整工作初稿已保存，第 N 版」+ 导出链接 + 括注局限 | 括注是过程性说明，非行动项 |
| `:567` | `study_binding_status` 告警 | — |
| `:568-569` / `:570-571` / `:572-576` | Office 帧 / 冲突按钮 / 重试·刷新·更新按钮 | 三个无语义分组的按钮散落 |
| `:588` | `editNotice` | — |

再叠加两处逐章重复：
- `ChapterDraftPreview.jsx:87` 每次选中章节都重印「当前文档中的正文，尚待医学核对」；
- `ChapterDraftPreview.jsx:77` 每个段落的编辑框内都带同一条 `<small>` 长句。

`office/GenOfficeFrame.jsx:94-98` 是 **4 行常驻散文**解释快照/冲突语义，占据编辑器首屏。

**已存在的正确模式**：`RegimenProposalCard.css:224-227` `.rpc-pending ul` 已是分点列表。也就是说"逻辑分点"在这个代码库里有实现先例，只有正文区没用。

---

## 3. GenOffice 真实文档编辑链 —— 逐层证据

### 3.1 渲染器是真的（证据）

- `scripts/qc/protocol_v3/build_genoffice_renderer.sh:11-18`：从上游 `genoffice/apps/docs` 用 `vite build --config vite.renderer.config.ts --base=/genoffice/` 构建**完整 docs renderer**，只注入 shim（`:22-32`），不做功能裁剪。
- `frontend/public/genoffice/index.html:11-12`：加载真实 bundle + GenOffice 自有 UI 字体包（`GenOfficePoppins-*`、`GenOfficeUIKanaJP-*`、`GenOfficeSansKR-*`…）。
- `frontend/public/genoffice/assets/index-DqUsVh4T.js`：含 docx-engine 标记 `documentXml` / `originalXml` / `w:tbl`（Grep 命中，非 facade 的典型特征）。
- 基线可溯：`docs/DELIVERY_SNAPSHOT_G0.md:12,17,43-44`（`GENOFFICE_HEAD=316ded6f…`，由该脚本构建）。
- 引擎保真度：`scripts/qc/protocol_v3/genoffice_feasibility.spike.test.ts:45-158` + `runs/requirements_v2_20260919/genoffice_feasibility.json`：814 blocks、83 表、4 sectPr、6 页眉页脚 part、未改动内容**字节级 round-trip 一致**、仅补丁段落改写。

**结论：不存在"简化 facade 冒充 Office"的问题。** 失败点在**接入链**，不在渲染器。

### 3.2 P0-A：研究基线 pin 传给了不存在的字段（F05 在真实路径上失效）

三段代码互相不接：

- 宿主算对了值：`office/GenOfficeFrame.jsx:43`
  `const studySha = savedDocument.document?.study_definition_sha256 || ''`
  并以 **`openedStudySha`** 为名传入 iframe query（`:62`）。
- shim 读的是另一个名字，且拿**文档哈希**顶替研究哈希：`frontend/public/genoffice/bridge-shim.js`
  `:19` 头注释声明参数名是 `studySha`；
  `:33` `const studySha = query.get('sha') || ''`；
  `:86` `expected_document_sha256: studySha` ← 正确；
  `:89` `opened_study_revision_sha256: studySha || null` ← **把语义文档哈希写成研究基线**。
- `openedStudySha` 全仓库**零读取方**（Grep 排除 `runs/` 后只有写点 `GenOfficeFrame.jsx:62`）。

服务端因此无法自救：`services/api/app/protocol_workflow/api/manuscript_drafts.py:508-510`
`intent['study_revision_sha256'] = body.opened_study_revision_sha256 or current.revision_sha256`
—— 客户端永远传非空值，所以**始终走"沿用打开基线"分支**，且记录的是错误常量；`study_revision_sha256_current_observed` 反而是对的，二者永不相同。

**不会报错**：`packages/contracts/workbench_contracts/protocol_v3.py:49-52`
`Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]` —— 真实文档哈希是合法 64 位十六进制，pydantic 放行。**静默数据损坏。**

**测试为何没抓到**：`tests/protocol_v3/integration/test_office_working_copy_closure.py:122-135` 只在 service 层用手造值 `'sha:study:S1'` 断言 F05，**绕过了 iframe query 契约和 pydantic**。

**最小完整修复**
1. `bridge-shim.js:33` 改为同时读两个键且语义分明：
   `const documentSha = query.get('sha') || ''; const openedStudySha = query.get('openedStudySha') || '';`
   `:86` 用 `documentSha`，`:89` 用 `openedStudySha || null`。
2. 宿主与 shim 的参数名二选一（建议保留 `openedStudySha`，同步修正 `bridge-shim.js:12-20` 头注释中的 `studySha` 描述）。
3. 研究 sha 缺失时**必须传 `null`**，让服务端记录保存时观测值，而不是塞一个错误常量。
4. 回归：新增 `bridge-shim.js` 的单测（mock `fetch` + 构造 `location.search`），断言 POST body 的 `expected_document_sha256` 与 `opened_study_revision_sha256` 分别等于传入的两个不同值。这条测试目前**不存在**。

### 3.3 P0-B：两个文档身份、两条导出路径，显眼的那条是错的

- 页面上可见的「导出Word工作稿」：`ManuscriptWorkspace.jsx:565` → `/manuscript-draft/export/docx`。
  服务端 `api/manuscript_drafts.py:198-230` 调 `render_production_docx(template_path, template_dir, saved['document'], output_path, current.definition.facts)`。
  而 `agent3/word_export_production.py:160-342` 会**打开模板 → 删掉模板示例正文 → 用 `document.semantic_blocks` 重建整个正文**。**这是投影产物，永远不是 Office 工作副本。**
- 编辑器内「下载当前工作稿」：`office/GenOfficeFrame.jsx:100` = `session.docUrl`，即"有快照则取快照、否则取同一导出"（`:44-54`）。
- **快照不会回流语义稿**：`application/manuscript_documents.py:719-802` 只落字节 + 事件；`:830-842` 只读字节；**没有把快照投影回语义文档的路由**。
- 宿主从不刷新：`ManuscriptWorkspace.jsx:568-569` 挂载 `GenOfficeFrame` **未传 `onClose`**，`GenOfficeFrame.jsx:80` 的 `onClose?.()` 落空。
- 能带回回执的客户端方法全是死代码：`protocolWorkspaceApi.mjs:145-170`（`saveOfficeSnapshot`/`recoverOfficeSnapshot`/`officeSnapshotContentUrl`）**只有定义、无调用**（Grep 证据）。shim 直接 `fetch`，宿主因此拿不到新的 `artifact_revision`/`content_sha256`/`document_revision`。
- 额外：该客户端方法 `:155-160` **未发送 `base_artifact_revision`/`opened_study_revision_sha256`**，与 shim 不是等价实现 —— 一个契约两套实现，一套废弃。

**用户可见后果**：在编辑器里改完内容或格式、关掉编辑器后，页面仍显示 Office 保存前的语义版本，点「导出Word工作稿」得到**不含 Office 修改**的文件；两个下载入口同义不同源。这正是用户说的"编辑区格式脱离真实文档"，也是 `frontend/AGENTS.md:60` 要求"audit persisted/current/exported document identity together"的那一项。

**最小完整修复（不新增渲染器、不建第二套存储）**
1. 增加/复用一个"当前工作文档"读取：`latestOfficeSnapshot` 已返回所需回执（`manuscript_drafts.py:533-538`，payload 见 `manuscript_documents.py:770-802`）。
2. 把页面导出/下载统一到当前文档：存在 Office head → 指向 `/office-draft/snapshots/{operation_id}/content`（已实现，`manuscript_drafts.py:540-550`）；不存在 → 回落到 `/export/docx`。语义导出降级为显式动作「按已确认研究重新生成（不改当前工作稿）」。
3. `ManuscriptWorkspace.jsx:568` 补 `onClose`，刷新 head + `savedDocument`（可直接复用既有 `setRefresh`），使用户看到"第 N 版"、绑定告警、冲突状态与真实保存一致。
4. 在一处同时显示身份：`当前工作稿 = Office 快照 v{artifact_revision} / 语义版本 v{revision}`。
5. 二选一：删除未用的客户端方法，或让 shim 改走它们；**不允许保留两套契约实现**。

### 3.4 P1-C：真正的编辑画布不是 Office，而是语义重绘 + textarea

- `ManuscriptWorkspace.jsx:577-587` 把「目录 + `ChapterDraftPreview`」作为普通块渲染；`:568` 的 Office 帧是**其上/其下的另一张卡片**，iframe 固定 `78vh`（`GenOfficeFrame.css:32`），且要多点一次「在浏览器Office中打开工作稿」（`GenOfficeFrame.jsx:87-90`）。
- 语义面本身的表达力：段落→`<p style="white-space:pre-wrap">`（`ChapterDraftPreview.css:6`，无粗斜体/列表/编号/页眉页脚）；表格→按结构模型重建的 HTML 表（`ChapterDraftPreview.jsx:28-59`，**只读**，无单元格编辑）；段落编辑→`<textarea>`（`:61-80`）。
- 与 `frontend/AGENTS.md:45-49` 的"desktop writing canvas is the primary surface""body content and structured tables must both support full-screen editing""never ship visual-only formatting controls"逐条不符。

**最小修复**
- `ManuscriptWorkspace.css:9-19`：把两列（目录+正文）改成三 pane 桌面布局 —— `minmax(200px,260px)` 章节树 | `minmax(0,1fr)` Office 画布 | 可选右栏（AI 提示/状态）；画布 sticky、满高，内部不再套 `max-width:900px` 卡片。
- `GenOfficeFrame.css:30-36`：主画布模式下 `height` 改为 `calc(100vh − chrome)` 并去掉卡片内边距，仅首次入口保留卡片样式。
- 保留 `ChapterDraftPreview` 但**降级为显式切换的"逐段语义对照/修改"**，不再与 Office 帧同时常驻（两个编辑器操作同一批 block 才是冲突根源）。

### 3.5 P1-D：两个编辑器 pin 的版本不同，宿主不做对账

`GenOfficeFrame.jsx:27-30,42-43` 有意冻结 session（F03）；而 `ManuscriptWorkspace.jsx:450-497` 的 `saveBlockEdit` **每次编辑都推进语义版本**。冻结的 `expected_revision/expected_document_sha256` 随即过期，下一次 Office 保存命中 `manuscript_documents.py:750-752` 的 `manuscript_document_revision_changed`（409）。shim 只识别 `manuscript_office_base_conflict`（`bridge-shim.js:109-125`），该 409 落到兜底分支，用户看到一句原文提示，**没有 re-base 路径，也不知道是自己的段落编辑造成的**。

**最小修复（不加合并功能）**：Office 会话打开期间冻结/禁用本页语义段落编辑；命中该 409 时给出明确出口「本页语义版本已更新，请重新打开编辑器以最新版本继续」+ 一个真正 close→re-begin 会话的按钮。

### 3.6 P2-E：`mapping_status` 是死字段；shim 的能力矩阵宿主不可见

- `manuscript_documents.py:782,801` 永远写/回 `mapping_status:'pending'`，产品代码中**没有任何推进点**（Grep 全仓仅此两处）；P3 要求的"与研究版本、映射状态原子登记"因此停在半成品。
- `bridge-shim.js:164-181` 明示 `writeRecoveryCopy/exportPdf/setDocPassword/discardDocPasswordIntents/revealDocInShell/openExternal` 为 `unsupported`；但 `:141-159` 又把 `respellKick`、`spellDiag`、`headlessExportDone`、`docPasswordIntentRevision`、`convertAltChunkHtml`、`consumeAiDocContent`、`consumeHeadlessExport` 硬编码为**静默返回值的假接口**，与 `:8-10` 自述的"决不伪造成功"自相矛盾。宿主既不展示这份能力表，也不在开始编辑前告知"嵌入版没有崩溃恢复副本、没有 PDF 导出"。
- **最小修复**：shim 暴露一个 typed `capabilities` 对象，宿主在编辑器头部一行内呈现；快照产生语义投影时（或明确标记"未投影"时）推进 `mapping_status`，让该记录不再永久歧义。

---

## 4. 对既有假设的反驳与改进建议

1. **"full fidelity renderer vs simplified facade"这个二选一的提问方式是错的。** 源码给出的答案是"渲染器真实、链路半成品"。建议把验收问题改写为**"每个用户动作下，当前工作文档是哪一份字节？"**，这才能覆盖 §3.2/§3.3 的真实缺陷。
2. **"宽屏=加列"会假通过。** 只加 pane 不动排版常量，仍是"文字/行距过大"：`ProtocolIntakeWorkspace.css:26-27`（16px/1.65）+ `ChapterDraftPreview.css:1`（16px/1.8，padding 32/40）+ `ManuscriptWorkspace.css:4`（按钮 12/16）。容器与字阶必须同批改，并在 1440/1920/2560 三档验收。
3. **"把 Office 帧放大成全屏"必须先做身份修复。** 编辑器越大，用户越可能改完就点页面上那条仍指向语义导出的链接 —— 放大画布会**提高**错误导出的概率。顺序必须是：身份统一 → 布局 → 密度。
4. **文件冻结范围与修复范围冲突。** context 声明"editor source remains frozen until this report returns"，但 §3.2/§3.5 的修复点在 `frontend/public/genoffice/bridge-shim.js`（未声明归属），§3.3 跨 `ManuscriptWorkspace.jsx` + `manuscript_drafts.py` + `GenOfficeFrame.jsx`（后者归属未知）。若并发修复正在触碰这些文件，本报告的 P0 必须排在其后。

---

## 5. 证据质量异常（标注为推断，需要一次廉价确认）

`runs/requirements_v2_20260919/genoffice_feasibility.json`：`source_bytes=293763`、`unchanged_roundtrip_bytes=293763`、`patched_bytes=122863`（**−58%**），而同一证据里 `part_comparison.identical=34, changed=[]`、`part_diff.added=[]`。

若 34 个 part 真为字节一致，差异只能来自 zip 层（压缩方法/级别/extra field）。我读过该测试的比较循环（`genoffice_feasibility.spike.test.ts:129-150`）：它确实覆盖了"缺失 part"与"内容变化"两种盲点，并比较了 `[Content_Types].xml`，所以更可能是压缩差异而非漏检；但**我没有在源码层证伪**。建议 Codex 做一次确认：对比同一 part 前后 `compressMethod/compressSize`，或去掉 `modified` 选项重跑。**这不是我断言的缺陷。**

---

## 6. 需要 Codex 裁决的边界问题

1. **归属与顺序**：`frontend/public/genoffice/bridge-shim.js` 与 `office/GenOfficeFrame.jsx` 当前由谁在改？冻结只覆盖 `ManuscriptWorkspace.jsx` 还是整条编辑链？
2. **产品真相**：我据 `AGENT_NEXT_TASK.md` P3"数据库不得另存第二份可独立编辑的正文作为竞争主版本"与 `frontend/AGENTS.md:60`，推断"**Office 快照即当前工作文档**"。若成立，语义导出必须降级为显式动作；若不成立，Office 帧就不能被呈现为"可编辑的工作稿"（`GenOfficeFrame.jsx:88` 的按钮文案与 `:94-98` 的说明都在做这个承诺）。
3. **语义段落编辑去留**：Office 帧成为画布后，`saveBlockEdit`/`localDrafts`/B07 缓冲是保留为对照工具，还是整块移除？（决定 §3.4 的工作量边界。）
4. **宽屏验收档位**：以哪个视口为准（1920/2560/超宽）？章节树允许移出卡片吗？

---

## 7. 未验证与超范围（明确声明）

- **未运行任何东西**：无浏览器、无服务、无网络、无测试执行（本会话 Bash 被权限拒绝）。全部结论为**源码级**。渲染器是否真的渲染 PDF/DOCX、UI 保存路径是否保真、`genoffice-docx-media:` 图片解码在 Electron 之外是否有效，**均未验证**，属 Codex 的 ego/浏览器验收范围。
- **未读工作区外的 `genoffice-upstream`**，未审阅 renderer 内部保存载荷组装逻辑；"UI 保存保真"只有引擎 API 级证据（spike），**没有 UI 级证据**。
- `bridge-shim.js` 的静默 no-op（`respellKick` 等）**未证明**造成用户可见失败；风险是调用方把 resolved promise 当作成功。§3.5 的 409 分类缺口才是源码可追踪的具体缺陷。
- 按 context 边界，**未审阅** synopsis StrictMode 挂载与后端恢复（分别由 owner/worker 持有），也未把那里的瞬时改动当作最终源码。
- 本报告未做任何产品修改；Codex 保留最终临床、视觉、浏览器、生产写入与对用户交付的接受权。

---

## 8. 最小完整修复清单（建议顺序）

| # | 动作 | 文件 | 验收信号 |
|---|---|---|---|
| 1 | 修 F05 参数：shim 分开读 `sha` / `openedStudySha`，缺失传 `null` | `frontend/public/genoffice/bridge-shim.js:33,86,89,12-20` | 新单测断言两个字段取到两个不同值；快照里 `study_revision_sha256 == StudyDefinition.revision_sha256` |
| 2 | 统一当前文档身份与导出/下载入口；补 `onClose` 刷新；处置死代码 | `ManuscriptWorkspace.jsx:565,568-569`、`office/GenOfficeFrame.jsx`、`protocolWorkspaceApi.mjs:145-170`、必要时 `api/manuscript_drafts.py` | Office 保存后页面版本与导出内容同步变化；两个入口同源 |
| 3 | 冻结语义编辑与 Office 会话的版本冲突出口 | `ManuscriptWorkspace.jsx:433-497`、`bridge-shim.js:109-125` | 409 时给出可执行 re-open 出口而非裸提示 |
| 4 | 三 pane 桌面布局 + 字体/行距/控件密度 | `ManuscriptWorkspace.css`、`ChapterDraftPreview.css:1`、`ProtocolIntakeWorkspace.css:22-27,123`、`office/GenOfficeFrame.css:30-36` | 1440/1920/2560 无空置主列，正文列显著变宽，无横向溢出 |
| 5 | AI 提示改逻辑分点（决策 + 下一步），合并 9 处重复散文 | `ManuscriptWorkspace.jsx:499-588`、`ChapterDraftPreview.jsx:77,87`、`office/GenOfficeFrame.jsx:94-98` | 正文区解释性散文块数量下降且每条含明确动作 |
| 6 | 暴露 shim 能力矩阵；推进 `mapping_status` | `bridge-shim.js:141-181`、`manuscript_documents.py:782,801` | 编辑器头部一行可见"嵌入版不支持项" |

**Resume point**：本 pass 已完成三个轴向的源码定位与最小修复建议，无阻塞。若需同会话继续，建议就 §6 的 4 个边界问题给出裁决后，直接进入 §8 第 1 项（改动面最小、风险最集中，且当前无任何测试守护）。
