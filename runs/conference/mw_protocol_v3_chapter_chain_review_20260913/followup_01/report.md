针对 F1–F4 做同会话核验：先读 followup 冻结清单和当前代码，再对照 owner 决策检查补救是否真正落地。清单显示若干文件哈希已变，`ordered_draft.py` 未变。接着对照 owner 决策核验这些改动。补救已写进代码。接下来跑指定测试，并核验 schema 同源、F2 定位语义与 F3 未决/排除边界。F1–F4 补救已在当前冻结文件落地。27 项测试通过；schema 与运行时同源。下面给出有界核验结论和残留集成要求。

# Conference Output: mw_protocol_v3_chapter_chain_review_20260913 - evidence_single_object

## Output

同会话 follow-up：按 owner 决策核验 F1–F4 是否在**当前冻结文件**上真正成立。只读；未改源码；未调用产品模型；未查看并行 UI/API 任务。`followup_01/artifact_manifest.json` 14 文件 SHA256 一致。`ordered_draft.py` 与 `test_ordered_chapter_draft.py` 哈希相对初审未变（载体语义保留）。

指定测试：`test_chapter_draft_request.py`、`test_chapter_draft_workflow.py`、`test_chapter_product_factory.py`、`test_ordered_chapter_draft.py`  
**27 passed / 1.23s**（含负例：dangling detail、表内虚构 lineage/note refs、整章 `not_applicable`、产品路径拒绝未绑定输入）。未重跑历史 probe，未解析真实凭证。

本轮**不声称**内容 QC / 医学 / Word 验收。

---

### 分类

- **证据**：当前文件、测试、只读脚本
- **推断**：由证据得出、指定测试未覆盖的结论
- **建议**：残留集成要求或 hardening，不实施
- **不确定**：未跑项

---

### F1 — Pydantic `msg` 作为 `detail`：**成立**

**证据**

- `subgraph.py:101-103`：`ValidationError` 映射含 `"detail": item["msg"]`。
- `subgraph.py:104-105`：`ChapterDraftReferenceError` 单独处理，带 `code` / `location` / `detail`；该类是 `ValueError` 子类（`chapter_draft.py:23-28`），`except` 顺序在通用 `ValueError` 之前，不会被收成仅有 code 的条目。
- `test_chapter_draft_workflow.py` `malformed=='dangling'`：断言 `'evidence:missing' in result['errors'][0]['detail']`，且原始 `content` 仍保留。
- 只读脚本按同一映射：`detail` 为 `dangling evidence_refs not present in known_evidence_ids: ['evidence:missing'] ...`；`location` 仍为 `''`（Pydantic `loc=()`）。

**推断**：JSON 非法路径仍有精确行列；块级悬空引用现在有可读 `detail`。空 `location` 不阻碍纠错阅读 `detail`。

**未改**：通用 `ValueError`（如 `chapter_draft_empty`）仍只有 `code`。Owner 要求的是 Pydantic `msg`，不是所有 ValueError。表嵌套引用走 `ChapterDraftReferenceError`，有 location+detail。

**残留**：表嵌套错误穿过完整 generate→validate→纠错 HTTP 的路径没有单独 pytest；handler 代码顺序正确。属覆盖缺口，不是 F1 失败。

---

### F2 — 生成输出边界强制嵌套 lineage / note source_refs；载体 locator 语义保留：**成立，有集成摩擦**

**证据（门在 `read_chapter_draft`，不在载体）**

- `ordered_draft.py` 哈希未变。只读脚本：载体仍接受单元格 `provenance_lineage=['evidence:invented']`。
- `test_ordered_chapter_draft.py` 9 passed（遗留 carrier 未回退）。
- `chapter_draft.py:88-99`：仅在 `model_validate` 之后扫描 `cell.provenance_lineage` 与 `note.source_refs`；不在宇宙内则 `ChapterDraftReferenceError`。
- `test_generated_table_nested_references`（cell/note）负例：`chapter_table_reference_unknown`。
- `source_locator` 未纳入宇宙门。只读脚本：表/单元格 `source_locator='invented:...'` 仍通过。符合「保留一般 StructuredTable/ordered 载体的 locator 语义」。

**挑战（最高影响残留）**

历史 `StructuredTableNote.source_refs` 是 **locator**（`_2x2_table` 默认 `['docx:t1:note']`），不是 `evidence_unit_id`。生成边界现在把 `source_refs` **全部**当作证据 ID。

