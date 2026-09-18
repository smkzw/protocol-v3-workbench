I'll start from the conference contract and the two assigned source files, then independently audit chapter order, carrier coverage, unknown vs excluded, phase mapping, and DOCX-to-section evidence bounds.The owner contract is read-only and hash-gated. Next I’ll load the frozen manifest and the listed source files before judging chapter order and evidence bounds.Hashes and the frozen source files come next, along with the extra allowed imports the context names. I will not write the runner report path.Hashes match. I’ll now read the frozen plan, source-material, and template runtime files against the extra allowed imports.Phase mapping sits outside the frozen core. I’ll read the tests and the allowed imports that actually own order, unknown/excluded, and DOCX evidence.Phase aliasing and applicability look like the highest-risk seams. I’ll read those tests and run the allowed suite plus a few read-only probes.I’ll run the allowed tests and a scratch-only audit of tree order, phase conflict, proposed-study API behavior, and DOCX evidence roles.# Conference Output: mw_protocol_v3_manuscript_inputs_review_20260913 - evidence_single_object

## Output

**Fallback (explicit):** 原指定 Z Code / `GLM-5.3` / thought `max` 在可恢复会话建立前不可用。本节点由 Codex fallback 以 `grok-build` / `grok-4.6` 执行同一 `evidence_single_object` 有界审阅。未切换角色、未改 source list、未写 runner 报告路径、未生成医学正文、未调用产品模型、未启动常驻服务。

**能力限制：** 不能在 Z Code app-server 内锁定 GLM-5.3；未做 Native Word / 医学准入 / 浏览器 / 真 HTTP 产品调用。证据来自冻结清单哈希、源码与允许的 in-process pytest / scratch 复现。不主张最终临床、监管、视觉或用户面验收。

**本轮核验：** 清单 13 个文件 SHA256 全部匹配；指定 pytest 14 passed / 2.68s。只读 scratch：`runs/conference/mw_protocol_v3_manuscript_inputs_review_20260913/scratch/evidence_audit.py`、`evidence_audit_followup.py`。未改 source/tests，未写 `evidence_single_object.md`。

---

### 1. 最高影响缺陷（先于总评）

**缺陷 A（高）— 期别旧/新冲突在完整初稿计划里对摘要/设计不对称。**

- **证据：** `fact_bindings.json` 中 `framing.study_phase` 与 `framing.structured_design.phase` 都把 canonical 指到 `framing.study_phase`，并互相列入 `legacy_canonical_paths`。`bind_chapter_input` 在两键同在且值不同时抛 `fact_alias_conflict`（`fact_bindings.py` 266–278）。隔离测试 `test_synopsis_and_design_share_one_phase_without_writing_duplicate_facts` 对 `v2_n_1_1` / `v2_n_4_1` 都能打到该冲突。
- **证据（计划路径）：** `plan_manuscript_chapters` 对非 `not_applicable` 章节调用的是 `bind_applicable_chapter`（`manuscript_plan.py` 33–43）。后者先走 `_resolved_input_contract`：`_resolve_rule_states` 一旦有 `conditional_applicability_unresolved` 就整章 raise，**到不了** alias 检查（`applicability.py` 312–316, 353–360）。
- **复现：** 同时写入 `framing.study_phase='Ⅱ期'` 与 `framing.structured_design.phase='Ⅲ期'`，不补 `v2_n_4_1` 的内层触发事实 → 计划里 `v2_n_1_1=invalid_input/fact_alias_conflict`，`v2_n_4_1=needs_information`（stratification/substudy 未决）。补上 `statistics.interim.applicable=False` 且 `framing.structured_design.features={stratification:false, substudy:false}` 后，两章才都变成 `invalid_input/fact_alias_conflict`。
- **推理：** 完整初稿准备计划在设计章“还缺内层条件事实”时，会把已经存在的期别自相矛盾降级成“待补信息”，而摘要章显示输入非法。这直接违背“摘要/设计期别同源、检出旧/新冲突”。
- **建议修复：** 计划循环把 **事实绑定错误** 与 **适用性未决** 拆开：对原合同始终跑 `bind_chapter_input`（只读、不投影义务）；`fact_alias_conflict` 一律 `invalid_input`。`bind_applicable_chapter` 只用于 snapshot 已适用且内层规则已决的 `facts_ready` 计算。未决条件仍保留为 `needs_information`，但不得吞掉 alias 冲突。
- **不确定：** 其他带内层条件的章（不限期别）是否同样会把 `fact_type_mismatch` / `fact_alias_conflict` 藏在未决规则后面；未做全规则扫描。

