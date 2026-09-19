Working...
# T17 独立端到端测试者2 测试报告

## SOURCE_HEAD
- **前端状态**：`http://127.0.0.1:5176/`（Build ID: `web-0eaf4868fff491f0`）
- **后端状态**：`http://127.0.0.1:5275/api/runtime-readiness`（Build ID: `api-d7875fbd70aa93f6`，Schema Version: `16`）
- **合同版本**：`medical-writing-api-2026-07-17.1`
- **新建测试项目**：`proj_user_46d16b7f0da5`（`合成药M · 慢性偏头痛 · III期 · MW-III-25919ED8`）
- **测试场景**：【场景2·入口B：从零设计，零附件】慢性偏头痛预防性治疗 III期（合成药M，CGRP单抗，皮下注射，24周，每月偏头痛天数较基线变化，约600例）
- **浏览器执行环境**：`ego-browser` 独立 TaskSpace（Space ID: `128`），无任何代码修改，操作全量通过真实页面交互完成。

---

## 步骤执行与判定（PASSED / FAILED / NOT_RUN）

| 步骤 | 耗时 | 用户点击次数 | 判定 | 核心事实与证据 |
|---|---|---|---|---|
| **Step 1: 打开前端创建新项目（含"偏头痛"）** | 3.1s | 2 次 | **PASSED** | 首页点击「新建项目」，填入药物「合成药M」、适应症「慢性偏头痛」、分期「III期」，点击「创建并进入写作」。成功建立 `MW-III-25919ED8`。截图：`/tmp/t17_tester2/09_writing_workspace_entry.png`。 |
| **Step 2: 入口B零附件仅写作说明推进** | 4.1s | 2 次 | **FAILED** | 1. 在 `ProtocolIntakeWorkspace` 入口下：因新建项目未自动准入白名单，`GET /protocol-workflow/sources` 返回 HTTP 404，「准备写作材料」按钮被物理禁用（`prepareDisabled=true`），无法点击推进（阻断缺陷）。<br>2. 在 `WritingPage` 入口下：无附件可正常进入；但在「补充产品事实」填入简述并点击「提交并拆解」时，后端触发模型标识校验异常，报 `fact intake AI provider failed: AI provider response model identity does not match the configured model (actual=deepseek-flash, expected=deepseek-v4-flash)`，事实拆解中断。截图：`/tmp/t17_tester2/14_protocol_intake_workspace.png`、`/tmp/t17_tester2/22_fact_parsing_settled.png`。 |
| **Step 3: 验证A03（零附件准入与来源透明）** | 3.1s | 2 次 | **PASSED** | 系统未强制要求上传 IB 或附件，支持选择「暂不提供IB」与「在保留全部缺口的情况下例外进入写作」；候选推荐明确标注依据为 `study_definition · framing.*`，未伪造文献或外源 ID；缺口以结构化方式透出（`未锁定精确年龄上下限...确定性预填不构成可采用的临床设计结论`）。截图：`/tmp/t17_tester2/55_override_acknowledged.png`。 |
| **Step 4: AI设计选项逐卡点选与推荐依据核对** | 5.5s | 4 次 | **PARTIALLY PASSED** | 1. 第一阶段框架标题成功采用 `合成药M治疗慢性偏头痛的III期临床研究方案`，来源追踪透明；<br>2. 第二阶段 PICOS 模块卡片：因竞品流水线在分块 13/20 遭遇 `CompetitorTriageError` 失败，6个组合卡片均退化为「需您选择/补全，无置信」；点击「采用当前方案文字建议」可自动将随机化、盲法、对照、分组填充为确定性值；手动建立 IN-01、EX-01、干预措施、主要终点及约600例样本量策略。截图：`/tmp/t17_tester2/39_adopted_text_suggestions.png`、`/tmp/t17_tester2/50_tab_stats_filled.png`。 |
| **Step 5: 生成完整初稿→保存→导出Word** | 5.1s | 1 次 | **FAILED** | 完成第一步（框架）、第二步（PICOS）及语料例外放行后，点击「进入写作平台」触发 `POST /api/projects/{id}/medical-writing/greenfield-document`。后端抛出 `PlanUnconfirmedError: plan revision 1 for project proj_user_46d16b7f0da5 has not been confirmed by an author`（前端从未调用且无 UI 触发 `/protocol-assembly-plan/confirm`）。建稿阻断，无法进入正文编辑器。截图：`/tmp/t17_tester2/57_enter_writing_platform.png`。 |
| **Step 5.1: 保存正文** | — | 0 次 | **NOT_RUN** | 因 Step 5 建稿阻断，正文未生成。 |
| **Step 5.2: 导出Word** | — | 0 次 | **NOT_RUN** | 因 Step 5 建稿阻断，导出无法执行。 |
| **Step 6: 数值合理性与反拟合核查** | 0.2s | 0 次 | **PASSED** | 全库与项目状态反拟合检索：无斑秃、鼻窦炎、鼻息肉、CRSwNP、SALT、SNOT、合成药T/X、固定缓解率或存储温度等无关疾病数值泄漏。 |

