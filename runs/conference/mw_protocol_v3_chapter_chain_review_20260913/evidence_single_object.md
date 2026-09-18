独立审阅章节候选链。先读取指定上下文、计划和冻结清单，再按实际代码与测试核验。冻结清单已确认。接下来读取清单内源码与测试，并追踪它们直接导入的定义。源码主体已读完。接着核对测试与纠错/恢复相关直接导入。纠错、进度与图运行时是关键导入，接下来核对这些直接定义和并发/恢复行为。接下来跑指定测试，并用只读脚本核验几个高影响边界。# Conference Output: mw_protocol_v3_chapter_chain_review_20260913 - evidence_single_object

## Output

独立工程审阅（非医学/Word/浏览器验收）。冻结 13 文件 SHA256 与 `artifact_manifest.json` 一致。指定三项测试 14 passed。未改源码，未调用产品模型，未读历史审阅报告。

### 审阅边界与挑战

计划把 Agent③ 写成「候选链、不准入」。这在 `read_chapter_draft` 注释和 `needs_content_review` 状态上成立。最高影响缺口不在「误把候选当医学批准」，而在：**最常见的引用身份失败进纠错时，精确结构错误被丢掉**；嵌套表来源字段可携带输入宇宙外的 ID 仍通过结构门。这两点会在真实模型输出上表现为：纠错不知道修什么、或表内伪引用被当成已通过身份核验。

---

### 分类约定

- **证据**：当前文件/测试/只读脚本的直接观察
- **推断**：由证据得出、尚未被指定三项测试覆盖的结论
- **建议**：最小补救，不实施
- **不确定**：未跑或无法在本边界内证明

---

### 轴 1 — 有序候选 vs 内容 QC/准入

**证据**

- `OrderedChapterDraftCandidate` 文档写明：候选、非 `SemanticDocumentRevision`；`known_evidence_ids` 只证明 ID 在调用方宇宙内，不是医学真实性/准入/打分（`registries/ordered_draft.py:14-20`）。
- `read_chapter_draft` 在返回前注明 transport/identity only（`agent3/chapter_draft.py:80-82`）。
- `subgraph.validate` 成功时：`valid=True`，`status=needs_content_review`，`validation_scope=structure_and_input_identity`（`agent3/subgraph.py:107-108`）。失败：`valid=False`，`status=needs_structure_correction`，`proposal=None`（`109`）。
- `test_chapter_draft_workflow` 对合法/畸形 JSON 分别断言上述状态；SQLite 中 `study_definition_repository.list_current` 与 `semantic_document_repository.list_current` 均为空。
- 候选 `extra=forbid`：只读脚本对输出加 `quality_score` 得到 `extra_forbidden`。空/空白段落 → `ValueError: chapter_draft_empty`。

**推断**：状态机没有把结构通过写成医学或 Word 完成。指定测试覆盖 JSON 合法性与空块，不覆盖「正文是否编造研究参数」（属内容 QC，本链故意不做）。

**建议**：保持该区分。不要把 `valid=True` 接到准入或整稿装配。

---

### 轴 2 — 研究 id/revision/hash 与有效适用性合同身份

**证据（绑定成立）**

- `BoundChapterSkillInput` 携带 `project_id` / `study_definition_id` / `study_revision` / `study_sha256` / `chapter_contract_sha256` / `applicability_rules_sha256`（`fact_bindings.py:50-59, 290-308`）。
- `prepare_chapter_draft` 对 `BoundChapterSkillInput` 校验 `chapter_contract_sha256 == contract.material_sha256()`（`chapter_draft.py:44-46`）。旧绑定改 `word_rules` 伪装新合同会 `chapter_input_binding_mismatch`（`test_chapter_draft_request.py:63-75`）。
- `ChapterDraftCoordinator.run_id` 在 `schema_version == protocol-v3-bound-chapter-input.v1` 时核对 coordinator 的 project/study/hash（`coordinator.py:28-32`）；`start` 在不一致时拒绝（`test_chapter_draft_request.py:97-112`）。
- `prepare_study_chapter` 走 `bind_applicable_chapter`，调用方不能拼接事实（`chapter_draft.py:85-93`）。适用性投影后 `chapter_contract_sha256` 等于有效合同 hash（`test_chapter_draft_request.py:78-94`）。
- 产品工厂测试用 `bind_chapter_input` + `study_revision_hash(study)` 重开后提案文本仍在。

**证据（缺口，已复现）**

