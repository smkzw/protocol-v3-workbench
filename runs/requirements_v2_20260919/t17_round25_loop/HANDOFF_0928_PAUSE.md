# HANDOFF — 0928 无损暂停（用户指示）

## 强制接续指令（每个后续 Agent 开工前必须先读完本节）

你接手的是 smkzw/protocol-v3-workbench 医学写作子系统的无损暂停点。用户已确立的推进方针：**多测试者真实用户视角端到端测试是产品验收主驱动，质量循环（审阅→反馈→复盘→深度分析→修订→再审阅）不设轮次上限**；基础结构只在测试证明挡路时才修；汇报一律非工程化语言四段式。工作目录=本仓库根。

## 一、运行身份与现场快照（2026-09-28）

- HEAD=`d9d70a3`（与远程一致，0/0）。后端 5301（构建 api-be195048893005bd）、前端 5186（**已重接 5301**，绑定 127.0.0.1；构建 api-34b93403aa68bba4）、oMLX@8001（编排器管理）、MTPLX@8002（编排器**实战验证拉起成功**：venv CLI + 显式模型路径 + --port 8002，pidfile=launched_pid=36620）。
- 目标批（da229e6a，230 项）：ready 60 / blocked 165 / failed 3 / excluded 2。
- K3 批（79e7f4e5，830 项）：ready 14 / blocked 38 / failed 522 / excluded 256。第 1 波（3 研究 52 项）放量完成：ready+14、blocked+37、failed+1。
- 医学门队列：**203 项 fidelity_blocked**（165 存量 + 38 第一波新增）已在 `runs/requirements_v2_20260919/t17_round23_blocked_lineage_0927/medical_queue_live_all.json` + `medical_gate_queue.md`，等用户医学处置。

## 二、已交付（全部已 push，本暂停无未推提交）

1. **长文截断修复**：无换行超长段落（4865 字符）不切分 → 模型输出顶到上限碎裂为 146 字；已补句边界安全切分（chapter_translation_pipeline.py `_split_oversized_text`）+ 5 反例（tests/test_chapter_translation_oversize_paragraph_split.py）。
2. **blocked 谱系持久化+离线重建**：被拦翻译同步落对齐底稿（写侧已闭）；存量从 blocked_raw_provider_output 确定性重建（scripts/qc/rebuild_blocked_chunk_lineage.py：rebuild/reeval-evidence/medical-queue 三子命令）；6 用例（tests/test_writing_reference_blocked_chunk_lineage.py）。
3. **样本重判实判=confirmed**：底稿重建后复检真正到达检查器，重判=初判（两码成立）——审阅要求的"正确性证明"达成（sample_reverdict.md）。
4. **有界放量通道**：重试命令支持 nct_ids 范围限定（同键不同范围=不同命令；worker 认领层严格遵守范围）。第 1 波实战 52 项。
5. **环境事故处置**：vite 5186 代理曾错指 live 8910（五人舰队 UI 写入落到 8910 库：T1/T3/T5 系列项目含 MW-II-AF970437）——已重接 5301 并实测验证；8910 侧测试残留**未动**，留待用户授权处置；**vite 默认代理指向 8910 属高危脚枪，已立案待修（本轮未修完，见 §四）**。
6. **模型调度全自动化实战验证**：MTPLX 由编排器 venv CLI 拉起成功（含 8-token 真实验证生成）；oMLX 按需加载/空闲释放正常。

## 三、进行中（两条工作流的状态）

1. **并发仲裁+五人真实用户循环（dwfrun-07b55989）——运行中，未停**：
   - 已完成：并发仲裁机制（排队+最小驻留窗+防双载+审计）已实现**但在途未提交**（30 文件 2313 行，含 ai_gateway 接线、front 缺陷修复 UI 脚枪、T5 报的 vite 默认代理修复尝试）；真实双负载压测已过（无双载）；五名测试者（T1 gpt-6-sol/T2 grok-4.6/T3 gemini-3.8-flash/T4/T5 内部）已派发并行测试中。
   - **在途 WIP 归属该工作流缓存**——接手者若重启该工作流，实现师会从缓存续；若手工接管，先 `git diff` 全量核对这 30 文件再决定提交或回退。
