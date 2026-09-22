全部核查完成。以下为完整会议输出（由 runner 持久化到指定报告路径）。

# Conference Participant Output: mw_protocol_v3_wp6_final_review_20260923 - general_single_object

## Boundary Check

- 只读复核：未修改任何源码、测试、产品数据库、runtime 工件或 Word 文档。测试以独立 venv 只读运行（`runs/mw_protocol_v3_1r_integration_20260905/venv`），不触碰产品运行时。
- 工作目录限定在 runner 绑定的仓库内；未读取 `~/.codex/AGENTS.md`、`~/.hermes/SOUL.md`、任何 secret/config 运行时文件（`ai_provider_settings.json` 等均未打开）。
- 未查看其他参与者输出；未调用产品模型；未启动/停止服务；未宣称最终临床/法规/视觉/浏览器/用户验收权威，Codex 保留最终接受。
- 本报告为返回稿，未写入 `runs/conference/.../general_single_object.md`。

## Independent Work Product

**复核对象解读**：A = Study A v10 路由回执对账；V = V01–V08 桌面/视觉证据（`ego_v03_v08` 宽度字号指标 + `real_http_acceptance` 浏览器 PNG）；B = B01–B12 决定性反例（Studies B/C 真实旅程 + HTTP 验收 + Office/原生 Word roundtrip）。此解读未经 Codex 确认，见第 6 节问题 1。

### 冻结提交 e8966d5 工程复核（20 文件，全部已读 diff）

确认有效的修复，均有测试与真实证据支撑：

1. **重复采用修复三层防护完整**。服务端 409 双冲突码（`manuscript_document_revision_changed`/`manuscript_candidate_intent_changed`，`services/api/app/protocol_workflow/application/manuscript_documents.py:199,244`）；`get_saved_manuscript_document` 扫描事件流取末条 `manuscript_external_candidate_accepted.v1` 并过 `verify_event_integrity`（`manuscript_documents.py:57`）；前端按 `accepted_candidate_id === jobId` 隐藏采用按钮并改述文案（`ManuscriptWorkspace.jsx`，新增 Vitest 断言按钮不存在且不触发 recover）。HTTP 验收 call[8]/[9] 真实演示了双 409 → 重读最新稿 → call[11] 再采用成功。
2. **同 key 恢复只补未成立**：Study A attempt 1 在 19/22 处 429 终止，attempt 2 保留 18 个已完成 chunk、仅补 4 个（cms-router depth 2），`content_sections_unchanged: true`；新旧工件 sha256 不同源于回执补记（元数据层），正文未重写。
3. **Fallback 政策合规**：仅 429/408/5xx/不可达/空响应触发（`MODEL_ROUTING_2PLUS1_ACCEPTANCE_20260923.md`），实测 MTPLX 11234 未监听、opencode-go 429，均属允许触发；`candidate_is_current`（`medical_writing_full_draft.py:239-283`）对 document_id/version/binding/每节 expected_revision+body_sha256 逐一校验，任何漂移即 fail-closed 到 204；`list_by_project` 为 `ORDER BY created_at ASC`（`medical_writing_durable_jobs.py:429`），`reversed()` 取最新正确。
4. **Word/Office 所有权**：书签修复消除真实 schema 隐患（`w:pPr` 必须为 `w:p` 首子元素；进程随机 `hash()` 改 sha256 确定性 ID）；`[我已阅读` 括号清理在 DOCX 抽样中生效；人工 Word 与候选分离、下载不重生成覆盖的语义未被本提交破坏。
5. **凭证边界**：`resolve_omp_opencode_go_key` 只读取 `~/.omp/agent/.env` 中命名赋值，进程环境优先，0/多匹配 fail-closed，3 个新测试覆盖只读性与歧义拒绝。
6. **legacy→v2 映射**：`v1_to_v2_mapping.json` 实测 130 行 forward mapping、8 个空映射集合与测试断言逐一相同；`_current_nodes_for_legacy` 前缀展开+文档序+去重正确，每个 legacy 节只取首个 primary leaf，防止跨章重复。

独立复跑 14 个聚焦测试（模板运行时 3 项、导出所有权 2 项、凭证绑定 3 项/文件、mutation drift、marker context 等）：**14 passed in 1.06s**。未复跑 2608 后端全量与 111+66 前端（采信 Codex 提供的计数，见第 5 节）。

