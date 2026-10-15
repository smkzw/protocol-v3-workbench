# 自检阻断修复 · 纪元R2第1次自检红节点②（2026-10-15，实现师，本ask内实跑）

## 红节点（承接自检报告）
②竞品分诊 partial_failed，连续第三个牺牲项目、跨两天同型。任务书三层根因：
云端半瘫痪（直接因）+ 路由swap未传导到分诊（配置层工程断点，本轮核心）+
partial_failed无前进路径（产品层，上轮已修）。

## 根因定位（本ask读码+读库实证）
### 路由swap传导断裂的准确机制
- 分诊网关不走 independent_ai 角色绑定，而走**任务级路由表**
  `TASK_TYPE_ROUTE_PROFILE_OVERRIDES`（ai_execution_policy.py:131）：
  `competitive_intelligence/protocol_design_synthesis/picos_design_coach/
  medical_writing_revision` 四任务钉死 profile `independent_ai__ollama_cloud_dsv41`
  （owner 2026-09-28 决策，当时该profile=ollama-cloud/deepseek-v4.1-flash）。
- owner 20261013 把该profile三元组切为 cms-router/glm-5.3-flash（profile_id
  保留）；owner 20261014 又把 **independent_ai 绑定**切到本地MTPLX
  （ai_role_bindings.json revision 126，读库确认）。绑定是角色主路权威，但
  四任务的钉子表不读绑定——分诊/设计综合/PICOS/修订继续被钉到瘫痪云。
- live对照（读库）：绑定主路=mtplx@8002 ✓、active=mtplx ✓、
  fallback_chain=[ollama_cloud_dsv41(cms-router)]——只有钉子表滞后。
- r2-1 现场（任务书证据）：job mwjob_81fdc6f0 冻结 ai_route=
  independent_ai__ollama_cloud_dsv41→cms-router/glm-5.3-flash，chunk 2/3/4
  TimeoutError，单成功chunk 28-30分钟——与机制吻合。
### 上轮部分确认修复的复核（任务书仍报"恒0项"）
- 上轮修复未提交但一直在盘（backend/vite 从盘加载，10-14 22:53 时已生效）。
- 本ask用 **r2-1 真实载荷**（读库 ct_run_5dc767bb：31候选/16分类/15未分诊/
  4保留）新增强化vitest：批量确认区按真实run呈现、确认可点、请求体
  retained=4成功批分类+excluded=27+partial_coverage_acknowledgement=true——
  **修复在真实数据上工作正常**。任务书所述"锁定深度处理篮子恒0项"指人工
  定稿框（其计数按设计在确认前为0）；新的部分确认区是其上方的正确出口。

## 修复（反例先红后绿；修链路功能非绕测试）
- `TASK_TYPE_ROUTE_PROFILE_OVERRIDES` 清空（带owner裁定传导注记）：四任务
  回落 independent_ai 绑定主路（"表项缺失回退绑定主路"是2026-09-28设计的
  既有合法形态）；云路由恢复后如需重新分任务钉云由owner再裁定恢复表项。
- 分诊网关（`_task_routed_independent_profile`→`_independent_ai_profile`）
  与提交层（`_capture_task_cloud_route`）共用该表，一处清空两路同时传导。
- 旧契约测试四件更新为新语义（钉子清空/绑定回退/不再钉云），每处注明
  owner 20261014传导依据；fallback_401指定档案夹具回真值
  deepseek-v4.1-flash（与真实注册表一致）。

## 反例与测试（先红后绿实证）
- pytest反例 `test_task_route_overrides_cleared_after_owner_20261014_swap`
  （修前红：四任务仍在表且解析到云profile；修后绿：NotIn+None）。
- vitest 真实载荷复验 `WritingReferencePanel.partialConfirm.test.jsx` 第2件
  （r2-1 run/snapshot 读库生成夹具 __r21Fixture.mjs，仅结构字段无原文）。

## FAST定向自查（本ask内实跑）
1. 套件：ai_execution_policy+fallback_401+ai_fallback_chain+triage三件+
   D017+contracts = **513 passed + 39 subtests**；vitest全库存
   **41文件/228测试**全绿（含r2-1真实载荷件）。
2. 后端带修复重启，经5186代理 ready=true（api-16f3f5fe6ad91abb）。
3. **真实库解析验证**（isolated_runtime env，python实跑）：四任务
   `task_routed_cloud_profile → None`；绑定主路 =
   independent_ai__mtplx_qwen38_local / mtplx / mtplx-flash-next-optimized-speed
   / http://127.0.0.1:8002/v1——分诊冻结路由自此跟随绑定swap。
4. MTPLX 产品探针 passed（85.0s含冷加载，响应model身份匹配）。

## 下一轮自检预期路径
②分诊经MTPLX本地（避开瘫痪云；MTPLX串行契约照旧，warm-up只对受管本地端点
生效）；若个别chunk仍失败，partial确认路径（上轮修复+本轮真实载荷复验）
提供"成功批分类即用"的出口——两层保障。③以后各节点按既有链路。

## 红线自检
未碰 live 8910/医学监查；模型服务器只经产品API（MTPLX探针触发编排器加载）；
未清库未reset（零数据写：本ask未动任何业务行，仅代码+测试+证据文件）；
未动immutable；反例先红后绿；主会话并行未提交改动零触碰（working tree中
上轮部分确认修复原样保留待主会话集成提交）。
