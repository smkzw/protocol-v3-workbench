# 医学写作子系统 Protocol v3：ZCode 接管恢复记录

- 时间：2026-09-11 21:14 Asia/Shanghai（off-peak：周五晚）
- 授权：用户在 ZCode 会话中明确要求完整接管 codex 线程 019fb62b-2a50-7ed0-8fb6-e66bbeb8e641 的医学写作子系统构建，进行完整工程 review、必要测试，并按全局 AGENTS.md 执行/会商机制进入连续实施。此为 2026-09-08 无损暂停后的显式恢复。
- 交接依据：handoff/2026-09-11/HANDOFF_PROTOCOL_V3_20260911.md（逐字读毕）。
- 本文件性质：恢复血统记录（recovery contract），不是任何阶段验收。

## 1. 对账结果（派发前完成）

| 项 | 结果 |
|---|---|
| Git | HEAD 3d6772f1014f2a86f96eb3dae4fd878c70a5251c 不变；脏条目 349 与交接一致 |
| 权威 7 文件哈希（handoff 14.1） | 全部一致 |
| 代码/fixture 6 文件哈希（handoff 14.4） | 全部一致 |
| 暂停快照 vs 现 batch1.json | 52 个 fixture ID 完全一致 |
| Trellis 3R.3 | in_progress + user_paused=true → 本次恢复清除暂停等待 |
| 聚焦测试基线 | 30 passed in 2.34s（新XML：resume_baseline_zcode_20260911_2115.xml） |

## 2. 恢复血统（原 logical key 处置）

### 2.1 mw_protocol_v3_3r3_batch1_repair_20260908（首批修复）

- 原session sess_b91d51c2-ce9c-48fe-9add-59201fcf8927，中断turn 6c01694b，exit130。
- 9月11日核对：model-io 日志在原路径缺失（交接§10.2），本 ZCode harness 无法原生续接 codex 侧session。
- 已有产物：6 个合同 + batch1.json + test_chapter_batch1.py 于 09:25–09:31 落盘；聚焦测试现已 30/30 通过。
- 处置：不伪称同会话无损恢复。剩余缺口=独立验收+文档收尾，属主owner+fresh reviewer职责，不再依赖原session。
- 新运行身份：fresh review = codebuddy/deepseek-v4-flash:max（非GLM家族验证者）。

### 2.2 mw_protocol_v3_3r3_batch2_20260908（第二批）

- 原session sess_4df83643-16c7-405c-af7a-1ab779584ad3，中断turn a4bc05a9，exit130。
- 交付对账：无任何 batch2 合同/skill/fixture/test 文件存在（worker 读过材料但未写交付物）。
- 处置：无重叠交付物，新派发即原范围续作，不违反"不重派重叠任务"纪律。
- 新运行身份：execution = codebuddy/deepseek-v4.1-flash:max（off-peak finite_code_task 链；首选项 pi/mlx-serve 因 64k 输入上下文门限与本次大材料阅读任务不兼容而跳过，AC/端口门已核）。

### 2.3 不变约束

- 1R.6 产品连通性探针已 SUCCEEDED，不重复。
- 不碰 live workbench、8910、医学监查、plan-upgrade-20260905、外部 SOP。
- 不清理历史 rows/runs/records/logs/evidence。

## 3. 本次派发

| worker | 路线 | packet | 状态目录 |
|---|---|---|---|
| batch1 fresh review | codebuddy/deepseek-v4-flash:max | context/mw_protocol_v3_3r3_batch1_fresh_review_20260911_context.md | runs/mw_protocol_v3_3r3_batch1_fresh_20260911/ |
| batch2 execution | codebuddy/deepseek-v4.1-flash:max | context/mw_protocol_v3_3r3_batch2_resume_20260911_context.md | runs/mw_protocol_v3_3r3_batch2_resume_20260911/ |

适配器最小连通性检查（2026-09-11 21:19）：deepseek-v4.1-flash 与 deepseek-v4-flash 均回显 PROBE_OK + 模型id；effort 自报 default，按 1R.6 先例不视为服务端已证明的推理强度，仅作传输连通证据。

## 4. 接管后工程判断摘要

1. 交接所述"首批修复未验收"实际状态更好：测试已全绿，修复语义抽查到位；缺的是独立复核与收尾文档。
2. fixture ID 在修复中被系统性改名（`v2_front_block`→`v2-front-block`），语义槽位 48/48 保留 + 4 条新增定向 fixture；字面改名是否可接受交 fresh reviewer 裁决（若裁决要求恢复原ID，属机械回滚，不影响合同语义）。
3. 主要工程风险仍在 6.2 清单（新前端未成形、StrictMode、过期Word预览、失联locator等），均在 6R/7R 阶段处理，不在本轮 3R.3 展开。
