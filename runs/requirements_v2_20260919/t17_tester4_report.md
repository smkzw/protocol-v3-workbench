Working...
# T17 独立端到端测试报告 · 测试者4 · 场景4（自选领域交叉验证）

## SOURCE_HEAD

**测试对象**：康哲 AI 医学经理工作台，前端 `http://127.0.0.1:5176`（HTTP 200）
**测试窗口**：2026-09-19 20:55 → 22:17（约 82 分钟），ego-browser 真实浏览器操作（Node.js heredoc）
**自选领域**：2型糖尿病（T2DM）· II期；试验药物 `HMS5552（多格列艾汀）`；入口方式＝纯文字（"从零开始"），未上传文件
**生成项目**：`HMS5552（多格列艾汀） · 2型糖尿病 · II期 · MW-II-84B2E103`（已持久化，重载后仍在项目列表）

**进入时的系统状态（首屏）**
- 项目总览：`项目总览暂不可用 · HTTP 503 · code=monitoring_principal_unavailable`（"服务器尚未提供可验证的当前用户身份"）
- 项目选择器已有 13 个他人项目（磷酸芦可替尼乳膏/特应性皮炎、MY009/溃疡性结肠炎、MG-K10/CRSwNP、合成药U/溃疡性结肠炎、合成药M/慢性偏头痛 等）
- 侧边栏折叠为 64px 图标栏；8 个模块除"医学写作"外均为"功能未配置"
- 来源台账同样报"服务器验证身份尚未接入，旧版医学监查读取已阻断"

**最终状态（版本 14，重载后复核一致）**
```
项目状态：研究框架待确认          来源：从零开始 · 版本 14
竞品调研进度：研究流水线失败
竞品方案处理：公开研究检索已保留 · 1304 项研究；后续处理未完成，请查看原因并重试
AI推荐研究方案：研究设计(正交维度)/干预与合并治疗/结局与终点/研究人群/产品画像/执行与统计 → 全部"有采用记录"
01 研究框架：enabled    02 PICOS设计：disabled    03 语料准备：disabled
一键采用推荐方案：disabled   保存草稿：disabled   完成第一步：disabled
```
**主链路结论：场景4 未能走通至导出 Word —— 导出/生成初稿/下载控件在应用内根本不存在（全库 79 个按钮/链接扫描，命中 0），且 01 步骤因"研究流水线失败"永久阻断。**

---

## PASSED（含耗时与点击）

| # | 项目 | 结果 | 耗时 | 点击 |
|---|---|---|---|---|
| P1 | 建项：自选领域 T2DM·II期，纯文字入口 | PASS | 约 8 s | 3（新建项目 / 从零开始 / 创建并进入写作） |
| P2 | 项目持久化、编号生成、重载后仍可选中 | PASS | — | 1 |
| P3 | 模块导航（图标区）可用 | PASS | 每模块约 2 s | 9 |
| P4 | 竞品公开研究检索：1304 项研究 + 141 份 Protocol，来源为真实注册库 | PASS | 首屏加载即"已完成"，约 3–5 min | — |
| P5 | **检索领域适配性抽样核验 6/6 为真实 T2DM 试验**（详见下） | PASS | 约 2 min（外部核验） | — |
| P6 | 反拟合检索：本项目全部渲染内容命中 0 | PASS（阴性） | — | — |
| P7 | 应用内未出现跨领域数值污染（因系统未生成任何医学数值） | PASS（阴性） | — | — |

**检索适配性抽样（我通过 ClinicalTrials.gov API 独立核验，非系统自证）**