2. **质量循环的设计要点（已写入脚本 .zcode/workflow-drafts/0927V1快车道与切片冲刺.dwf.ts）**：测试→反馈（聚合去重）→复盘（与上轮对照：新/修好/持续/回归四分类）→深度分析（无进展必须换策略；连续两轮无进展升级主会话）→修订（反例红绿）→再测试。收敛=五场景全部导出 Word + 无开放 P0/P1 + 并发压测干净。**禁止"修完默认通过"。**
3. 五人任务书要点已定：T1 糖尿病肾病III期口服SGLT2/A入口/医学总监盯内容；T2 肺癌III期PD-1联合化疗/B入口/临床运营盯流程；T3 房颤III期口服FXIa/A入口/统计师盯终点；T4 黄斑变性II期双特异抗体/B入口/医学写作盯结构；T5 失眠II期DORA/A入口/药物警戒盯安全性。**用户视角铁律**：一切操作测试者本人浏览器完成，界面做不到=P0 界面能力缺失；秘书不代操作。

## 四、已立案待修（下一批队首）

1. **vite 默认代理指向 8910**（高危脚枪）：不带 VITE_API_PROXY_TARGET 时应默认本子系统端口或拒绝启动——本轮修了一半（运行时已重接，默认值修复在途 WIP 中）。
2. **fidelity_blocked 无再生成通道**：重试只认 failed_retryable；被拦项重译需产品机制（医学工作流的一部分）。
3. **波次 2-4 映射覆盖缺口**：22 研究 0 条目——研究→条目映射未覆盖，需查 g6_k3_574_mapping.json。
4. **版本门并行开发宽容**：并行部署期间版本门硬拦且只有"重新检查"无原因说明（T5 实报 P2）。
5. **33 项存量测试债务**（known_failures_0926v1.json）+ 全库门"带已知账目通过"口径展示。
6. **8910 测试残留项目清理**（T1/T3/T5 系列）——需用户授权。

## 五、质量基线快照

- 全库门最近一次：11268 测试 / 33 失败（全部登记在册的存量，零新回归）/ 静态与必测口径清零。
- FAST 关键文件：tests/test_model_lifecycle_orchestrator.py、test_writing_reference_translation_batch_g5_scope.py、test_translation_retry_scope.py、test_chapter_translation_oversize_paragraph_split.py、test_writing_reference_blocked_chunk_lineage.py。
- **编排层四教训（接手必读）**：①脚本调 pytest 必须绝对路径（cwd=工作台根）；②工具接口变更必须同批更新编排脚本；③门时限按实测设（全量 1-3 小时→3h 上限）；④world.run cwd=工作区根，测试路径写绝对。

## 六、NEXT_GATE（恢复后顺序）

1. 处置运行中的 07b55989（五人测试结果聚合→循环后续轮次）与在途 WIP（提交或续跑）。
2. 修 §四.1 vite 默认代理（脚枪）+ §四.3 波次映射缺口。
3. fidelity_blocked 再生成机制设计（§四.2）——医学工作流的一部分。
4. 用户医学处置 203 项清单后：按 G6 入选范围继续有界放量（nct_ids 通道就绪）。
5. 五人舰队循环收敛后：R16 总验收（含 T18 操作负担、双入口正向、界面三视口）。

## 七、红线（不变）

不碰 live 8910/医学监查/共享 runtime（vite 代理事故教训在案）；模型服务器只经编排器管理；不清库不删历史；忠度晋级与 574 全量重放维持暂停（等医学处置）；测试者 UI 黑盒+用户视角铁律；共享文件单一集成人；反例先证失败再修；汇报非工程化语言四段式。