1. **未绑定输入可绕过研究身份写入模型材料。** `prepare_chapter_draft` 类型是 `ChapterSkillInput`；仅当 `isinstance(..., BoundChapterSkillInput)` 才核合同 hash。`inputs()` 与 `test_chapter_draft_workflow` 使用未绑定输入。只读脚本：`chapter_input` 键只有 `active_conditional_rule_ids, chapter_contract_id, node_id, resolved_facts, template_id, template_sha256, word_rules`，无 `study_definition_id` / `study_sha256`。`run_id` 的研究核对也只在 bound schema 上执行（`coordinator.py:28`）。
2. **`prepare_study_chapter` 不拒绝整章不适用。** 对 `v2_n_16_x1`，`appendix.ecog_assessment_applicable=False` 时：`prepare_study_chapter` 成功（`active_conditional_rule_ids=[]`，事实仍写入）；`build_applicability_snapshot` 同研究同章为 `not_applicable`（规则 `affects_chapter_presence: true`，`applicability_rules.json:341`）。存在「快照排除、编译器仍出稿」分叉。
3. **产品工厂不强制 `prepare_study_chapter` 或 Bound 输入。** `create_product_chapter_factory` 只把 study 身份放进 coordinator（`product.py:30-39`）。`test_chapter_product_factory` 用 `bind_chapter_input`，不是适用性编译器。

**建议**

- `prepare_chapter_draft` / `coordinator.start` / 产品 `start` 拒绝非 `BoundChapterSkillInput`。
- `prepare_study_chapter` 在 presence 规则为 `NOT_APPLICABLE` 时失败关闭，或要求调用方先给 `ApplicabilitySnapshot` 且该节点为适用。
- 在整稿循环接上之前，不要对 registry 全节点盲目 `prepare_study_chapter`。

---

### 轴 3 — 完整来源正文/ID 宇宙 vs 无依据医学主张

**证据（正文与块级引用）**

- `prepare_chapter_draft` 把完整 `EvidenceUnit.model_dump` 打进 payload（`chapter_draft.py:54`）。`test_chapter_draft_request` 断言 `body` 以「原文末句」结尾且 JSON round-trip 不共享可变事实。
- `test_chapter_draft_workflow` 断言伪造 HTTP 的 user message 含「原文末句」（完整 artifact，非截断）。`artifact_messages.py:13-14, 29-34`：全文或拒绝，禁止当完整材料截断。
- 模型若自报 `known_evidence_ids` 且不等于输入宇宙 → `chapter_source_universe_mismatch`（`chapter_draft.py:70-72`，测试覆盖）。省略该字段时由输入宇宙注入。
- 块级 `evidence_refs` 悬空 → Pydantic `dangling evidence_refs...`（`ordered_draft.py:177-188`）。

**证据（已复现的宇宙漏洞）**

- `OrderedChapterDraftCandidate._validate_order_identity_and_refs` 只遍历 `block.evidence_refs`，不遍历 `StructuredTable` 的 `provenance_lineage` / `notes.source_refs`（`ordered_draft.py:177-188`；`ordered_draft.py` 无 `provenance_lineage`）。
- 只读脚本：表单元格 `provenance_lineage=['evidence:invented']`、note `source_refs=['evidence:invented']`，块级 `evidence_refs=('evidence:known',)` 时候选 **validate 成功**。
- `StructuredTableCell.provenance_lineage` 与 `StructuredTableNote.source_refs` 是自由 `List[str]`（`models.py:1678, 1700`）。
- 指令写「引用仅使用输入 evidence_unit_id」（`chapter_draft.py:17`），结构门未覆盖嵌套表字段。
- 正文是否编造 `resolved_facts` 外参数：本层不查（内容 QC）。`refuse_occurrences_as_instances` 存在但 **agent3 解析路径未调用**。

**建议**：结构门增加对 table `provenance_lineage` 与 note `source_refs` 的宇宙成员检查（与 `evidence_refs` 相同，仍声明非医学真实性）。正文/事实一致性仍留给内容 QC。

---

### 轴 4 — 原始畸形响应保留 + 精确结构错误 + 单次同模型纠错

**证据（保留与单次纠错成立）**

