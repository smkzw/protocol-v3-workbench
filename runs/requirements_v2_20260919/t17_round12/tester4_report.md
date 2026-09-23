Working...
# T17 第十二轮独立端到端测试报告（测试者4 · 膝OA / 合成药K3 · 入口B）

**SOURCE_HEAD**：`0874ab3fa1f3b2ea4c2f384c551bf1ba64d26c6d`（2026-09-23T20:42:24+08:00，R11 P1 批）
**环境**：前端 http://127.0.0.1:5186（vite dev）→ 后端 5301；MTPLX 8002；全程 ego lite（TaskSpace 43 / p1），黑盒 UI，未改仓库任何代码，未直连后端 API/DB。
**项目**：`合成药K3 · 膝关节骨关节炎（OA）疼痛 · II期 · MW-II-50F1E080`（内部 id `proj_user_82b59ebf62d0`）
**会话时长**：12:47:33Z → 13:37Z ≈ **50 分钟**；**点击数 ≈ 88**（明细见下）；截图 88 张于 `/tmp/t17_r12_tester4/`

---

## 1. PASSED / FAILED / NOT_RUN

### PASSED
| # | 项目 | 耗时 | 点击数 | 证据 |
|---|---|---|---|---|
| P1 | 开局 503（`monitoring_principal_unavailable`）识别为非缺陷并绕过 | <1 min | 1 | 01_landing.png |
| P2 | 新建项目（从零开始）：药物/适应症/II期 → 建项成功并预填方案号、标题、分期、开发区域 | ~2 min | 3 | 21_create_filled.png、22_after_create.png |
| P3 | **文献库 DOI 导入**：`10.1056/NEJMoa0901510` → 卡片 `Lane Nancy E. 等·2010 / NEJM·363·16·1521-1531 / 信息完整 / DOI 外链`，**与 PubMed 权威题录（Vol 363, Issue 16, 1521-31）逐项一致**；GB/T 7714-2015 顺序编码制选择器、题名/作者/期刊/DOI 搜索框、手动确认与来源输入耦合说明（R11 P1 修复）齐备 | ~30 s | 1 | 24_lit_import.png |
| P4 | 引文插入守卫：无编辑器时点“插入引文” → “请先在左侧打开文档编辑器，再插入引文。” | ~5 s | 1 | 84_insert_citation_guard.png |
| P5 | 竞品检索：锁定 501–637 项，检索计划把项目事实完整投影（Osteoarthritis, Knee / PHASE2 / INTERVENTIONAL + 靶点、目的、设计、人群、技术类型、给药途径、暴露 8 条分诊线索） | ~3 min | 0 | 23_workspace_top.png |
| P6 | **人工分诊可用**：搜索 `tanezumab` → NCT00994890（Pfizer PHASE2）→ 填理由 → “标记为直接竞品” → 计数 0→1；定稿理由≥10字提示（R11 P1 修复）有效 | ~2 min | 4 | 31_search_tanezumab.png、32_marked_direct.png |
| P7 | **事实采集（NL→事实拆解）质量高**：21 条候选，准确捕获 抗NGF/关节腔内注射/随机双盲安慰剂对照/16周/第16周WOMAC疼痛子量表/300例/对乙酰氨基酚≤3g/RPOA 类效应；对高影响定量字段**拒绝编造**（保持 unknown）；提出 3 个高价值医学追问 | 轮1 ~75 s；轮2 ~2 min | 15 | 43_facts_submitted.png |
| P8 | 语料例外放行审计诚实：勾选 5 项缺口 + 理由 → 状态“例外允许写作”，但门槛仍显示“**语料未就绪**”，缺口不被隐藏 | ~1 min | 6 | 75_override_done.png |
| P9 | 取消解析干净：入口A 提取中点“取消” → “本次解析已取消。您可以重新选择文件。” | ~5 s | 1 | 20_after_cancel.png |
| P10 | 反拟合：本项目内容 24 词**零命中**（详见 §6） | — | 0 | — |