- **建项到受阻总点击数**：`11` 次（≤ 20 次，符合测试指标要求）。

---

## 问题清单

### [P0] 阻断缺陷 #1：初稿生成因装配计划缺少作者确认报错阻断（`PlanUnconfirmedError`）
- **现象**：在完成研究框架、PICOS设计并签署语料例外放行后，点击「进入写作平台」时界面报错：`建立工作稿失败：plan revision 1 for project proj_user_46d16b7f0da5 has not been confirmed by an author`。
- **根因**：后端 `medical_writing_plan_consumption.py:108` 强校验装配计划的 `confirmation_status == "author_confirmed"`；但前端 `MedicalWritingAuthoringJourneySetup.jsx:createDocument()` 直接 `POST /greenfield-document`，既没有在前置调用 `POST /protocol-assembly-plan/confirm`，前端界面上也未提供任何供作者确认装配计划的按钮或卡片，导致正文建稿彻底阻断。
- **复现步骤**：
  1. 打开 `http://127.0.0.1:5176`，新建从零设计项目；
  2. 补齐框架与 PICOS 必填项，完成第一步与第二步；
  3. 在语料准备阶段展开「在保留全部缺口的情况下例外进入写作」，勾选5项缺口并填入理由，点击「确认例外并放行」；
  4. 点击「进入写作平台」。
- **截图证据**：`/tmp/t17_tester2/57_enter_writing_platform.png`

---

### [P0] 阻断缺陷 #2：Protocol v3 Intake 界面下新项目无法起步（`prepareDisabled` 恒真）
- **现象**：当开启 `VITE_PROTOCOL_V3_WORKFLOW_ENABLED=true` 访问 `ProtocolIntakeWorkspace` 时，页面报错 `未找到所请求的方案工作流对象。请核对项目与对象标识后重新请求。`，且「准备写作材料」按钮呈灰显禁用状态，无法提交写作说明。
- **根因**：用户在前端通过 `POST /api/projects` 建立的项目并未自动加入 `protocol_workflow_project_allowlist` 表；`ProtocolSourceIntake.jsx` 挂载时请求 `GET /protocol-workflow/sources` 返回 HTTP 404；导致 `visibleSources === null`，代码第 254 行计算 `prepareDisabled = true`，禁用提交按钮。
- **复现步骤**：
  1. 配置 `VITE_PROTOCOL_V3_WORKFLOW_ENABLED=true` 启动前端；
  2. 首页新建项目并进入「医学写作」；
  3. 观察提示横幅及「准备写作材料」按钮状态。
- **截图证据**：`/tmp/t17_tester2/14_protocol_intake_workspace.png`、`/tmp/t17_tester2/16_brief_filled.png`

---

### [P1] 严重缺陷 #3：DeepSeek 模型响应标识不匹配导致全线后台 AI 任务崩溃
- **现象**：在自然语言事实采集、竞品分诊及语料分析时，界面报底层错误：`事实采集未完成：fact intake AI provider failed: AI provider response model identity does not match the configured model (actual=deepseek-flash, expected=deepseek-v4-flash)`。竞品流水线卡死在 23%（分块 13/20）。
- **根因**：`ai_gateway.py:1215` 严格比对 API 返回报文中的 `model` 字段与配置的 `WORKBENCH_AI_EXPECTED_RESPONSE_MODEL`（`deepseek-v4-flash`）；DeepSeek 官方线上真实返回值为 `deepseek-flash`，导致校验直接抛出 `AiProviderRuntimeError`，所有后台语义调用（事实提取、分诊、语料分析）全部失败，且工程级异常文本直接暴露在用户界面。
- **复现步骤**：
  1. 在「高级微调」->「补充产品事实」中输入文本；
  2. 点击「提交并拆解」；
  3. 等待约 35 秒查看状态信息。