- `persist_model_response` 把原始 `content` 与 receipt 打成 `model_response.v1`（`model_response.py:9-16`）。workflow 测试：`record['content']==raw`（含 `synthetic invalid JSON`）。
- `structure_correction_inputs` 把 `previous_output=record['content']`、`errors=validation['errors']` 放入 `correction_context`；若原 receipt 已有 `correction-context` → `chapter_correction_budget_exhausted`（`proposal_correction.py:4-20`）。
- 纠错 generate 核 provider/model/effort（`subgraph.py:63-65`）。logical_key `chapter-draft.correct.v1`，`allowed_attempts=1`。
- `test_chapter_product_factory`：`correction=True` 时 HTTP=2；重开后再 `resume` 仍为 2；原 artifact 仍为 `'broken chapter JSON'`；第二次消息含原文与 `chapter_invalid_json`。`still_invalid` 时 `can_resume is False`，`proposal is None`。

**证据（精确结构错误：JSON 有，Pydantic 身份失败无 — 已复现）**

`subgraph.py:97-105`：

| 失败类 | 进入纠错的 errors | 是否精确 |
|---|---|---|
| `JSONDecodeError` | `chapter_invalid_json` + `line:N:column:M` | 是（测试覆盖） |
| 显式 `ValueError` 且 `chapter_*` | 该 code | 是（空稿、绑定、自报宇宙） |
| `ValidationError` | `code=chapter_output_schema_invalid`，`location=loc`，`issue=type` | **否：丢掉 `msg`** |

只读脚本：模型按指令省略 `known_evidence_ids`、块引用 `evidence:missing` 时：

- Pydantic `msg` 为 `dangling evidence_refs not present in known_evidence_ids: ['evidence:missing']`
- 按 subgraph 映射后：`{'code': 'chapter_output_schema_invalid', 'location': '', 'issue': 'value_error'}`

这是指令下最可能的引用失败。纠错模型只能看到空 location 的 `value_error`。重复 `block_id`、表内外 `block_id` 不一致同类。

**建议**：`exc.errors()` 增加 `msg`（及 `ctx` 若有）。至少把 `value_error` 的原始字符串送进 `errors[].detail`。不要静默吞掉。与 agent1/agent2 同模式不是本章免责理由。

---

### 轴 5 — 并发 / 重开 / 未知结局

**证据（重开，已复现）**

- `start`：已有 run 则 `prepared_request` 核 `run_id`，不二次 `start_run`（`coordinator.py:40-53`）。
- `start_run` 对相同 plan+root hash 幂等（`graph/runtime.py:315-361, 1687-1710`）。
- 产品测试：新 factory、同一 sqlite+artifacts 路径，`start(prepared)` 得到同一 `run`，事件相等，第二次 `resume` 不增加 HTTP。
- workflow：新 `runtime()` 共享 sqlite，`run_to_completion` 不增加 opener.calls。
- `read`：无纠错 run 且原验证为 `needs_structure_correction` → `can_resume=True`（`coordinator.py:75-78`）；纠错 run 已存在则读纠错结局（`still_invalid` → `can_resume=False`）。
- `proposal_outcome`：`blocked` 且节点 `blocked_unknown` 且 live dispatch → `status=running`，`can_resume=False`；完成后 `can_resume=False`（`proposal_progress.py:4-20`）。
- 凭证：`create_product_chapter_factory` 后、`resume` 前 `key_reads==[]` 且 `opener.calls==0`。

**推断（代码审查，未做线程复现）**

- 相同 `run_id` 并发 `start`：后到者走幂等 reuse，不双创建。
- 并发 `resume`：都看到原 run 需纠错，对 `:correction:1` `start_run` 幂等；`allowed_attempts=1` 应挡二次 dispatch。**未做线程测试。**
- `resume` 需要 `artifact_store`（`coordinator.py:95`）。workflow 测试构造的 coordinator 默认 `artifact_store=None`；产品工厂有 store。无 store 时 `read` 仍可把 `can_resume=True`，`resume` 会崩。
- 校验节点结果事件缺失时 `proposal_outcome` 会 `StopIteration`，不是带类型的 unknown 状态。

**建议**：`resume` 在 `self.artifacts is None` 时 typed fail；`read` 在校验事件缺失时返回 typed unknown，而不是崩溃。并发 `resume` 作为集成预条件留给图预约，不要在未测时宣称已证明。

---

### 轴 6 — skill / schema / graph 注册一致性

**证据**