### FAILED
| # | 项目 | 耗时 | 点击数 | 证据 |
|---|---|---|---|---|
| F1 | 入口A（导入方案摘要）夹具解析失败：通用文案无原因 → “继续处理”后出现英文内部串 `synopsis import route configuration changed after task start`，再次点击状态完全不变（死循环），不给出路 | ~4 min（含等待） | 6 | 11_extract_failed.png、12_after_continue.png |
| F2 | 竞品分诊失败且**不可从 UI 恢复**：`重试当前分诊` → HTTP 409 `当前失败不属于竞品分诊节点，不能从分诊入口恢复`；界面**零反馈**，连点 3 次状态不变 | ~7 min | 4 | 26_triage_retry.png、28_retry2.png、72_retry_triage2.png |
| F3 | 第二快照“按当前信息重新分诊”后仍为“12 个分诊批次未完成”，`competitor-triage/ct_run_.../retry` 返回 202 但 `reused:true` 且无进展 | ~3 min | 2 | 71_retriage.png |
| F4 | 锁定竞品篮子 → 422 英文原串直出 `PICOS and competitor search must be complete before triage finalization` | ~1 min | 2 | 33_after_lock.png |
| F5 | 事实采集第2轮提交 → 422 英文内部路径直出 `...fact intake proposal[3] exact high-impact field framing.product_profile.confirmed_facts.safety_threshold must be explicitly user_stated or source_extracted`（改写为显式“未知”后 200，可恢复但不可读） | ~2 min | 2 | 46_after_422.png、47_round2_retry.png |
| F6 | **建立工作稿被科学设计阻断门拒绝**（重复 3 次均同）：`protocol-assembly-plan/confirm` → 409 `protocol assembly plan still has unresolved scientific design blockers: intervention.active_comparator_regimen, intervention.background_treatment, intervention.investigational_product_dose_actions, intervention.investigational_product_regimen, intervention.permitted_concomitant_treatment, intervention.placebo_regimen, intervention.prohibited_concomitant_treatment, intervention.rescue_treatment` —— 旅程界面**这 8 个字段没有任何录入控件**，语料例外放行也不覆盖；错误以英文+内部路径透出 | ~10 min | 4 | 77_assembly_blocker.png、85_final_blocker.png、87_retry_blocker.png |

### NOT_RUN（被 F2+F6 阻断，未到达编辑器）
- (a) 文内层：编号自动生成、删/移段落联动重排、点击编号回跳文献卡/来源 —— 未验证（库层与插入守卫已验证）
- (b) 目录、表目录/图目录、图表编号与交叉引用、预览跳转 —— 未验证（依赖对象“研究流程图/研究流程表/研究摘要”在前端影响清单中存在，见 50_impact_panel.png）
- (c) 研究流程图生成与入正文 —— 未验证（同上，产品概念存在但页面不可达）
- 全文初稿 AI 生成、Word 预览/正式导出、Office 打开编辑保存 —— 未验证

---

## 2. 问题清单

### P0-1 分诊失败无出路：重试入口被后端拒绝且界面零反馈（全链第一断点）
- **现象**：抽屉内“部分分块失败：…可直接重试当前分诊”，点击“重试当前分诊”后 `POST /research-pipeline/retry-triage` 返回 **409** `{"detail":"当前失败不属于竞品分诊节点，不能从分诊入口恢复"}`（页面侧抓包实测），UI 不显示任何反馈，按钮仍在，形成静默死路。
- **复现**：医学写作→项目 K3→竞品处理抽屉→“重试当前分诊”→观察无任何状态变化（连点 3 次）。
- **证据**：`/tmp/t17_r12_tester4/26_triage_retry.png`、`28_retry2.png`；后端日志 `POST .../retry-triage → 409 Conflict`（71→127 次 `triage chunk ... provider call failed: AI provider request failed: HTTP 400`）。
- **[INFERENCE] 根因线索**：重试门（`services/api/app/medical_writing_research_pipeline.py:1429-1444`）枚举的分诊失败形态含 `分诊任务结束为 failed/cancelled`，但父层实际写入的是 `分诊任务结束为 {status}`（同文件 1651/1713 行），**partial_failed 不在可重试形态内**；同一门内注释已记录过同类 409 死锁（P1#4）——本次是未覆盖的新形态。