### Study C 候选 DOCX 医学抽样（309 段全文提取）

- **框架医学合理**：MDD 辅助治疗 II 期、18–65 岁、稳定 SSRI 应答不足、1:1 随机双盲安慰剂对照、20 mg 每晚一次×8 周、筛选 2 周+治疗 8 周+安全随访 2 周、访视 Wk1/2/4/6/8+Wk10、主要终点 Wk8 MADRS 变化、关键次要应答（≥50%）/缓解（≤10）、C-SSRS 特别关注、治疗策略 estimand+MMRM+跳转参考敏感性分析、无期中/无再估计——内部自洽且符合 II 期惯例。签字页合法空白、版本日期留空诚实。
- **P2 医学发现（样本量自相矛盾）**：正文以正式假设口吻写“约 170 例、组间差异 3 分、SD 8、双侧 α=0.05、把握度 90%、15% 失访”。按标准双样本公式，该参数约需 150/组（≈300 例）；170 例实际把握度约 60–70%。溯源（工件 evidence span 原文）显示数字来自注入种子的“当前正文=…计划约170例；**合成参数仅用于功能验收**”——即上游功能验收合成参数。工件层来源绑定完整保留了限定语，但 DOCX 正文写成确定假设并丢掉了“仅用于功能验收”限定；产品无样本量数值校验。此发现印证 2+1 验收 MD 自列的“逐章医学判断未完成”：正式使用前逐模块医学核查不可省，且“0 decision_required”反映上游字段已确认，而上游确认质量（如本例合成参数）是真正的弱环节。
- 术语：候选 r2 已归一（试验参与者 58/受试者 0）；成对近重复段落普遍（主要目的×2、总体设计×2、随机化盲法×2、样本量在 5.1 与 9.1 两章重复），工件 `review_advisories` 已如实提示“重复…建议压缩”，属工作稿可接受噪音但构成真实编辑负担。

### A/V/B 结论判断（建议口径）

- **A = PARTIAL**：恢复与只补未完成成立；但 18/22 条 opencode-go 回执 `legacy_inferred: true`（从旧记录推断补记，非原生持久化），且 MTPLX 生成质量未验证。
- **V = PARTIAL**：3 视口 DOM 几何与字号指标合格（minVisibleFontPx=12、无外溢、visibleTextBelow12=0），但该轮截图全部 CDP 超时（`screenshot: null`）；视觉证据仅有前一轮 4 张 PNG；且全库仍有约 350 处 sub-12px 字号声明（本提交只改 5 处），实测仅覆盖 writing desk 单页。
- **B = PARTIAL（偏强）**：真实 HTTP 全旅程（framing/picos 双阶段 impact-preview+commit、语料门 override、装配确认、source-policy 确认/项目级复用/重放、409 竞争、恢复、候选 DOCX 下载）、真实模型回执（22/22 chunk 三层深度+身份+原因）、Office 引文 roundtrip（增删后字段/文献表/格式保留、bad_xml 空）、原生 Word 16.113.1 改后保存重开（引文与标记存活）均成立；缺口为 MTPLX 质量、Study C 差异化旅程、逐章医学核查。
- **工作稿边界诚实**：working_draft_ready=true / adoption_ready=false / formal_ready=false 三级判定与证据一致；`formal_ready_reason` 明确列出申办者、版本日期等缺失，明确声明“这是可编辑工作稿”；验收断言 `forbidden_body_markers` 全 false 与新代码把 `【待处理】` 移出正文块一致（旧快照 wp6-office-snapshot-v5 含 110 个待处理标记属修复前产物，时间线自洽）。

## Evidence And Assumptions