- **截图证据**：`/tmp/t17_tester2/22_fact_parsing_settled.png`、`/tmp/t17_tester2/44_after_retry_result.png`

---

### [P1] 严重缺陷 #4：竞品流水线失败提示重试但接口返回 HTTP 409 死锁
- **现象**：竞品分诊流水线失败后，抽屉提示 `研究流水线失败。可直接重试当前分诊。` 并提供「重试当前分诊」按钮；点击后接口报错 HTTP 409：`当前失败不属于竞品分诊节点，不能从分诊入口恢复`。
- **根因**：`medical_writing_research_pipeline.py:1410` 中恢复校验使用硬编码前缀 `error_summary.startswith("competitor_triage_")`，而流水线实际抛出的异常类型字符串为 `CompetitorTriageError: ...`，未能匹配判断逻辑，导致后端误判并拒绝恢复。
- **复现步骤**：
  1. 流水线分诊失败后点击「打开竞品处理」；
  2. 点击「重试当前分诊」；
  3. 观察网络面板返回值。
- **截图证据**：`/tmp/t17_tester2/26_competitor_drawer_open.png`、`/tmp/t17_tester2/27_after_retry_click.png`

---

### [P2] 体验/规范建议 #5：前端端口默认代理指向未启动后端引发 503 假死
- **现象**：若未显式指定 `VITE_API_PROXY_TARGET`，Vite 默认将 `/api` 代理到 `8910`（无 AI 配置端口），导致前端页面展示大屏拦截红屏 `当前版本组合不可进入写作工作区（HTTP 503）`。
- **建议**：`vite.config.mjs` 应与集成测试环境脚本保持一致，默认对准已配置独立的 `5275` 端口，并在连接失败时提供用户友好的服务状态提示而非版本不匹配阻断。
- **截图证据**：`/tmp/t17_tester2/05_after_recheck.png`

---

## 反拟合检索结果表

在已持久化的项目数据（`authoring-journey`、`study-definition`、`protocol-assembly-plan`）中针对规定词库执行全量扫描：

| 检索词 | 出现次数 | 上下文事实摘要 / 判定 | 判定 |
|---|---|---|---|
| **斑秃** | 0 | 无任何出现 | **PASSED**（无串入） |
| **偏头痛** | 71 | 全部位于本研究适应症、诊断标准及终点描述（`慢性偏头痛`、`每月偏头痛天数较基线的变化量`） | **PASSED**（属于本品合法语义） |
| **鼻窦炎** | 0 | 无任何出现 | **PASSED**（无串入） |
| **鼻息肉** | 0 | 无任何出现 | **PASSED**（无串入） |
| **CRSwNP** | 0 | 无任何出现 | **PASSED**（无串入） |
| **SALT** | 0 | 无任何出现 | **PASSED**（无串入） |
| **SNOT** | 0 | 无任何出现 | **PASSED**（无串入） |
| **合成药T** | 0 | 无任何出现 | **PASSED**（无串入） |
| **合成药M** | 48 | 全部位于试验药物定义及干预用量（`合成药M用于治疗慢性偏头痛...`、`合成药M每4周皮下注射一次`） | **PASSED**（属于本品合法药物名） |
| **合成药X** | 0 | 无任何出现 | **PASSED**（无串入） |
| **20%** | 0 | 无任何出现（本研究设定脱落率为15%） | **PASSED**（无固定模板硬编码） |
| **35%** | 0 | 无任何出现 | **PASSED**（无固定模板硬编码） |
| **第24周** | 7 | 全部位于本研究设定的主要终点评价时点与双盲治疗期结束访视 | **PASSED**（符合本研究24周关键设计） |
| **2℃～8℃ / 2-8℃** | 0 | 无任何出现 | **PASSED**（无默认保存温度残留） |

---

## KNOWN_LIMITATIONS
1. **正文初稿渲染与原生编辑未验证**：由于 Step 5 中 `PlanUnconfirmedError` 导致工作稿建稿失败，未能进入基于 Tiptap/GenOffice 的实际正文富文本编辑工作区。
2. **Word导出及格式回核未验证**：由于正文对象未生成，无法触发 `document.docx` 导出接口，未能验证导出文档的样式、TOC域及表格题注书签。
3. **AI生成候选方案包质量未实测**：由于后台 DeepSeek 响应模型名校验异常，竞品分析流水线中途失败，未能体验基于 297 项公开偏头痛研究全自动产出的 3~5 个精细化推荐包内容。