### P0-2 语料例外放行后仍无法建立工作稿：8 项干预设计阻断门无 UI 入口
- **现象**：`进入写作平台` → 409，8 个 `intervention.*` 字段未解析；旅程界面（PICOS 干预措施页签）仅有“干预概述/用法用量”两个文本框，**其余 8 个字段无任何控件**；错误以英文+内部字段路径直出，尽管前端已有中文标签映射（`MedicalWritingAuthoringJourneySetup.jsx:3859-3868` `ASSEMBLY_PLAN_BLOCKER_LABELS`：活动对照的具体方案/背景治疗规则/试验药物剂量调整规则/给药途径方案/允许的合并治疗/安慰剂方案/禁止的合并治疗/救援治疗规则）。
- **复现**：完成 PICOS → 语料准备 → 勾 5 缺口 + 例外说明 → “进入写作平台” → 底部“建立工作稿失败：…（英文原串）重试”。
- **影响**：即使走完产品自己提供的“例外进入写作”，编辑器/全文初稿/导出/重点模块(a 文内)(b)(c) 全部不可达。
- **证据**：`/tmp/t17_r12_tester4/85_final_blocker.png`、`77_assembly_blocker.png`、`80_intervention.png`（干预页签仅 2 字段）。

### P1（内部串/标识符直出，纪律项）
| # | 直出内容 | 出现位置 | 截图 |
|---|---|---|---|
| P1-1 | `synopsis import route configuration changed after task start`（英文原串，属路由类失败，R11 大白话映射未覆盖 resume 报错路径） | 入口A“继续处理”后 alert | 12_after_continue.png |
| P1-2 | `事实采集未完成：fact intake proposal[3] exact high-impact field framing.product_profile.confirmed_facts.safety_threshold must be explicitly user_stated or source_extracted` | 事实采集第2轮 | 46_after_422.png |
| P1-3 | `操作未完成：PICOS and competitor search must be complete before triage finalization` | 锁定竞品篮子 | 33_after_lock.png |
| P1-4 | `自动调研未完成：the current competitor search plan already has an immutable search snapshot` | 语料准备页“检索计划”尾行 | 82_corpus_stage.png |
| P1-5 | `建立工作稿失败：protocol assembly plan still has unresolved scientific design blockers: intervention.…`（8 条内部路径；中文标签映射未生效） | PICOS/语料页底 | 85_final_blocker.png |
| P1-6 | 内部快照 ID 直出：`当前工作区已保存本次公开检索快照（wref_search_238a018887275107dd28）` | 建稿前语料准备 | 82_corpus_stage.png |
| P1-7 | 枚举值直出：事实候选值显示 `monoclonal_antibody`（非“单克隆抗体”） | 事实拆解列表 | 43_facts_submitted.png |

