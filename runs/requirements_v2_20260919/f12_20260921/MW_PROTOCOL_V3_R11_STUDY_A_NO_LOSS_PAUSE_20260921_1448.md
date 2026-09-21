# Protocol v3 Round 11 / Study A 无损暂停记录

记录时间：2026-09-21 14:48 +0800  
任务会话：`019fb62b-2a50-7ed0-8fb6-e66bbeb8e641`  
本次暂停性质：用户明确要求在完成当前手头工作后暂停。产品总目标没有完成，本记录不得被解释为发布验收。

## 1. 当前权威与恢复入口

1. 本轮入口：`plans/protocol_v3_fork_execution_20260921/00_START_HERE.md`
   - SHA-256：`4020fa3f348c62b767c8424749b0566fe65b5a24dba2b742ef6b8af2affd2d9c`
2. Goal prompt：`plans/mw_protocol_v3_goal_prompt_20260921.txt`
   - SHA-256：`3a3f03effcdd0373ecc4133d3b04da5052cd62bb78b6df674cae345ffe01bace`
3. 动态状态：`.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md`
4. 当前源代码与文件系统高于旧交接摘要；不要回到 3R.4、r42 或 2026-09-19 Round 10 起点。
5. 用户的最新施工纪律仍有效：以完整功能批次构建，避免过度设计；构建期间不“改一处测一次”，完整产品构建后再集中验收。

## 2. 本次实际完成

### Study A 研究定义

隔离项目：`proj_user_8a5a00cb014a`  
项目名称：合成试验药A / 成人中重度斑块状银屑病 / III期 / `MW-III-AEA61047-DRAFT`

后端 authoring journey 已从 revision 16 推进至 revision 20：

- `framing_complete=true`
- `picos_complete=true`
- `current_stage=corpus`
- 给药途径已持久化为“口服”
- 中心模式已持久化为“多中心”
- 研究设计为随机、双盲、安慰剂对照、平行组、两组 1:1
- 不开展期中分析，不进行样本量再估计
- 主要终点为第16周 PASI 75 应答率
- 合成验收样本量为132例，每组66例
- 人群、入排、干预、对照、PASI量表、访视、estimand、样本量和统计策略均已保存
- PICOS 草稿无缺失项并已正式提交，提交后草稿清空

这些数据只用于产品验收，不得用于真实申报。

### 保存冲突修复

真实故障是：用户编辑期间，后台推荐投影把 journey 从 revision 15 推到 16；原前端只能检查“服务器是否已经保存同一份草稿”，没有在确认是明确的 stale revision 后用最新 revision 保存用户仍在页面上的内容。

已在 `frontend/src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx` 中加入一次性恢复：

- 只处理 HTTP 409 且错误明确包含 `stale authoring journey revision`
- 先读取服务器最新 journey
- 使用同一用户草稿和新 revision 生成新的稳定幂等键
- 只重试一次
- 网络错误、无状态错误和 unknown outcome 不自动重放

该源文件暂停前 SHA-256：`40c712bc9a23f04153f68b0eea65580158c6145275995b4a1ac1c92f8473c585`。

## 3. 本轮没有做

- 没有启动 Study B（类风湿关节炎复杂非劣效研究）或 Study C（MDD盲测）。
- 没有创建完整方案正文、Word导出或新的原生Word往返验收。
- 没有重跑竞品分诊、下载、OCR、13个翻译失败项或5个历史失败项。
- 没有运行新的产品模型调用。
- 没有为这一个前端修复重新跑全量测试；最近一次完整集中回归仍是 checkpoint 记录的前端110+65、GenOffice 1398通过/1跳过、后端2601通过。
- 没有声称独立审阅中的全部 A01-A26、V01-V08 已通过。
- 没有向 GenOffice 上游仓库推送。该目录的 origin 是 `genspark-ai/genoffice`，当前本地改动属于本项目适配，不能冒充已被上游接收。

## 4. 仍未闭合的风险与欠项

