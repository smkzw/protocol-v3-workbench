# retest-r4 · R27 LOOP 第5轮修复批复测报告（2026-09-30 下午，复测协调员）

- 被测对象：本仓库工作区（HEAD=64841c2「orchestrator probes authenticate to MTPLX」+612ee3b + 未提交修订批47文件/12399行；修订批最后源码修改14:40）
- 前端：http://127.0.0.1:5186（pid 4160，14:43:35启动）；后端：127.0.0.1:5301（14:43:17由实现方启动→15:24由本协调员带key重启，见①）
- 测试者：复测协调员本人，浏览器黑盒操作（文本选择/输入/按钮全部本人完成；共享Camoufox多次回收标签页照旧以服务端状态续跑）
- 本轮新建项目：R4RT-CD-501（克罗恩病（回结肠型）·II期·从零开始，MW-II-AD…）——回归点1建项✅
- 账本来源：r3轮两P0（repository类边界截断、MTPLX死亡+属主失效）+ r3-revroute修订路由P0（修一半）+ r2/r3遗留（入口B、导出、幂等死路）

---

## 一、重启与指纹（①）

本轮有代码修订（新提交64841c2=编排器探针带鉴权修MTPLX误判离线——**上一轮P0-2的根因修复**：裸`/health`被服务器401拒绝→被误读为离线→2小时+重启循环而模型一直健在；另有612ee3b测试产物清理）。实现方14:43:17/14:43:35重启5301与vite，晚于全部源码修改（最后14:40:57）→ 无需再启。指纹三方一致：直连=经5186代理=dist期望，均为 `api-6e3c03577653f0b7`，`ready=true` ✓。**MTPLX已由编排器重新拉起**（8002新pid 63756）——上一轮「进程消失+无法拉起」的P0-2主因已随64841c2清偿。

## 二、上轮P0清偿核验

### P0-1 repository.py 类边界截断——已修复并验证 ✅

AST复测：`_with_effective_document_binding` 的父链恢复为 `ClassDef:MedicalWritingRuntimeRepository:162`（r3时父节点是模块级函数`_gap_placeholder_block`）。浏览器实测：OAB项目（MW-II-C6833D74）文档工作台**不再500**，「真实方案文档会话读取失败」消失，编辑会话就绪——**关闭**。

### P0-2 MTPLX不可用——主因已修（64841c2），属主记录残留一项未清 ⚠️

- MTPLX进程回归（8002 pid 63756）且 lifecycle `healthy=true, resident=true`；探针401误判的根因（裸/health被拒）已修。
- **残留**：lifecycle的 `identity` 仍为 `owned=False, pid=18233, process_not_running`（死pid），**跨后端重启持久存在**；后果实测：翻译相探针报 `refusing to stop a server we do not own: {…pid 18233…} (switch retried 2x, budget capped)`——仲裁器**无法切相**（omlx相派发被拒），仅当前相（mtplx）直发可能。属主记录的清偿（重新绑定/状态文件重置）属编排器属主职权，本协调员未触碰。

## 三、fixed_pending_verify逐项（②）

### 修订路由P0（r3-revroute「修了一半」）——已修复并验证到网关 ✅（附新P1）

- 代码核对：`ai_execution_policy.py:217` NEW-40将 `_OLLAMA_CLOUD_DEEPSEEK_V41_FLASH_POLICY`（provider=ollama-cloud, base_url=https://ollama.com, model=deepseek-v4.1-flash）补入 `MEDICAL_WRITING_REVISION` 执行层白名单。
- **浏览器端到端实测**（OAB项目4.1总体设计节，本协调员亲手选中文本「本研究采用多中心、随机、双盲、安慰剂平行」20字→修订意图=改写→提交AI修订，14:57:27）：
  - UI推进到「正在校验AI候选（60%）步骤4/5」——**r3的三连拒（AiExecutionPolicyDenied×3/50秒）未复现，执行层策略放行**；
  - durable job只读核对（`medical_writing_durable_jobs.sqlite3`，`mwjob_3191204088a210663e2774d9`，created_by=medical_manager）：`provider='ollama-cloud'`、`model='deepseek-v4.1-flash'`、phase=validating_candidates、attempt 3/3、耗时54秒——**路由身份=owner决策20260928指定的ollama云，请求真实到达云网关**（对比r2走opencode、r3被白名单拒）。
  - 失败点：`AI provider request failed: HTTP 404`——**ollama.com云端点对model id返回404**。这不再是路由缺陷，是**云端profile配置/凭据问题（新P1，集成人职权）**：ollama.com的key与model id需核定；且失败文案已中文化（NEW-12生效，无内部枚举外泄）。
- **判定：r3-revroute P0（修订路由）关闭**；新立P1：ollama云profile 404（配置）。

### 入口B解析（R2-D/R3-D P0口径）——仍未完成；根因转移到云端401 ⚠️不计关闭