**缺陷 B（高）— Word 数字样式标题会被当成正文证据。**

- **证据：** `docx_parse.py` 115–122 只在 `_has_heading_style` 或**段落本地** `outlineLvl!='9'` 时标 `heading`。`_has_heading_style`（`writing_reference_docx.py` 223–226）只认 styleId 以 `heading`/`标题` 开头或 `title`/`subtitle`。`node_tree.json` 的标题节点大量 `style_id: "2"`；树抽取算法明确读 `styles.xml`（含 basedOn），`parse_docx` **不读** `styles.xml`。
- **复现：** `w:pStyle w:val="2"` 单独出现 → role=`body`，进入 `evidence`。同段加本地 `outlineLvl=0` 或 style=`Heading1`/`标题1` → `heading`，不进 evidence。把 heading 1 写进 `word/styles.xml`（styleId `2` + outlineLvl 0）而段落只有 style 2 → 仍是 body，证据数组含「数字样式标题」。
- **对比（同一管线成立的边界）：** TOC（`derived_toc`）、参考文献 SDT（`bibliography`）、页眉/脚注 story 均不进 evidence；完整 parse 仍保留 `grid_span`、story_parts、diagnostics。产品假 HTTP 测试确认 `derived_toc` / `grid_span` / `not_assessed` 进入请求体。
- **推理：** 章节请求指令写明“目录、标题、参考文献、页眉不独立证明研究参数”，但标题一旦进入 `evidence[]`，`read_chapter_draft` 只校验 ID 成员，模型可以合法引用标题句。这比 TOC 漏网更接近真实公司 DOCX。
- **建议修复：** `parse_docx` 按与 `node_tree` 相同口径解析 `styles.xml` 样式名/大纲继承；数字 heading styleId 不得当 body。补回归：styleId `2` + styles.xml、无本地 outlineLvl 的标题不得出现在 `bundle.evidence`。
- **不确定：** 冻结 TP-MA-07 源 DOCX 是否每个标题都带本地 `outlineLvl`。未打开生产 Word 文件（越界）。若源文件段落都有本地大纲，运行时风险下降，测试缺口仍在。

---

### 2. 章节顺序与全部载体覆盖

**证据**

- 当前模板 111 份 chapter contract = 111 registry 章 = `chapter_order` 长度 111。`heading_style_tree` 135 节点 / `outlined_tree` 139 节点。两树 `body_child_index` **无冲突**；order 内无重复 index；单调递增；首 `v2_front_block`（cover，index 0），末 `v2_n_16_x3`。
- 仅 outlined 的叶子：`v2_n_front_5`, `v2_n_16_x1/x2/x3`，被第二遍 outlined 位置纳入，避免文件名排序把 `v2_n_10_*` 提前（`test_document_order_uses_template_positions_instead_of_filename_sort`）。
- 29 个树节点无合同，样本为 `v2_n_1`, `v2_n_2`, `v2_n_10`, `v2_n_11_4` 等容器。计划按 **合同载体** 而非全部树节点记账。`plan_manuscript_chapters` 19–20 行要求 `chapter_order` 与 registry 集合全等。
- `node_tree.json` / `template.json` 仍标 `candidate_status: candidate_not_current`。运行时 `load_current_template` 仍把它当现行 authored 模板；`template_sha256` 与测试钉死值 `018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756` 一致。

**推理：** “每个 node 的原生模板顺序”在本代码里被实现为 **每个 chapter contract 载体** 的文档序，不是 135/139 个树节点全写。容器标题不进计划，符合 coverage_role 设计（heading_leaf / outline_only_leaf / cover）。`candidate_not_current` 更像抽取元数据残留，不是顺序算错的证据。

**建议：** 计划或 `template_identity` 增加一句：覆盖口径=合同载体∪front_block，容器节点有意缺席。若 Codex 认为“每个 node”含容器，才需要改范围——那会改变写作调度，不是修 bug。

