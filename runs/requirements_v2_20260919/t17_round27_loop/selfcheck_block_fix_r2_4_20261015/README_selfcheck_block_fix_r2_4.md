# 自检阻断修复 · 纪元R2第4次自检收尾批（2026-10-15，实现师，本ask内实跑）

## 背景（承接自检报告）
本轮自检无功能红节点（allGreen=false为保守判定：⑤16/23批运维帽主动停、
⑧带占位预览件均为'证据到手即停'）。本轮四条遗留观察按根因修复三条
（②无恢复按钮/③剂量政策select不入库/①section任务路由审计口径），
④（确认变更清空表单）经风险评估后本轮不修（理由见下），如实记录。

## 修复（反例先红后绿，修链路功能非绕测试）
### ②（P0姊妹缺陷）：cancelled 全文初稿任务无续跑入口
- 根因（读码）：resume按钮渲染条件 `status === "failed"`——cancelled 被漏；
  且「生成全文初稿」幂等复用命中已结束任务后（POST /full-drafts 返回
  reused+终态），前端仍走 monitorFullDraft 轮询一个永不变化的终态job直至
  抛错——用户既看不到续跑按钮也不明白发生了什么。
- 修复（App.jsx）：新增导出纯函数 `fullDraftResumeVisible`（failed/cancelled
  → true）与 `fullDraftReusedTerminal`；渲染条件与 startFullDraft 复用分支
  全部改走纯函数——cancelled 任务显示「续跑全文初稿（已完成批次会复用，
  不会重头再来）」；复用命中终态时不再空转轮询，直接给出中文指引指向续跑
  按钮。resume 端点本身（main.py:8288 NEW-35，批次级复用）上轮已被测试者
  实战验证（cancel后resume从第4批续跑）。
### ③（r2-2遗留：IP剂量调整政策select不入库）
- 根因（机制级，与上轮⑤同族）：旅程写回合并对标量"incoming非空即整替"，
  而服务端旧快照的 `ip_adjustment_policy` 是哨兵值 `"unspecified"`（非空）→
  测试者设好政策后，任何旅程写回（管线运行期高频journey刷新）把
  `no_planned_adjustment` 清回 `unspecified`。上轮哨兵修复只加了
  unknown/undecided，漏了本字段的哨兵。
- 修复：`unspecified` 入 MERGE_PLACEHOLDER_VALUES（Setup.jsx）——与枚举
  字面值一致（InterventionRulesIpAdjustmentPolicy.UNSPECIFIED）。
### ①（审计口径不一致）：section任务缺顶层路由审计字段
- 根因：section_ai_candidate 的路由只在 `generation_context.descriptor.
  ai_policy` 深层；protocol_full_draft 在顶层 `descriptor.ai_policy`——
  审计侧按payload顶层找路由扑空。
- 修复（medical_writing.py）：initial 与 rewrite 两条 durable 创建路径的
  payload 顶层新增 `ai_route` 摘要（provider/model/base_url/route_profile_id/
  transport/deployment_profile/required_response_model/route_identity_hash/
  frozen_at，与descriptor.ai_policy同源，创建时点冻结）；新增模块级
  `_frozen_ai_route_summary`。纯增字段，不改执行路径。

## 反例与测试（先红后绿实证，git stash摘除对应改动证红）
- ②：新测试 frontend/src/fullDraftResume.test.jsx（2件）——修前import失败
  （纯函数不存在=旧UI面无此能力）+App.jsx stash后2红→修后绿（cancelled/
  failed可见、running/queued/completed/undefined不可见；复用终态判定）。
- ③：sentinel测试新增第4件——unspecified不覆盖本地no_planned_adjustment
  及声明文本——stash后3红（含本件）→修后4绿。
- ①：tests/test_medical_writing_revision_durable.py 新增
  test_section_job_payload_carries_top_level_ai_route_audit_summary——
  stash后FAILED（无ai_route键）→修后绿（provider/model/base_url/
  route_profile_id与descriptor.ai_policy逐项同源+frozen_at）。

## FAST定向自查（本ask内实跑）
- 套件：durable三套 191 passed；前端全库存 43文件/239测试 + node 66
  全绿（新测试先以.mjs落地被node runner正确拒 imports .jsx——改.test.jsx
  归位vitest，inventory分派语义验证为真实行为）。
- 后端带①修复重启（graceful），经5186代理 ready=true（api-be4132cd4b8c8413）；
  vite 200。
- r2-2现场对账：被运维帽cancel的全文初稿任务（mwjob_9bc4c0b9，cancelled）
  在库可查——修复后UI将对其显示续跑按钮；**未实际触发resume**（会重启
  小时级23批AI任务，留待下一轮按需执行——端点行为已有上轮实战证据）。
- 新创建的section任务将携带顶层ai_route（下个section任务可验）。

## ④不修理由（如实）
'确认变更并重新核验'清空已填PICOS表单：确认面板提交的是**打开面板时点
的payload快照**（后端CAS要求impact_preview_id与payload绑定，改值需重走
预览），面板打开后用户继续编辑的内容会被快照回写覆盖。正确修法需"确认前
检测表单漂移→自动以当前值重走预览"的产品级交互决策（涉及确认语义变更，
可能引入静默重预览的新歧义），超出本批FAST边界——留待与观察C（表单交互
复杂度）同批产品化处理。

## 红线自检
未碰 live 8910/医学监查；模型服务器零接触（本ask无AI调用；未触发resume）；
未清库未reset（零业务行写入）；未动immutable；反例先红后绿（stash三组）；
主会话并行未提交改动零触碰。
