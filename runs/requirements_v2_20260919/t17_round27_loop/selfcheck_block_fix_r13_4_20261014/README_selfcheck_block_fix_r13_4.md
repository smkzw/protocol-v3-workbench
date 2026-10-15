# 自检阻断修复④ · 新纪元R13第4次自检红节点②（2026-10-14，实现师，本ask内实跑）

## 红节点（承接自检报告）
②竞品分诊两轮 partial_failed：云端 cms-router/glm-5.3-flash 退化日单批 30-60 分钟
且失败；产品层 partial_failed 无前进路径——UI 文案说"可保留已成功分块并重试
其余部分"，但重试=小时级再跑失败批（增量语义在、provider 退化下耗时如全量）、
"锁定深度处理篮子"恒 0 项（成功分块分类不可见不可用）→ ④及以后全堵。

## 根因取证（本ask实跑）
- r1-4 live（proj_user_c1b741eab57a，ct_run_98162dd939cd3e2891fe，读库）：
  6 chunk 中 4 succeeded（21 项分类：9 直接/间接 + 12 排除）、2 failed
  （attempt 3/2，provider error）→ run=partial_failed；
  recommended_retain=9 已在 run 层算出——**成功批分类数据在、但不可用**。
- 死锁双闸门：
  1. 服务端 `confirm_basket` 拒一切非 REVIEW_READY（"run must be fully
     REVIEW_READY to confirm"）且要求全候选精确分区；
  2. 前端批量确认区仅 `status === "review_ready"` 渲染——partial_failed 时
     成功批 AI 分类不呈现，篮子计数取 workspace.decisions（确认时才落）恒 0。
- 对照：重试路径本身是增量的（retry_run 仅 reset 失败 chunk；
  r1-4 第二轮 100 分钟=失败批 2 次调用 × 退化 provider 时长，非全量重跑）；
  r1-3 昨日同路由 35 分钟 completed=provider 退化非代码回归（任务书判断一致）。

## 修复（反例先红后绿；修链路功能非绕测试）
**部分覆盖确认语义（医学安全方向不变：未分诊不得默认保留）**
1. 服务端 `confirm_basket`（medical_writing_competitor_triage.py）：
   PARTIAL_FAILED + 请求显式 `partial_coverage_acknowledgement=True` 时允许确认——
   未分诊候选只能进排除集（放进保留篮即拒，给出可行动指引）；成功批分类正常
   入篮；确认理由强制留痕未分诊处置（"（部分分诊批次未完成：N项未分诊候选
   经医学经理确认暂不纳入本轮篮子：…）"）。未显式知晓→仍拒；failed/running/
   stale→仍拒。契约新增字段默认 False：既有调用方行为零变化。
2. 前端 `WritingReferencePanel.jsx`：partial_failed 也渲染批量确认区；
   未分诊候选预选「暂不纳入」（有效选择集推导，可人工改判）；确认按钮文案
   如实（"确认锁定9项（4项未分诊暂不纳入）"）；确认请求携带知晓标记；
   横幅讲明"云端慢或不稳时先用已分类项推进，不必整轮重跑；确认后仍可重试
   分诊补齐失败批次"。
3. 管线衔接（既有行为验证，无新代码）：retry-triage 见 CONFIRMED run →
   零 AI 直接转 awaiting_triage_confirm（"竞品分诊已完成，请确认保留的竞品
   篮子后继续"）→ 正常续链。

## 反例与测试（先红后绿实证）
- pytest（红→绿）：`test_partial_failed_run_confirmable_with_explicit_
  acknowledgement`——修前在生产同款错误处红（"run must be fully REVIEW_READY…
  current status: partial_failed"）；修后绿：未知晓拒 / 知晓但未分诊进保留篮拒 /
  知晓且未分诊仅排除→确认成功+投影落地+run CONFIRMED+理由含"未分诊"。
- vitest（红→绿）：`WritingReferencePanel.partialConfirm.test.jsx`——修前
  批量确认区不渲染红；修后绿：确认区呈现、未分诊预选排除后按钮可点、
  POST 体含 partial_coverage_acknowledgement=true、保留篮=成功批5项、
  排除=未分诊4项。

## FAST定向自查（本ask内实跑，全经产品API/真实数据）
1. 套件：triage 三套+D017验收+contracts+前端契约 = 575 passed + 77 subtests；
   vitest 全库存 41 文件 / 227 测试全绿。
2. 后端带修复重启，经 5186 代理 ready=true（api-a744e7bfaf0cdeae）。
3. **真实受阻项目复验（r1-4，任务书指名供原路径复验）**：
   - 读库构造确认体：保留=成功批 9 项（NCT05277415 等）、排除=12 已分类排除
     + 10 未分诊、全 31 候选精确分区；
   - POST confirm（partial_coverage_acknowledgement=true）→ 200：
     confirmation_id=ct_conf_a432d9ef52d2f1425091，理由含未分诊留痕
     （首试投影因我误填 expected_journey_revision=18 而拒——真实为 3；
     经产品 projection-retry 端点幂等补投：journey rev4、discovery 投影
     confirmation 落位、retained 9 项）；
   - POST retry-triage → 零 AI 转 awaiting_triage_confirm——②红节点的
     死锁出口在真机打通，链条回到用户决策点，④修复现场自此可达。
   - 注：r1-4 的确认由实现师经 API 完成（任务书授权的原路径复验）；
     UI 路径由 vitest 覆盖，下一轮自检可在新牺牲项目走界面全流程。

## 未修项与如实说明
- 云端退化本体（cms-router 单批 30-60 分钟/间歇失败）与 opencode 订阅失效、
  MTPLX 大载荷 507：环境侧，非本批范围；本修复使退化日"成功批可用"，
  不再整链瘫痪（任务书附观察①的部分缓解）。
- 任务书附观察③（长跑 vite esbuild 崩溃列入检查单）：运维建议，未动代码。
- 全量 pytest 未整跑（每轮收尾脚本职责，非本 FAST 范围）。

## 红线自检
未碰 live 8910/医学监查；模型服务器零接触（本修复全程无 AI 调用——确认与
恢复均为纯状态转换）；未清库未reset（r1-4 经产品幂等契约推进 rev3→4，
确认/投影/恢复全留痕）；未动immutable；反例先红后绿；主会话并行改动零触碰。