---

### 3. 未知 vs 排除

**证据**

- 整章排除只允许 `affects_chapter_presence=true` 的规则。现行仅两条：`applicability:v2-n-16-x1:assessment`（ECOG）、`applicability:v2-n-16-x2:assessment`（NYHA）。内层 false 不藏章（`applicability.py` 380–384 注释与 snapshot 实现）。
- 稀疏 confirmed study：111 章全是 `needs_information`，**0 个** `not_applicable`。ECOG 缺触发事实 → `conditional_applicability_unresolved`，不是排除。
- 确认 `appendix.ecog_assessment_applicable=False`（外加 disposition 记录）→ ECOG `not_applicable`；NYHA 同理。`v2_n_16_x3` 合同 `conditional_applicability_rules: []`，QC 写明缺失走待补、**不得以不适用替代**——不能整章排除，属有意。
- Proposed study：`plan_manuscript_chapters` 在 snapshot 处直接 `ValueError('applicability requires confirmed study facts')`，单元测试禁止用 proposed 事实排除章节。GET 同一路径 **422**，公共信封是「请求内容与当前工作台要求不符」（`router.py` 126–131, 211–212）。`_EXCEPTION_MAP` 不含该 ValueError，故不会译成 typed `ProtocolWorkflowError`。
- 计划 `scope=chapter_fact_readiness`；`all_applicable_inputs_ready` 仅当每章 `facts_ready` 或 `not_applicable`。`facts_ready` 不读来源、不读 evidence、不读 Word。

**推理：** 未知/排除在 confirmed 路径上是分清的。Proposed 是整单失败而不是把章标成排除——语义上 fail-closed，符合“未确认不得排除”。但 API 把“研究未确认”伪装成请求形状错误，调用方看不到 111 个载体。

**建议：** 保持“proposed 不得排除”。把该 ValueError 译成既有 typed 码（例如 `D1_STUDY_DEFINITION_INCOMPLETE`），或返回计划对象外加 `study_not_confirmed`，章节一律 `needs_information`。不要用通用 422 请求信封。

**不确定：** 前端是否把 `all_applicable_inputs_ready` 画成“可以开写全文”。本次禁止评平行前端。

---

### 4. 期别同源映射

**证据**

- 两条 binding 共用 canonical `framing.study_phase`，legacy 含 `framing.structured_design.phase`。`affected_chapter_fact_paths` 对任一存储键都返回两条合同路径（历史失效范围保留）。
- `research_intent.py` 只写入 `framing.study_phase`，不写第二份期别。
- `bind_chapter_input` 优先 canonical，再比 legacy；冲突 fail-closed。研究字典不被改写（测试 `study.model_dump_json()` 前后相同）。
- 计划层在内层规则已决时，摘要与设计都会报 `fact_alias_conflict`（见缺陷 A）。内层未决时设计章漏报。
- `_resolved_input_contract` 投影 inactive 事实时只读 `study.facts[b.canonical_path]`（`applicability.py` 320–322），不读 legacy。期别不是适用性触发器，当前规则文件无 `framing.study_phase` 谓词。

**推理：** 同源与“不写重复事实”在 **binding 函数** 成立；**完整初稿计划** 在缺内层条件时不保证设计章冲突可见。legacy-only 期别仍能被 `bind_chapter_input` 读到。历史保留体现在 catalog + impact 路径，不体现在计划 payload 里的旧值。

**建议：** 缺陷 A 的拆分修复优先。其次给 `_resolved_input_contract` 与 `evaluate_predicate` 同一套 canonical/legacy 读取，避免将来有规则触发 `structured_design.phase` 时把只存新键的研究判成未决。

---

### 5. 完整 DOCX 结构 → 章节请求的事实/证据边界

**证据（保留）**