- **观察（直接读取/运行）**：e8966d5 全部 20 文件 diff；9 份指定证据 JSON 全文；候选 r2 与 4 份快照 DOCX 的 XML 全文提取计数；`v1_to_v2_mapping.json`（130/8）；`list_by_project` SQL；Study C `full-draft.json`（sha256 与验收记录一致：de3bc490…）内嵌 evidence span 原文与 review_advisories；`run_acceptance_study.py` 真实 HTTP 驱动逻辑；14 项测试独立复跑通过。
- **推断**：`保密声明×4` 在全部产物一致 → 来自 TP-MA-07 v2 模板本身而非渲染 bug（未找到模板源文件比对，模板不在 `config/` 下）；study C roundtrip 文档（02:13，受试者 52）为修复前采用产物、r2（02:28）为修复后候选导出 → 时间线推断，无直接生成记录佐证。
- **采信 Codex 供给**：后端 2608 passed、前端 111+66、build 1971 modules——未独立复跑全量。
- **假设**：“A/V/B”含义按上文解读；V02 的 UI≥12px 契约范围假定覆盖全部产品 UI（若仅限 writing workbench，发现 3 降级）。

## Risks, Gaps, And Verification Needs

按严重度：

1. **P2（医学边界）**：样本量段落数值自相矛盾且丢失来源限定语（详见上）。需人工医学核查重写该章并回填真实参数；产品层面建议将“证据 span 原文含限定语而正文丢失”纳入 review 提示（可选，非阻断 working draft）。
2. **P3（术语单路径）**：`_normalize_candidate_text` 仅在 bridge 采用时生效；study C 当前工作稿仍为 受试者 52/试验参与者 6。要统一需重生成+重采用（旧候选已过期，受 409/current 规则约束）。需在验收结论文档记录该现状，防止“产品统一术语”被过度表述。
3. **P3（V02 证据面）**：约 350 处残留 sub-12px 声明 vs 实测单页三视口。若契约覆盖全 UI，需补一次全路由 computed-style 扫描；V 只能记 PARTIAL。
4. **P3（证据可复现性）**：`ego_v03_v08` 两个 DOCX 及其验收 JSON 无留痕生成脚本/命令（runs、scripts grep 无果），弱于 `real_http_acceptance` 的脚本化证据链。
5. **P3（回执强度）**：Study A 18/22 回执为 legacy 推断补记；`durable_provider: mixed` 如实，但“回执完整”只能算 PARTIAL。
6. **P4（观察）**：保密声明×4 疑为模板自带（建议人工确认模板意图）；App.jsx cleanup 中 `const runToken = …; if (… === runToken)` 条件恒真（等价无条件递增，功能无碍）；`_real_values` 在 sponsor 为空时产出“此信息属申办者所有”通用兜底（formal_ready_reason 已列缺失，影响有限）；`bad_xml: []` 仅证明良构不证明 schema 合法——真正的接受证据是 Word 实开实存，后续若要自动化 schema 校验需专门校验器。
7. **Owner 已自报的开放项（确认属实）**：两个旧竞品分析实现仍直连 provider、未入统一 runner fallback（2+1 MD 自列 P2 迁移项）；本地 MTPLX 恢复后的质量与身份验收未完成。
8. **未验证**：2608/111+66 全量回归未独立复跑；浏览器交互状态（V01/V04–V08 逐项）本轮无新证据，历史截图只能按同源码范围复用（契约原话）。

## Recommended Next Step

1. **给 Codex 的三个有界问题**：(a) “A/V/B”是否即 A=Study A 回执对账、V=V01–V08、B=B01–B12？若 V 另有所指，结论映射需校正。(b) study C 当前工作稿的术语混合状态是接受并记录（我的建议），还是安排一次重生成+重采用？(c) 350 处 sub-12px 是否在 V02 契约范围内？若是，是否补一次全路由扫描后再定 V 项结论。
2. **安全暂定路径**：(a) 未澄清前按我的解读交付；(b) 术语按“记录现状+仅对未来采用生效”处理；(c) V02 暂记 PARTIAL。
3. **建议的验收口径**：A=PARTIAL、V=PARTIAL、B=PARTIAL（偏强）；working_draft_ready=true、adoption_ready=false、formal_ready=false 维持原判；正式就绪前置条件保持：补齐 MTPLX 质量验证、Study C 差异化旅程、逐章医学核查（样本量章为首个已证实的必修点）、V02 全范围补扫（视问题 c 裁决）。
4. 本会话剩余预算充足；若 Codex 需要我对任一发现做同会话补证（如全路由字号扫描脚本草案或 roundtrip 文档路径追踪），可在同会话续问。