| NCT | 官方 briefTitle | 条件 |
|---|---|---|
| NCT02303405 | Hydroxychloroquine Versus Pioglitazone in Combination Treatment for Type 2 Diabetes Mellitus | Type 2 Diabetes |
| NCT07675499 | Exercise and Intranasal Insulin in Type 2 Diabetes | Type 2 Diabetes |
| NCT07296484 | Clofutriben And Placebo **Phase 2** Trial Against INtractable Type 2 Diabetes (CAPTAIN-T2D) | Type 2 Diabetes |
| NCT07065032 | A Study of ZT002 Injection in Adult Chinese Subjects With T2DM | Type 2 Diabetes |
| NCT06937203 | A First-In-Human Study of ARO-ALK7 in Adults With Obesity With and Without T2DM | Obesity / T2DM |
| NCT00924534 | A Safety PK/PD Study of SLV337 in Patients With Type 2 Diabetes | Type 2 Diabetes |

→ 检索词与结果域一致，**未发现检索引擎把其他适应症研究塞进 T2DM 项目**。这是本次唯一实质正向结论。

---

## FAILED

| # | 项目 | 结果 | 耗时 | 点击 |
|---|---|---|---|---|
| F1 | **走完全链到导出 Word** | FAIL —— 导出入口不存在 | — | 0（无可点） |
| F2 | 完成第一步（01 研究框架） | FAIL —— 按钮自始至终 disabled | — | 0（不可点） |
| F3 | AI 研究设计推荐包生成 | FAIL —— 6 模块各 1 张占位卡，44 字段建议值全空 | >25 min 累计等待 | 2（更新建议）+12（tab）+8（展开） |
| F4 | 竞品 AI 分诊 | FAIL —— 6/33 批次停滞 → 研究流水线失败 | 首轮 80 s 停滞，其后 14 min 无进展；重新分诊 13 min 无响应 | 4 |
| F5 | 02 PICOS设计 / 03 语料准备 内容检查 | FAIL —— 两按钮 disabled，无法进入 | — | 0 |
| F6 | 推荐卡片 R1 违例检查 | FAIL —— 无内容可判（详见 R1 段） | — | — |
| F7 | 进入写作工作区（首次） | FAIL 后恢复 —— 运行环境 503 门禁 | 约 2 min + 4 次重试 | 4 |
| F8 | 保存草稿（写作主区） | FAIL —— 至终态仍 disabled（仅"高级微调"面板内成功保存过 1 次） | — | 1 |

**建项到导出总点击**：导出不可达；我实际执行 **约 55 次**鼠标点击（含恢复性重试）。即使系统完全正常，理论上限也需 **≥64 次**（6 tab + 6 候选展开 + 44 字段填写 + 6 采纳 + 完成第一步 + 后续步骤）。**≤20 达标线未达标，超出 3 倍以上。**

---

## 问题清单

### P0-1 竞品研究流水线失败 → 主链路永久阻断，且无重试控件
**现象**：写作页顶部"竞品调研进度 / 研究流水线失败"；抽屉提示"研究流水线失败。可直接重试当前分诊。"，**但抽屉内不存在任何重试按钮**（仅剩 标记为直接竞品/标记为间接参照/排除/锁定竞品篮子，**4 个全部 disabled**）。
**影响**：`完成第一步` 永久 disabled → 02/03 步骤永久 locked → 无正文 → 无导出。这是本次唯一的主链路 kill 点。
**复现**：建 T2DM II期 项目 → 竞品抽屉 → 启动AI分诊 → 等 80 s 见"6/33 批次"→ 再等 → "后台分诊任务未完成" → 重试 → 再次停滞 → 更新建议后抽屉变为"研究流水线失败"，重试控件消失。
**证据**：`/tmp/t17_tester4/20_triage.png`、`20b_triage_stalled.png`、`21_triage_retry.png`；终态文本（版本 14）见 SOURCE_HEAD。
**提示-控件不一致**：文案指示"可直接重试"，界面无对应动作 → 用户死锁。