1. 新增的 stale revision 单次重试尚未做浏览器故障注入验收。它经过源码核对，但必须在后续集中验收中证明不会覆盖其他窗口的新编辑。
2. Study A 尚未从语料准入继续到完整正文、真实编辑、下载和Word原生保存重开。
3. Study B 与 Study C 尚未开始。完整三研究F12验收未完成。
4. GB/T 7714只覆盖工作稿级常见来源；复杂作者、法规、指南、书籍、网页与访问日期仍需补齐。
5. Office复杂对象级局部AI修订、完整引用元数据、三研究逐章医学一致性及A/V矩阵仍未闭合。
6. 当前工作树包含大量Round 11源码、计划、审阅和验收证据。不要用旧HEAD或清理命令覆盖。
7. GenOffice本地仓库仍有未提交适配改动；主项目通过构建产物承载当前集成结果，但继续开发前必须先核对两个仓库状态。
8. 停止API时收到了此前PICOS提交后的延后投影告警：`corpus projection failed for confirmation ct_conf_64147b6c4d57d64cb9b9: triage must use the immutable snapshot bound to the authoring journey`。PICOS revision 20已成功提交，该告警表示后续语料投影没有闭合，不能把 `current_stage=corpus` 解释为语料已准入。恢复后应先核对authoring journey绑定的immutable snapshot与现有triage run，不要重新分诊。

## 5. 已保留的不可重复运行证据

- Study A 检索：315项
- 竞品分诊：20/20分块，保留59项，排除256项
- 原文准备：61份；失败项原样保留
- 翻译规划 run：`wref_ulrun_c037c4da8e76657c31d974a4`
- 翻译批次：`wref_translation_batch_d4eaf133b83061d1c0d2b2dc`
  - 13项 `failed_retryable`
  - 3项 excluded
  - 已保留原文关键锚点：eligibility 5、objectives/endpoints 5、safety 3
- 第一轮语料分析：`mwca_aaee876eeec80159d18fa6d5`，4/4完成
- 当前流水线停在 `awaiting_corpus_admission`
- 隔离运行目录：`runs/requirements_v2_20260919/f12_20260921/three_studies/isolated_runtime`
- 研究定义暂停快照：`runs/requirements_v2_20260919/f12_20260921/study_a_pause_state_20260921.json`
  - SHA-256：`d491788a00a15bf5603af36906fc0c88e84592f6cb59a8d8d73cbcba475ca174`
- 流水线暂停快照：`runs/requirements_v2_20260919/f12_20260921/study_a_pipeline_pause_state_20260921.json`
  - SHA-256：`7d2106848e4e954c64d9c2960f6d4c3449110eb12167e53def1f2c7ae541b9c8`

上述检索、分诊、下载、OCR、翻译和语料分析结果只恢复读取，不重跑。

## 6. 凭证与Git注意事项

- 主仓库暂停提交由本文件所在提交承载；最终SHA以 `git log -1` 和GitHub远端为准。
- `isolated_runtime/ai_provider_secrets.json` 含运行凭证材料，只保留本机，不得提交Git、复制到暂停记录或打印内容。
- SQLite、WAL、SHM、浏览器运行态和大体积运行副本保留本地，不纳入本次GitHub提交。
- 不清理历史runs、reviews、conference、prompt、raw log和已有DOCX证据。
- 工作树暂停时仍保留三份本地运行配置/任务日志的修改及未跟踪的数据库、原始runner输出；这些是运行态证据，不属于GitHub产品提交，后续不得用`git clean`或强制reset清除。

## 7. 恢复后的第一个安全动作

1. 读取最新全局 `~/.codex/AGENTS.md`、本仓库 `AGENTS.md`、本文件、`00_START_HERE.md` 和 Trellis checkpoint。
2. 核对主仓库与 GenOffice 仓库的当前 Git 状态，确认没有其他Agent继续写入。
3. 启动新的隔离 API/Vite 端口，不触碰8910、5186、5285及医学监查服务。
4. 在 Study A 页面读取 revision 20，确认 `current_stage=corpus`、framing/PICOS均完成。
5. 核对告警中的confirmation `ct_conf_64147b6c4d57d64cb9b9`、authoring journey绑定的immutable snapshot和现有triage run；只修复绑定/投影恢复，不重新分诊、下载或翻译。
6. 用一次明确的并发 revision 场景验收“保存草稿自动恢复一次”；失败时保留两个版本，不重复调用模型。
7. 然后从现有 `awaiting_corpus_admission` 继续 Study A 的“准入→完整初稿→编辑→Word→原生保存重开”，不要回到检索或原文处理。
8. Study A完整路径稳定后，再按验收包执行Study B与盲测StudyC，最后集中执行F12。

## 8. 暂停状态

本任务创建的5296 API和5196 Vite服务均已停止；8910及共享/医学监查服务未触碰。Goal按用户明确要求标为 paused。恢复必须由用户再次明确要求。

暂停前仅执行一次最小静态核对：目标 JSX 由本地 esbuild 成功解析，`git diff --check`通过。没有运行组件、API、浏览器或全量测试。