- 运行时 skill：`skill.chapter-draft`，`agent_role=full_draft`，tools `product-llm`，URI `chapter-draft-input/output.v1.json`（`skill_registry.json:239-278`）。产品工厂与 workflow 测试加载该条目。
- 图：`graph_id=chapter-draft` / `chapter-draft-correction`，`graph_version=chapter-draft.v1`；generate `owner=full_draft`，`logical_key=chapter-draft.generate.v1` 或 `.correct.v1`，`allowed_attempts=1`；validate `owner=system`，`chapter-draft.validate.v1`。与 role `full_draft` 一致。
- 角色 `product-llm` / `glm-5.3-flash` / `zhipu-coding-plan` 与 skill `tool_versions.product-llm` 一致。`chapter_execution_contract` 拒绝非该 skill 或非 llm role（`subgraph.py:33-35`）。
- **不一致**：实际校验/提示 schema 是 `OrderedChapterDraftCandidate.model_json_schema()`（`chapter_draft.py:55`），不是 registry URI。Zhipu 请求 body 只有 artifacts，不含把 URI 当 JSON Schema 约束（`zhipu_api.py:268-308`）。功能上模型看到的是候选 schema。
- 章级 `chapter_skills/v2_n_3_1_1.json` 仍声明 `ChapterSkillOutput`。`ordered_draft.py:32-38` 写明旧输出不改、候选并行。不把「未接整稿/Word」本身当新缺陷。
- 声明的 `acceptance_test_ids`（`test.chapter-draft.substantive-contract-met` 等）不是本冻结测试名。`idempotency_policy.key_basis` 为 `chapter-contract-id+fact-revision`；实际 `run_id` 为 project+branch+study_id+study_sha+input_sha（更强）。

**建议**：把 `skill.chapter-draft` 的 `output_schema_ref` 标成有序候选 schema（或 `module:OrderedChapterDraftCandidate`），避免将来 Codex/其他 harness 按旧 URI 约束。章级 `ChapterSkillOutput` 保持并行，直到确认步显式采用。

---

### 轴 7 — 产品接线未挂载、仅候选

**证据**

- `create_product_chapter_factory` / `ChapterDraftCoordinator` / `prepare_study_chapter` 的生产引用仅在 `agent3/` 与 `tests/protocol_v3/test_chapter_*.py`。无 router/API 挂载。
- 工厂构造不读凭证、不发 HTTP；执行才解析。无服务进程。
- 未把「无 UI / 无整稿 / 无 Word」算作新实现缺陷。

**集成预条件（现有代码，尚未有用户界面损失）**

- 调用方必须同时保留 sqlite 与 `{path}.artifacts`。
- 调用方必须 `resume`（或等价 `run_to_completion`）；`start` 只播种。
- 适用章节应走 `prepare_study_chapter`（或 snapshot 后再编译），不要对未绑定 `ChapterSkillInput` 调产品 `start`。

---

### 指定测试