### P0-2 "AI 推荐研究方案" 100% 空壳
**现象**：6 个模块各只有 **1 张占位候选卡**，文案 `需您选择/补全 <模块>模块待AI基于语料生成 / 模块结构已准备；待语料准入和独立AI完成证据绑定后生成3–5个候选包。/ 无置信`。全部 **44 个字段**（design 13 / intervention 6 / outcomes 10 / population 4 / product 4 / statistics 7）的"建议值"为 `（空）`、`（空列表）`、`待确认`、`未设置`。**"3–5 个候选包" 从未出现。**
**影响**：`一键采用推荐方案` 从不可用；"部分建议已就绪 / 已结合 1304 项公开研究及 141 份Protocol" 与事实不符。
**关键陷阱**：勾选"本次跳过该字段"**不能**推进——13 个字段全跳过 → `组合采用完成：应用0项，修改0项，跳过13项` → 模块仍为"待审阅"、`完成第一步` 仍 disabled。用户被迫**逐字段手写自然语言**才能推进（我照此填满 44 字段、6 次采纳后 6 模块才全部"有采用记录"，而 `完成第一步` 仍因 P0-1 而 disabled）。
**证据**：`/tmp/t17_tester4/16_modules.png`、`18_update_click.png`

### P1-3 枚举字段以自由文本呈现 → 后端 Pydantic 校验失败并原样回显（2 处）
**(a) 产品画像模块**（字段 给药途径/剂型/暴露范围/药物技术类型 全为自由 textarea）
```
组合采用失败：2 validation errors for MedicalWritingStudyFraming
  product_profile.technology_type
    Input should be 'unknown','monoclonal_antibody','other_biologic','small_molecule','rna_therapy','cell_therapy','gene_therapy','vaccine' or 'other'
    [type=literal_error, input_value='小分子', input_type=str]
  product_profile.exposure_scope
    Input should be 'unknown','systemic','local' or 'mixed' [type=literal_error, input_value='全身暴露', input_type=str]
  For further information visit https://errors.pydantic.dev/2.13/v/literal_error
```
**(b) 执行与统计模块**
```
组合采用失败：1 validation error for MedicalWritingPicosDefinition
  design_archetype
    Input should be '','randomized_confirmatory','randomized_exploratory','single_arm_early_phase','open_label_extension' or 'other'
    [type=literal_error, input_value='随机、双盲、安慰剂对照、多中心、平行分组研究', input_type=str]
```
**影响**：界面只给自由文本框、无允许值提示、无前端校验；中文用户按提示填自然语言必然失败。**泄露内部模型名（`MedicalWritingStudyFraming`/`MedicalWritingPicosDefinition`）、内部字段路径（`product_profile.technology_type`）、Pydantic 版本、以及 pydantic.dev 文档 URL。**
**复现**：产品画像 tab → 展开占位卡 → 药物技术类型填"小分子"、暴露范围填"全身暴露" → 采用所选方案。改填 `small_molecule` / `systemic` 即通过（我据此绕过）。

### P1-4 计数自相矛盾（同一页面三套数字）
- 页头：`公开研究处理已完成 · 1304 项研究`
- 抽屉状态计数：`0项`（全部状态/待AI分类/直接竞品/间接参照/已排除 全为 0）
- 分诊进度：`已完成 5-6/33 个分诊批次；已返回 1168/1304 项建议`（状态计数同时仍为 0）
- "文档与解析"tab 内实际渲染 **1304 个 NCT ID**
**影响**：医学经理无法判断竞品篮子到底有多少可用证据；"0项"与"1168/1304"并存。
**证据**：`/tmp/t17_tester4/20_triage.png`

### P1-5 分诊进度条死锁在 6/33，随后进程级失败
首轮"启动AI分诊"约 80 s 到 6/33 → 文案变为"后台分诊任务未完成。可直接重试当前分诊"；随后 **14 分钟**（28×30 s 轮询）无任何进度变化；"按当前信息重新分诊"点击后 **13 分钟**无任何进度上报（未启动）。