### P2（易用性/一致性）
- **P2-1** `完成第一步` disabled 时 tooltip 仅“请先补齐第一步必填项…”，不指出**具体缺哪几项**（实际缺 设计模式/目标人群意图/内在研究目的，只能经事实拆解补齐）。（35_step1_filled.png）
- **P2-2** 给药途径选项无“关节腔内注射”（本项目核心给药方式），只能选“其他”。（同图）
- **P2-3** **第一步↔第二步 dirty 往返**：PICOS 每次改动后需“返回第一步→完成第一步→确认变更并重新核验”，四轮往返，每轮 1–3 min 重核验，且不告知第一步变了什么。（54–59 系列）
- **P2-4** PICOS 维度长期显示“待确认”，而 `<select>` 实际已有值（显示/状态不一致）。（57_dims.png）
- **P2-5** 刷新页面后项目下拉回落到出厂 demo（RUX-03-002），丢失当前项目上下文，需重选。（38_after_reload2.png）
- **P2-6** 项目下拉混入其他测试者/他轮项目（含 类风湿/银屑病/多发性硬化/抑郁症 等）——隔离性观察。（30/31 图）
- **P2-7** 检索精度：锁定的 637/501 项含明显无关项（如 HNSCC 头颈癌试验 NCT00652613），本应由分诊拦截，但分诊失败后原样保留。
- **P2-8** DOI 显示为小写 `10.1056/nejmoa0901510`（注册形式为大写 NEJM）。
- **P2-9** 候选检索框不支持机制词（搜 `NGF` 得 0 项；仅 NCT/标题/申办方）。

---

## 3. 重点模块结论表

| 模块 | 结论 | 逐项观察 |
|---|---|---|
| **(a) 文献引用与管理** | **库层 PASSED / 文内层 NOT_RUN** | ✅ DOI 导入元数据与 PubMed 权威源逐项一致；GB/T 7714-2015 顺序编码制锁定；题名/作者/期刊/DOI 搜索；手动确认必须复用上方来源标识（R11 P1 修复文案到位）；无编辑器时插入引文有明确前置提示。❌ 编号自动性、删/移段落联动、编号回跳来源：因编辑器不可达未验证。**用户最小期望**：正文 `[1]` 顺序编号 + 删/移段落后正文与文末文献表同事务重排 + 点击编号回跳文献卡。 |
| **(b) 目录与图表呈现** | **NOT_RUN（缺前提）** | 未生成工作稿即无目录/表目录/图目录可验；前端影响清单明确存在下游对象“研究摘要/研究流程表/研究流程图”，说明概念在系统内。**用户最小期望**：导出 Word 含可点击目录（标题锚点）+ 独立表目录/图目录（表1/图1 顺序编号、题注统一）+ 交叉引用可跳转。 |
| **(c) 研究流程示意图** | **NOT_RUN（缺前提）** | 工作台可见范围内无流程图入口；流程图生成依赖 PICOS/设计事实投影，而投影被 P0-2 阻断。**用户最小期望**：筛选→随机→双盲16周→随访 的纵向节点图，随设计事实自动生成、可微调、可入正文并随导出保留。 |

---

## 4. 易用性专题（中年、非 AI/非网页熟练的医学写作者视角）

1. **看不懂**：`完成第一步/完成第二步` 灰显无原因（P2-1）——不知缺什么、去哪补。
2. **找不到**：设计模式/目标人群意图/内在研究目的无显式表单，只能“粘贴一段话让 AI 拆”；不写自然语言就永远无法完成第一步。
3. **易误点**：“继续处理”（入口A）点下去像“继续解析”，实际是重试同一条已失败请求，且零反馈（F1）。
4. **重复劳动**：第一步↔第二步四轮往返 + 每轮重新核验，不知道改了哪一项（P2-3）。
5. **术语墙**：`例外放行/语料准入/分诊/组装计划/科学设计阻断门` 无解释；阻断门文案为英文内部路径（P1-5）。
6. **状态不自洽**：维度显示“待确认”但已选值（P2-4）；刷新后项目回到别的项目（P2-5）。
7. **本专业缺项**：给药途径无“关节腔内注射”（P2-2）；救援/背景治疗等 8 个干预要素在界面上无处可填（P0-2）。
8. **等待无引导**：>8 min 提取只有“1/1 内容块 · 已运行 N 分钟”，无预计时间、无后台化提示、刷新即丢（外部 vite 重启曾直接清空对话框）。
9. **反馈缺失**：所有 409/422 均无界面提示（F2/F4/F6），用户只能反复点。

---

## 5. 耗时与点击明细

