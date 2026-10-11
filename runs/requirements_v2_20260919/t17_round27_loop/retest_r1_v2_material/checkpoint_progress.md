# retest_r1_v2 过程检查点（2026-10-11，复测协调员）

## 已完成证据
- ① 重启：5301 pid 24818（09:28:10 起 > 最后源码修改 09:16，含全部修订批）；vite pid 24907 显式 VITE_API_PROXY_TARGET=http://127.0.0.1:5301（进程 env 实测）。指纹三方一致 api-f2b9c4d4635834d3（后端自报 = vite 现算 = 经代理）。
- 单元证据：pytest 19（adopt_reanchor 3 + external_literature 14 + chunk_fault_injection 2）+ fidelity_ritual 3 + vitest residualAdmission 2（--environment jsdom，首跑失败系本协调员漏加 env，非产品问题）全绿。
- OCR 探针：HTTP 200 / passed=true / GLM-OCR-bf16 / 17.0s（ocr_probe_r1v2.json）。
- 新建项目（只新建）：MW-II-847F2D95 / proj_user_f4646e04bf3f（KZ-HS501 口服TYK2变构抑制剂缓释片 · 化脓性汗腺炎（Hidradenitis Suppurativa，中重度）· II期）——159 项目无 HS、无 TYK2 口服用例；慢性咳嗽+P2X3 已被 5 个历史项目占用故弃用。回归点1 建项 ✅。
- PubMed 连通性：esearch 混合中英文适应症词 Count=15（CJK 词元被忽略）→ live hit 路径可行。
- 第一步：产品事实（小分子/全身/口服固体/口服 checkbox）+TYK2 机制事实拆解（第3次重试成功；前2次失败=MTPLX prefill_system_abort/death_signature 内存中止甩尾 NetworkError/RemoteDisconnected——MTPLX 日志实测，环境行为）→ 完成第一步 v3→确认变更重新核验→v4。
- 第二步：采用方案文字建议（随机/双盲/安慰剂/平行/多中心）+ 设计类型=随机探索性研究 + 六模块亲填（人群概述/IN×3/EX×2/干预概述/用法用量/对照设计/主要终点HiSCR75/关键次要/其他次要/安全性终点/AESI/研究时期/访视/估计目标/样本量208例/统计策略fixed-sequence）+ 样本量锚点（KZ-HS501-201 Ib期 IB v1.2 §7.3——P1-48 上纸验证点）。守卫往返：v4→保存→返回第一步→完成→v7→确认变更核验→v8→完成第二步 ✅ 一次过（r3-N2 往返仍在，已挂账族）。
- 语料门：竞品分诊确定性失败 no_public_protocol（HS 检索无公开 Protocol 文档，pipeline status 实录：stage=failed 32%，child 16/19 84%，error_summary=ResearchPipelineError: 竞品分诊仅部分完成：deterministic corpus disposition: no_public_protocol，snapshot wref_search_3c215d0407fa043dd34e，triage_run ct_run_b46ec9aeceef59e4d3f3）。期间真实死路现场（已恢复）：继续未完成分诊/按当前信息重新分诊 →"project material facts have changed since the run was created"（旧run拒绝续跑）+ 重新检索竞品 → 409 Conflict 多次 + 无取消入口；数分钟后重试实际重启了新一轮分诊（3/19 批后同样 no_public_protocol 收敛）。例外放行：5 缺口全勾 → 确认例外并放行 → 项目状态=例外允许写作。
- 写作平台：进入无 500（r3-E 建稿死锁未复现）；创建工作副本出现「检测到未完成的初始保存：内容已就绪，点击『保存版本』完成初始化」→ 保存工作副本 → 版本 1 保存成功，遮罩解除——**r1-N2 工作副本保存死路（P0）修复 live 验证通过**（提示文案『保存版本』与实际按钮『保存工作副本』措辞不一致，小瑕疵）。
- 生成全文初稿：已启动（第 1/21 批 · 0%），21 批预计 ~2h。

## 待完成
- 生成完成后：P0-2 背景外查取证（背景章 source_gap 降级/留痕/归档外部文献档案区）→ N1″ 批量采纳重锚验证 → 导出回归（预览 Word + 样本量锚点/剂量出处检查）→ P2-8 忠实度面板（本链 no_public_protocol 无译文，如实报告不可达）→ 并发仲裁 300s 双负载 drill → 收尾清点。