命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api:.:tests:tests/protocol_v3:tests/protocol_v3/integration`  
`runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest -p no:cacheprovider --basetemp=runs/conference/mw_protocol_v3_chapter_chain_review_20260913/scratch/pytest`  
`tests/protocol_v3/test_chapter_draft_request.py tests/protocol_v3/test_chapter_draft_workflow.py tests/protocol_v3/test_chapter_product_factory.py`

**结果：14 passed，1.00s。** 未重跑历史 probe，未解析真实凭证。未改 fixture / xfail。未跑 `test_ordered_chapter_draft.py`（按指令限这三项）；嵌套表宇宙漏洞由只读脚本直接打 carrier。

---

### 发现清单（按用户可见功能损失）

**F1 — 已复现 — Pydantic 结构失败进入纠错时丢掉精确错误**

- 文件：`services/api/app/protocol_workflow/agent3/subgraph.py:101-103`
- 触发：模型省略 `known_evidence_ids`（与指令一致），`evidence_refs` 含宇宙外 ID；或重复 `block_id` / 表身份不一致。
- 观察：纠错 `errors` 为 `{code: chapter_output_schema_invalid, location: '', issue: value_error}`。
- 期望：保留精确结构错误（悬空 ID 列表、重复 block_id 等），供同模型一次纠错。
- 证据：Pydantic `msg` 存在；映射脚本丢掉它。JSON 路径有精确 location（测试覆盖）。
- 最小补救：errors 增加 `msg`/`detail`。

**F2 — 已复现 — 嵌套表来源字段绕过 ID 宇宙门**

- 文件：`services/api/app/protocol_workflow/registries/ordered_draft.py:177-188`
- 触发：合法 `evidence_refs` + 单元格 `provenance_lineage` 或 note `source_refs` 为虚构 ID。
- 观察：候选 validate 成功。
- 期望：引用身份与指令一致，输入宇宙外 ID 不得出现在候选可引用字段。
- 证据：只读脚本 `PROVENANCE_HOLE True`。
- 最小补救：对 lineage/source_refs 做与 `evidence_refs` 相同的宇宙成员检查。

**F3 — 已复现 — 适用性快照排除的章仍可编译**

- 文件：`services/api/app/protocol_workflow/agent3/chapter_draft.py:85-93`；`registries/applicability.py:353-360` vs `380-426`
- 触发：`prepare_study_chapter(template, study, 'v2_n_16_x1', ())` 且 `appendix.ecog_assessment_applicable=False`。
- 观察：编译成功；snapshot 为 `not_applicable`。
- 期望：有效适用性合同身份包含整章 presence；不适用则不应出写作请求。
- 证据：只读脚本 `PREPARE_ECOG_NA ok` 与 `SNAPSHOT_ECOG not_applicable`。
- 最小补救：presence `NOT_APPLICABLE` 时失败关闭。当前无整稿循环，属集成预条件，不是已挂载 UI 损失。

**F4 — 已复现 — 未绑定输入缺少研究身份**

- 文件：`agent3/chapter_draft.py:36-46`；`agent3/coordinator.py:28-32`
- 触发：`prepare_chapter_draft(contract, ChapterSkillInput(...), evidence)`（workflow 测试即此）。
- 观察：payload 无 study id/hash；coordinator 研究核验跳过。
- 期望：产品路径上写作材料绑定当前研究。
- 证据：只读脚本 `UNBOUND_KEYS`；workflow 测试用 `inputs()`。
- 最小补救：产品 `start` 要求 bound schema。workflow 测试是合成路径，不证明产品绑定。

非缺陷（有界证据）：候选 vs QC 状态分离；bound 路径研究/合同 hash；完整证据正文进 HTTP；畸形原文保留；单次同模型纠错预算；sqlite+artifact 重开不重放；执行前不读凭证；产品工厂未挂 router。

---

### 对 Codex 的异议、方案、决策点、有界问题

**异议**

1. 「结构纠错带精确错误」目前只对非法 JSON 为真。最可能的引用失败是 Pydantic `value_error`，纠错看不到悬空 ID。
2. 「ID 宇宙」只盖块级 `evidence_refs`。表内 provenance 可藏无依据引用，同时 `valid=True` / `needs_content_review`。
3. 「有效适用性合同」在 `prepare_study_chapter` 是义务投影，不是 presence。ECOG/NYHA 附录在快照不适用时仍可出稿。
4. 指定 workflow 测试用未绑定输入，会夸大「研究绑定已在恢复路径上证明」。产品测试才证明 bound 恢复。

**方案**

- F1：纠错 errors 保留 Pydantic `msg`。
- F2：嵌套表引用纳入宇宙门。
- F3：presence 关闭或强制 snapshot。
- F4：产品 start 拒绝未绑定输入。
- 不要把 `needs_content_review` 接到准入/Word。

**决策点（会改变结论，需 Codex）**

1. 表 `provenance_lineage` / note `source_refs` 算本层结构身份，还是留给内容 QC？
2. `prepare_study_chapter` 是否必须拒绝 `affects_chapter_presence=NOT_APPLICABLE`？
3. 是否打破与 agent1/agent2 相同的「只转发 pydantic type」模式，给章节纠错完整 `msg`？
4. 未绑定 `ChapterSkillInput` 是否仍为允许的合成测试路径，还是产品编译器必须 bound？

**有界问题**

- Q1：F2 是否作为结构缺陷纳入本章候选门，还是书面定为内容 QC？影响是否改 `ordered_draft.py`。  
  暂定：当作结构漏洞报告；采用前不要把带未核验 lineage 的表当已通过来源身份。
- Q2：整稿循环前，F3 是现在修的编译器缺陷，还是调用方必须先读 snapshot？  
  暂定：集成预条件；不要对全 registry 节点盲目 `prepare_study_chapter`。
- Q3：F1 是否要求与 regimen/seed 同步改 errors 形状？  
  暂定：章节链单独需要精确 `msg`；JSON 路径已满足指定测试。

**未做 / 不确定**

- 无线程并发 `resume`。
- 未跑 `test_ordered_chapter_draft.py`（指令限三项）；carrier 行为由只读脚本覆盖。
- 无浏览器/Word/医学权威。
- 无产品模型、无真实凭证、无服务。
- Codex 保留最终接受权。