### P2-6 工程语言 / 内部标识泄露到用户界面（多处）
| 位置 | 泄露内容 |
|---|---|
| 占位候选卡 | `design模块待AI基于语料生成`、`statistics模块待AI基于语料生成`（内部模块代号 design/intervention/outcomes/population/product/statistics 直接暴露） |
| 建议值 | `kind：待确认；标签：未设置`、`类型：待确认；intervention：待确认`、`模式：待确认`（内部字段名 kind/intervention/mode） |
| 采纳记录 | 把原始 JSON 直接铺在页面上：`已采用 {"design.adaptive_design": "否，采用固定设计", "design.arms_or_cohorts": ...}` |
| 候选标识 | `研究设计（正交维度） · mwprefillcand_7757164636440562 · 修订 7→8` |
| 结构与译文确认 tab | 中文界面内原样回显英文后端异常：`候选范围预览失败：batch translation requires either finalized corpus triage or a confirmed discovery basket projection for the locked snapshot` |
| 组合采用反馈 | Pydantic 全栈错误文本（见 P1-3） |

### P2-7 身份未接入导致首页/来源台账 503
`monitoring_principal_unavailable`（项目总览）、"服务器验证身份尚未接入"（来源台账）。另：**刷新页面后项目选择重置为列表第一项**（磷酸芦可替尼乳膏·特应性皮炎），用户须每次重选，易误操作到他人项目。

### P2-8 侧栏折叠后按钮被 main 覆盖，文本定位点击失效
nav 按钮宽 160px，但 `<main class="page writing-runtime-gate-page">` 从 x=64 起覆盖：`elementFromPoint(90,149)` 命中 `MAIN`。只有 x<64 的图标区可点。`text=证据调研与方案设计` 定位点击报错 `main intercepts pointer events`。

### P2-9 截图/CDP 捕获能力失效 + 视口塌缩（影响取证）
长时间操作后 `Page.captureScreenshot` **持续超时**（`CdpRequestTimeoutError`），即使 DOM 仅 258 节点、已用 `Emulation.setDeviceMetricsOverride` 强制 1600×1000，甚至改用裸 CDP 与新建 tab 仍失败；期间 p1 视口一度塌缩为 **240×117**。→ 最终阻断态无法提供截图，仅有文本证据。

### P2-10 写作工作区首次进入需门禁重试
首屏报 `当前版本组合不可进入写作工作区 · 运行环境检查未通过（HTTP 503）`；前后端指纹与合同号完全一致（`web-0eaf4868fff491f0` / `api-d7875fbd70aa93f6` / `medical-writing-api-2026-07-17.1`）却仍拒绝。约 2 分钟（后端就绪）后自动恢复。门禁期间 main 覆盖侧栏（见 P2-8）。

---

## 反拟合检索结果表

检索范围：`document.body.innerText` 克隆后**剔除 `<select>/<option>`**（排除项目选择器里他人项目的字样），覆盖写作页 + 竞品抽屉全部 4 个 tab。终态（版本 14）实测：

| 词 | 出现次数 | 上下文 |
|---|---|---|
| 斑秃 | 0 | — |
| 偏头痛 | 0 | — |
| 鼻窦炎 | 0 | — |
| 鼻息肉 | 0 | — |
| CRSwNP | 0 | — |
| SALT | 0 | — |
| SNOT / SNOT-22 | 0 | — |
| 合成药T / M / X / U | 0 | — |
| 缓解率 | 0 | — |
| 第24周 / 24周 | 0 | — |
| 2℃ | 0 | — |
| 2～8℃ / 2-8 | 0 | — |

**结论（必须正确解读）**：全部 0 命中是**证伪性阴性结果，不是质量通过**——因为系统**根本没有生成任何含数值或术语的医学正文**（44 字段建议值全空）。正文层面的反拟合 P1 检索 **NOT_RUN**；同样地，"排除标准/终点/样本量假设/保存条件/失访率是否出现无关数值"**无从检验**，因为系统未给出任何数值。若以"未生成"视作"无错配"，会掩盖 P0-2 的空壳事实。

**唯一非零值说明**：项目选择器下拉框内确实含他人项目的 `合成药T·斑秃`、`合成药M·慢性偏头痛`、`MG-K10·CRSwNP` 等字样（未剔除选择器时扫描命中：斑秃4、偏头痛2、鼻窦炎1、鼻息肉1、CRSwNP1、合成药T4、合成药M2、合成药U2）。经定位确认**全部来自选择器选项，未进入我的项目内容区**，不构成本项目串味缺陷；但暴露了另一个风险：多测试者共用同一实例时，选择器不按用户隔离。另在 `/tmp/t17_tester4/` 发现非我写入的 `projects.json`（含 4 条 `合成药T·斑秃` 项目），确认存在并行测试者。