- 本轮SAP v2摘要解析（15:0x/15:3x两次续跑）在实现方14:43后端与我的带key后端下均快速失败。只读核对 `medical_writing_synopsis_import.sqlite3`：`error_message='chunk 0 validation failed: AI provider request failed: HTTP 401'`（attempt 3，15:32:55）——**结构化路由按owner决策走ollama云，云端鉴权401**（另一名R4-A测试者14:30同报401，先于我的重启→非本协调员环境问题）；且owner路由覆写在凭据坏时**不回退本地链**（设计缺口，记P2观察：NEW-22的回退条件只覆盖「缺失/禁用/非云」，不含「云端鉴权失败」）。
- 30分钟口径连续第四轮无果；**不判通过**。清偿=集成人核定ollama云key/model id（与§三修订404同源，一处修复两处受益）。

### 导出（③之2回归点）——被新P1阻断 ❌

- OAB初稿隔夜完成：82章候选生成，「全文初稿已写入56个章节」（本协调员点「确认关键章节并采用全文」采纳）——**初稿链路在模型可用时段端到端走通**。
- 「预览 Word」点击实测：**「失败：DOCX 导出失败（阶段：组装章节）: NameError: name '_context' is not defined」**——导出组装阶段又一个未定义名（与r3的AttributeError同族=连续快改留下的破损；UI报错即充分证据）。**新立P1（导出组装NameError）**，正式Word另被「106章节未形成作者冻结版本」门挡（需逐章冻结，流程性门槛）。
- **导出回归未达成**；内容族①②③的导出件检验随之被阻。

### 幂等死路 / 版本门

- 幂等死路：解析未完成即无取消-完成场景；未验证。
- 版本门漂移：构建一致；无法诚实复现。均维持不判。

## 四、回归抽查（③）

1. **建项**：R4RT-CD-501（克罗恩病）三字段建成（首次提交被「请填写研究分期」中文点名拦下——分期下拉时序未注册，补选后建成；点名机制工作正常）→ **重过 ✅**
2. **导出**：见§三——**未达成**（被导出NameError阻断）。

## 五、并发仲裁压测（④）

- `retest_r26_drill.py`（300s窗口），15:09:17–15:18实跑，跑在实现方14:43后端（**该后端环境缺模型网关key**）上：翻译相0/1（401，415s）、分诊相0/129275（**401速拒风暴：0.1s/次×约13万次**——drill失败无退避循环在速拒场景的行为问题，记P2压测仪器观察）；**双载=0（61样本）**。
- 本协调员随即以带key环境重启5301（15:24）并单发探针复测：翻译相改为报属主拒绝（见§二P0-2残留）——即：**key就位后401消失，但切相仍被死pid属主记录卡住**。两段合读：模型层要在「属主记录清偿+key环境交接」后才具备压测条件；本轮「无双载」结论在故障态下成立（61样本无一同时驻留），不构成健康态证明。

## 六、新立/维持缺陷清单

| 级别 | 项 | 状态 |
|---|---|---|
| P1(新) | DOCX导出组装阶段 NameError `_context`（预览Word实测失败） | 待修 |
| P1(新) | ollama云profile：修订404/结构化401（key与model id核定） | 集成人职权 |
| P1(维持) | 连点重复建项（r3-D证红；本轮项目列表MSC-201约30个重复仍在库） | 未修 |
| P0(残留) | 仲裁器属主记录 owned=False死pid18233 跨重启持久→无法切相 | 编排器属主职权 |
| P2(新) | owner路由覆写在云端凭据失败时不回退本地链（NEW-22回退条件不含鉴权失败） | 待评估 |
| P2(新) | drill失败无退避循环（速拒时430rps自压） | 压测仪器 |

## 七、最终判定

- **关闭2项**：r3-P0-1 repository类边界截断（AST+浏览器双验证）；r3-revroute修订路由P0（durable job实证路由=ollama云+过执行层策略，链路修通至云网关）。
- **未通过/未闭合**：入口B解析（云端401，集成人职权）、导出回归（NameError新P1）、内容族①②③导出件检验（随导出阻断）、幂等死路、版本门、属主记录残留（P0残留）。
- **allPass = false**：修复批确实清偿了r3两P0（仓库破损+MTPLX拉起），初稿链在模型可用时段端到端走通（82章→采纳56章）；但「ollama云profile配置」与「导出NameError」两个新阻断使入口B与导出仍无法收口，属主记录残留使仲裁切相仍瘫。

## 八、收尾确认

- Camoufox标签页已全部关闭（`camofox_list_tabs`核为空）；5399临时文件服务器已停；`serve3.log`已删。
- 保留：本报告、drill原始数据（`concurrency_drill_summary.json`/`events.jsonl`）、测试材料docx。
- 现运行5301为本协调员15:24带key重启（pid 14256，指纹api-6e3c03577653f0b7）——key环境较实现方14:43版本多出模型网关key，属①职责内的正确配置，属主重启时自然接管。
- 未触碰：live 8910（观察到其新进程在跑，未互动）、医学监查、共享runtime、任何模型进程、他人项目（MSC-201重复群仅记录）、路由/密钥文件内容。
- cleaned = true