- 阶段耗时：环境门禁（含诊断与等待他人重启）≈ 5 min｜入口A 探索 ≈ 19 min（其中 AI 等待 ~12 min）｜建项 & 文献 & 检索 ≈ 5 min｜分诊重试/手工分诊/锁定 ≈ 10 min｜事实采集两轮 + 采纳 ≈ 9 min｜第一步提交 & 影响核验 ≈ 3 min｜PICOS 填写与提交 ≈ 8 min｜语料例外 + 建稿尝试 ≈ 6 min。
- 点击：总 **≈88**（超 ≤20 达标线）。构成：环境门禁重试 5｜入口A 夹具路径 14｜主线必要操作 ≈ 36（建项 3、文献 2、分诊 6、事实 20、提交 5）｜**缺陷恢复性重复点击 ≈ 33**（重试分诊/锁定/建稿/往返第一步共 12+，事实与 PICOS 的 12 项逐条“采用”属产品设计）。
- 关键量化：分诊 provider 失败 chunk 71→127（两次运行）；`retry-triage` 409 ×3；`assembly-plan/confirm` 409 ×3；`corpus-triage/finalize` 422 ×1；`fact-intake/turns` 422 ×1（重试 200）。

---

## 6. 反拟合检索表（24 词 + 内部串）

| 类别 | 结果 |
|---|---|
| 子宫内膜异位/甲状腺眼病/肺纤维化/IPF/痛风/CLL/荨麻疹/白癜风/AML/骨髓瘤/便秘/镰状/IgAN/MASH/强直/干眼/前列腺/结直肠癌/偏头痛/COPD | **本项目零命中** |
| 类风湿 / 银屑病 / 多发性硬化 / 抑郁症 | 仅出现在顶部**他项目下拉**（RA-GREENFIELD 演示、CMS-D001 演示、M8、MDD×2），非本项目内容 |
| 内部标识符 | 命中 1 类：`wref_search_238a018887275107dd28`（P1-6）；`mwprefillcand_/ct_chunk_/Pydantic/Traceback/ct_run_/mwjob_/mwintake_` 界面零命中 |

---

## 7. KNOWN_LIMITATIONS

1. **环境**：开局 12:47–12:52 被“前后端构建不一致”门禁阻断（vite 5186 启动于提交前、5301 后端重启于提交后）；经重算指纹确认前端 dev server 过期（当前源 `api-c2e8194ba29bb425`/`web-6cad5f5cd01adc03`，`frontend/dist/runtime-build.json` 已正确配对），由**外部/同伴重启**恢复，非产品缺陷。期间我的重复启动尝试因 macOS 无 `setsid` 失败，未改动任何文件。
2. 会话中前端 dev server 被（他人）重启 3 次，导致 1 次解析 UI 丢失（环境事件，非产品）。
3. ego-browser 提示可升级 Ego Lite 0.5.1.11 —— **未升级**（需用户确认）。
4. 分诊 chunk 的 provider HTTP 400 归因未定（后端日志仅记“AI provider request failed: HTTP 400”，MTPLX 8002 请求日志无对应错误记录）——可能为路由/契约侧问题，标 [INFERENCE]。
5. 入口A 的 8 分钟提取未完成即被我主动取消（共享 MTPLX 被 4 名测试者争用，非缺陷判定）；夹具 `synthetic-reference.docx` 内容本身不是方案摘要，解析拒绝可理解。
6. 因 P0-2 未到达编辑器，模块 (b)(c) 与文内引用为 **NOT_RUN（缺前提）**，不等于“功能正常”。
7. 未验证 全文初稿/Word 导出/Office 编辑（依赖工作稿）。

**EXIT=BLOCKED:建立工作稿被 8 项干预设计阻断门拒绝且界面无录入入口（P0-2），叠加竞品分诊重试 409 静默死路（P0-1），编辑器与重点模块 (b)(c) 不可达**

EXIT=0