---

## R1 违例检查（"按常规/通行"包装特定产品条件）

**结果：NOT_RUN —— 无内容可判。** 6 张推荐卡片的全部理由文本仅两条通用句：
- `为何推荐`：`模块结构已准备；待语料准入和独立AI完成证据绑定后生成3–5个候选包。`
- `临床差异 / 权衡`：design 模块 `默认关闭复杂设计模块，需要时再改选。`；product 模块 `错误modality会误导安全性与PK模块。`

无任何以"按常规/通行/惯例"包装特定产品条件的表述，也**无任何条件语句**。R1 在本场景下既未被违反、也无法评估——因为推荐引擎没有产出内容。

---

## 领域适配质量评估（自选领域：T2DM II期）

**可取**：检索侧适配良好。1304 项研究抽样 6/6 为真实 T2DM 试验，含一项 Phase 2 T2DM 试验（NCT07296484 CAPTAIN-T2D），说明适应症→检索词→注册库映射可用。模块骨架（研究设计正交维度 / PICOS / 干预 / 终点 / 人群 / 产品画像 / 执行统计）对 II 期方案而言结构合理。

**不可取**：**零领域专业化**。没有给出任何 T2DM 术语（HbA1c、FPG、SMBG/CGM、TIR、HOMA-IR/β、二甲双胍背景治疗）、任何人群参数、任何终点建议。44 个字段 100% 为 `待确认`/`未设置`/`（空）`。系统对"2型糖尿病"这一输入的回应，与对一个空白项目的回应在内容上无差别——适配质量无从体现，本质是"未产出"。

**无法评估项**：术语取舍是否专业、人群定义是否合理、终点建议是否贴合 T2DM II 期 —— 全部因无输出而 NOT_RUN。

---

## KNOWN_LIMITATIONS

1. **最终阻断态无截图**：`Page.captureScreenshot` 在本会话后期全局超时（P2-9），阻断态（研究流水线失败、Pydantic 报错、完成第一步 disabled）仅有文本证据。已保存截图截止 `21_triage_retry.png`（21:12），未覆盖 21:12 之后的采纳与失败过程。
2. **未上传 DOCX/IB 走文件入口**：本次走纯文字入口。文件解析、IB 事实拆解、文档与解析链路未测。
3. **未到达 Word 导出，故导出文件内容、Word 结构、方案正文医学质量全部未验证**（P0-1 阻断）。
4. **未验证 02 PICOS设计 / 03 语料准备 步骤内容**（按钮 disabled，无 URL 路由可绕过，`location.hash` 为空、SPA 无路由）。
5. **未做同项目第二次独立复现**：P0-1 是否由"更新建议"使分诊结果失效引发（抽屉曾提示"项目框架或检索结果已更新，请重新分诊"），我无法在不新建第二个项目的前提下确证；新建第二项目会再耗 20+ 分钟且可能同样失败。
6. **枚举允许值清单来自报错回显与选择器**，未通过前端文档或帮助入口交叉确认。
7. **未连接后端/数据库/文件系统**（遵守禁令），所有结论来自页面渲染与真实点击；检索适配性抽样通过 ClinicalTrials.gov 公开 API 独立核验。
8. 浏览器任务空间（space 127，p1/p2）**未调用 `finish()`**：任务以 P0 阻断结束，保留现场供聚合方复查。

---

## 一句话结论

**检索层是好的（1304 项真实 T2DM 研究，抽样 6/6 对口），生成层是空的（44 字段零建议、6 张占位卡），流水线是断的（研究流水线失败且无重试控件），导出是没有的（应用内无任何导出控件）**。反拟合检索 0 命中是"没产出"而非"通过"——本场景暴露的是 P0 级不可用，而非串味风险。