- `prepare_chapter_source_material` 把 `asdict(parsed)` 整包进 `sources[].parse`（blocks/rows/grid_span/vertical_merge/diagnostics/story_parts/parser_version/status）。`physical_page_count` 恒为 `None`；`status=parsed_pending_source_review`。
- 仅 `role=='body'` 的 `_units` 生成 `EvidenceUnit`：`canonical_state=proposed`，`quality_score=0`，`medical_admission=not_assessed`。TOC 句「表1 合成剂量」不在 evidence；表单元格「合成项目/合成值」在；`grid_span=2` 在 parse 不在 evidence。
- 页眉/脚注：parse 有 `header`/`footnote` 与对应 `story_parts`；evidence 只有正文。
- `prepare_chapter_draft` 要求 `source_material.evidence == payload.evidence`，否则 `chapter_source_evidence_mismatch`。指令禁止把 TOC/标题当研究参数、禁止把未评估质量改成已准入。
- `extracted_at` 由 owner 传入。同一 parse 换时间：evidence_unit_id 不变，`input_sha256` 变。符合“恢复读原包、不重新打时间戳”的注释，但 **没有** 挂载/缓存的生成端点（router/service 无 compile API；仅 `pinned_sources.read_pinned_chapter_sources` 辅助函数）。假 HTTP 产品测试在调用方传入 bundle 时原样送达。
- 指定测试含 `test_product_chapter_factory_calls_only_on_execution_and_reopens`：假传输、读既有 probe 收据、不碰真凭证。

**证据（边界缺口）**

- 缺陷 B：数字 styleId 标题进入 evidence。
- 带 `w:ins` 的修订插入句进入 body evidence（「插入句保留句」）；`w:delText` 删除句不进。diagnostics 有 `tracked_changes_present`，但 **evidence 单元不携带该码**。只消费 `evidence[]` 会丢掉“脏稿”警告。
- `table_text_coverage_pending` / `visual_objects_pending` / `unhandled_text_container` 同理：停在 parse.diagnostics。
- `quality_score=0` 与 ECOG 等 `minimum_quality_score: 0.9` 同用 `UnitInterval`。0 在单元上无法区分“未评估”与“评估为无价值”；缓解字段只在 bundle 根 `quality_score_basis`。
- 章节草稿校验只查 evidence ID 成员，不查 `source_role` 准入。`company_style_only` 正文仍成为可引用 proposed 证据（角色字段保留，准入后置）。这与“解析成功≠医学准入”一致，但事实/证据边界依赖后续 QC，不在本编译层闭合。

**推理：** 结构保真（表、合并单元格、stories、diagnostics）在 **source_material 整包** 上成立；**证据数组** 是“正文候选、未评估、可引用 ID”。TOC/参考文献/页眉/脚注达到目标。标题与修订插入未达到与指令相同的硬边界。未挂载生成端点是现状，不应当成已实现，也不应在本任务要求生产开通。

**建议：** (1) 修 heading 分类；(2) 修订标记存在时，要么不把 ins 文本升为 evidence，要么每个 evidence 复制 `diagnostic_codes`；(3) 保持 source_material 可选且调用方持久化 bundle，避免用 `now()` 重编译导致 `input_sha256` 漂移。不要把“尚未挂载”写成验收失败。

---

### 6. 读 API / SQLite / 钉住

**证据：** `get_manuscript_plan` 先 `get_study_definition`（当前 SQLite），再 `plan_manuscript_chapters(self._load_current_template(), current.definition)`。集成测试：111 章、`v2_front_block` 为首、`all_applicable_inputs_ready is False`、库 dump 不变、缺 ID 404、重开客户端同一 JSON。计划钉住 `study_sha256`、`template_identity`（template/registry/bindings/rules 哈希与计数）、`fact_catalog_sha256`、`applicability_snapshot`（`created_at=study.updated_at`）。模板每次从 loader/磁盘组装，不是 SQLite 快照。

**推理：** 研究侧是当前库的只读快照；模板侧是现行 authored 文件。这对“钉住当前 study/catalog”足够，只要调用方比较返回的哈希。不是单一事务里的 study+template 原子快照。

**建议：** 保持只读。若需要跨进程审计，把 `plan_sha256` 与 `study_sha256` 一起存，而不是假设磁盘模板永不改。

---

### 7. `facts_ready` 不是内容/证据完成

**证据：** 状态机只有 `not_applicable` / `needs_information` / `invalid_input` / `facts_ready`。成功绑定只写 `bound_input_sha256`。router summary「核对完整初稿所需研究信息」比 `scope=chapter_fact_readiness` 更像“全文输入已齐”。

**推理：** 代码未把 facts_ready 当成证据完成或医学完成。命名/文案可能让人把计划当成开写许可。