只读脚本：仅提供 `evidence:e1`/`evidence:e2`、保留默认 note `source_refs=['docx:t1:note']` → `chapter_table_reference_unknown` at `blocks.0.table.notes.0.source_refs`。

F2 正例测试通过的办法是**额外造一个** `evidence_unit_id='docx:t1:note'` 的 EvidenceUnit。这是测试迁就，不是模型自然输出。

指令同时要求「引用仅用 evidence_unit_id」和「完整保留表格脚注和引用定位」。若模型把脚注定位写进 `source_refs`（载体旧语义），结构门会失败并进入一次纠错。Locator 应写在仍未设门的 `source_locator` / `marker_source_locator`。

**建议（集成，非否决 F2）**

- 生成表：`provenance_lineage` 与 `note.source_refs` 只放输入 `evidence_unit_id`；docx 定位放 `source_locator` 类字段。
- 不要把 locator 字符串登记成假 evidence unit（测试可以，产品路径不行）。
- 空字符串 lineage 同样拒绝（已复现 `Reference '' is not in the supplied evidence IDs`）——正确 fail-closed。

**不确定**：未跑表嵌套失败的同模型纠错 HTTP（F1 dangling 段级已覆盖 detail 转发）。

---

### F3 — 整章排除前使用现有适用性快照：**成立（排除 = `not_applicable`）**

**证据**

- `prepare_study_chapter`（`chapter_draft.py:105-117`）先 `build_applicability_snapshot((entry.contract,), ...)`，`entries[0].status.value == 'not_applicable'` 则 `chapter_not_applicable`，否则才 `bind_applicable_chapter`。
- `test_whole_chapter_not_applicable_does_not_create_a_writing_request`：ECOG 事实为 false → 该错误。
- 适用章（interim false）仍能编译（既有 `test_study_chapter_preparation_uses_current_catalog_and_actual_study`）。

**边角（fail-closed，但不是 `chapter_not_applicable`）**

- Owner 决策是 **excluded whole chapters**。快照 `CONDITIONAL`（缺触发事实）**不会**在 snapshot 门被拒。
- 只读：`v2_n_16_x1` 缺 ECOG 事实 → `ApplicabilityResolutionError: conditional_applicability_unresolved:...`（bind 路径）。interim 章同样。无写作请求。
- 每次 `prepare_study_chapter` **现场重建** snapshot（`created_at=study.updated_at`），不绑定已持久化的 `applicability_snapshot_id`。用的是现有构建函数，不是调用方持有的快照对象。

**建议**

- 调用方把 `chapter_not_applicable` 与 `ApplicabilityResolutionError` 都当「不要发写作请求」。
- 不要对 registry 全节点盲目编译；排除章现在会 typed 失败。
- 若需要与已批准 snapshot 字节级一致，需另接 snapshot id（当前未做）。属后续集成，不是 F3 失败。

---

### F4 — 产品工厂要求绑定输入；低层合成运输测试保持未绑定：**成立**

**证据**

- `product.py:37-39`：`require_bound_input=True`。
- `coordinator.py:13, 25-30`：默认 `False`；为 True 且 `schema_version != protocol-v3-bound-chapter-input.v1` → `chapter_bound_input_required`。Bound 输入仍核 project/study/hash。
- `test_chapter_product_factory`：`correction is False` 时未绑定 `start` 被拒；绑定输入照常执行/重开。
- `test_chapter_draft_workflow` 仍用 `inputs()` 未绑定 `ChapterSkillInput`，coordinator 默认不要求 bound；SQLite 恢复负例仍在。

**残留**

- `prepare_chapter_draft` 仍接受未绑定 `ChapterSkillInput`。产品闸在 factory/coordinator 标志，不在 prepare。
- 手写 `ChapterDraftCoordinator(require_bound_input=False)` 仍能对未绑定材料 `start`。产品路径必须走 factory。
- 产品 coordinator **不能** `read` 一条未绑定 run（`run_id()` 先抛 `chapter_bound_input_required`）。低层与产品身份空间按设计分开。

---

### 注册：输出 URI 与 `key_basis`

**证据**