**建议：** 公共文案改为“章节事实齐备核对”；`all_applicable_inputs_ready` 可改 `all_applicable_facts_ready`。非本节点必改项，但是审查异议。

---

### 8. 分项结论（对 Codex 问题的直接回答）

| 问题 | 结论 | 标签 |
|---|---|---|
| 原生模板顺序覆盖全部载体 | **成立（111 合同载体）**；29 个容器树节点有意不在计划内 | 证据 |
| 未知 vs 排除 | **confirmed 路径成立**；proposed 整单 422，载体不可见 | 证据 + 缺陷 |
| 期别同源 | **binding 层成立**；计划层在设计章内层未决时漏报冲突 | 证据 + 缺陷 A |
| 不把 facts_ready 当内容/证据完成 | **数据结构成立**；路由文案偏大 | 证据 / 推理 |
| 读 API 用当前 SQLite 且只读 | **成立** | 证据 |
| 完整源结构表/stories/roles/diagnostics | **parse 整包成立** | 证据 |
| 不把 TOC 当正文证据 | **成立** | 证据 |
| 标题不当正文证据 | **对 Heading1/标题1/本地 outline 成立；对 styleId `2`+styles.xml 失败** | 缺陷 B |
| 假 HTTP 原样送达 | **指定产品测试成立**；未跑真模型 | 证据 |
| source_material 已挂生成端点 | **未实现**（按任务不得要求生产开通） | 证据 |

---

### 9. 对 Codex 的异议、方案、决策点、有界问题

**异议**

1. 用 `bind_applicable_chapter` 兼做“整稿记账”会在内层未决时丢掉 `fact_alias_conflict`。隔离期别测试因此**不能**代表完整计划。
2. 来源角色分类与 `node_tree` 不是同一套样式权威，标题可能被写成可引用 proposed 证据。
3. proposed GET 的 422 通用信封违反“未决节点保持可见”，尽管它没有错误排除。

**方案（按优先级）**

1. 计划循环拆分：`bind_chapter_input(原合同)` 收集 alias/缺事实；snapshot 管排除/未决；仅两者都过才 `facts_ready`。
2. `parse_docx` 读 `styles.xml`，补 styleId `2` 回归；修订 diagnostics 下沉到 evidence 或禁止 ins 升格。
3. proposed/未确认研究改为 typed 错误或仍返回 111 行 `needs_information`，不要通用请求信封。

**决策点（请 Codex 拍板，本节点不改源）**

1. 计划在适用性未决时，是否必须同时暴露 `fact_alias_conflict`？（建议：必须）
2. heading 分类是否必须与 `node_tree` 的 styles.xml 口径对齐？（建议：必须，否则指令与机器边界不一致）
3. proposed 研究的 manuscript-plan 是整单拒绝还是可见未决清单？（建议：可见未决 + typed 原因）
4. source_material 保持调用方持久化、不挂生成端点——是否仍为有意？（建议：是，与任务冻结范围一致）

**有界问题**

1. 缺陷 A 是否视为本冻结范围的必须修复，还是接受“先补齐内层条件再发现期别冲突”？影响：若不修，摘要/设计同源在整稿计划上不可审计。
2. TP-MA-07 源 DOCX 标题是否普遍缺少段落本地 `outlineLvl`？若 Codex 有该文件的既有解析统计，可降低缺陷 B 的现场严重度；测试缺口仍在。
3. `v2_n_16_x3` 永不 `not_applicable` 是否仍为产品意图？合同文案支持“是”。

**安全暂行路径：** 在 Codex 答复前，不要把 `all_applicable_inputs_ready` 或 `facts_ready` 解释成可调度写作；不要把 `evidence[]` 当作已排除标题/修订/目录后的准入证据；期别冲突须同时看 `bind_chapter_input` 与整稿计划，不能只信后者。

---

### 10. 未做 / 恢复点

- 未写 runner 报告文件；完整正文即本 Output。
- 未打开生产 DOCX、未跑非清单回归、未调用真 GLM、未启动服务。
- 若 Codex 要同一会话补测：从 `evidence_audit_followup.py` 的期别不对称与 styleId `2` 标题两条复现继续，不必重做哈希与 14 项 pytest。