- `skill_registry.json`：`output_schema_ref=https://protocol-v3.local/schemas/ordered-chapter-draft-candidate.v1.json`；新文件在 `config/medical_writing/protocol_v3/schemas/ordered-chapter-draft-candidate.v1.json`。
- **同源相等**：文件 JSON == `OrderedChapterDraftCandidate.model_json_schema()` == `prepare_chapter_draft` payload 的 `output_schema`（只读 `SCHEMA_EQUAL True` / `PAYLOAD_SCHEMA_EQ_FILE True`）。
- `key_basis`：`chapter-draft:project+branch+study-id+study-sha256+complete-input-sha256`，与 `run_id` 材料（project、branch、study id、study sha、`input_sha256`）一致。`run_id` 另含字面量 `chapter-draft.request.v1`（命名空间，不是身份输入遗漏）。

**残留（非本轮 output URI 决策失败）**

- `input_schema_ref` 仍为 `chapter-draft-input.v1.json`，**该路径无文件**（`INPUT_SCHEMA_FILE_EXISTS False`）。Zhipu 路径不按 URI 约束 JSON Schema（提示里是 payload 内 schema）。其他 harness 若解析 input URI 会找不到文件。
- 章级 `chapter_skills/*.json` 仍声明 `ChapterSkillOutput`（并行旧路径；`ordered_draft.py` 未改）。不把未挂载整稿/Word/并行 UI 算新缺陷。
- `acceptance_test_ids` 仍非 pytest 名。

---

### 其他轴（相对初审，无回归）

| 轴 | 本轮 |
|---|---|
| 候选 vs QC | 仍 `needs_content_review` / `needs_structure_correction`；`validation_scope=structure_and_input_identity`；不写 study/document。dangling 负例保留。 |
| 重开 | 产品三参仍：执行前无凭证/HTTP；纠错保留原文；`still_invalid` → `can_resume is False`。 |
| 未挂载 | factory 仍仅测试+`agent3/product.py`。并行 UI/API **未审**。 |

---

### 发现 vs 残留

**无新的用户可见功能损失否决 F1–F4。** 四项补救在声明边界上成立。

残留集成要求（优先）：

1. **生成表字段约定**：`provenance_lineage` / `note.source_refs` = 输入 `evidence_unit_id`；定位字符串只用 `source_locator` 类字段。否则 `chapter_table_reference_unknown`（已复现）。
2. 产品执行只走 `create_product_chapter_factory`（或显式 `require_bound_input=True`）。
3. `prepare_study_chapter`：`not_applicable` → `chapter_not_applicable`；未决 → `ApplicabilityResolutionError`。两者都不要发写作请求。
4. Input URI 仍无 schema 文件；output URI 已与 shipped 候选 schema 同源。
5. `resume` 仍需要 `artifact_store`；workflow 默认 coordinator 无 store（低层、非产品）。

---

### 异议、方案、决策点、有界问题

**异议**

- F2 正例靠把 locator `docx:t1:note` 注册成 evidence id。真实模型若按旧表语义把脚注定位写入 `source_refs`，会稳定打进结构纠错。这是边界选择，不是门没装上。
- F3 只挡 snapshot `not_applicable`，未决靠 bind 失败。符合「excluded」，但错误码不统一。
- 产品绑定闸可被默认 coordinator 绕过——与 owner「低层测试保持未绑定」一致，不能当成全局不变量。

**方案**

- 写作提示/下游解析明确：嵌套引用字段只允许 evidence id。
- 可选：`prepare_study_chapter` 对 snapshot `conditional` 给 typed `chapter_applicability_unresolved`（非必须，已 fail-closed）。
- 不要改 `ordered_draft.py` 来「修」locator；那会违反本轮载体不变决策。

**决策点（若 Codex 还要收紧）**

1. 生成输出是否应对 `note.source_refs` 与 `provenance_lineage` 区别对待（仅 lineage 当证据 ID，source_refs 保持 locator）？当前两者都当证据 ID。
2. 未决整章是否应在 snapshot 门拒绝，还是维持 bind 错误？

**有界问题**

- Q1：是否接受「生成 `source_refs` 必须是 evidence id，locator 走 `source_locator`」作为产品约定？  
  **暂定**：接受；F2 按 owner 边界成立。采用前把该约定告诉写作提示，避免无意义纠错循环。
- Q2：并行 UI/API 是否调用 `prepare_study_chapter` / factory？  
  **暂定**：本冻结集未包含那些文件，**未审**。若 UI 直接 `prepare_chapter_draft`+未绑定 coordinator，F3/F4 不会自动生效。

Codex 保留最终接受权。
