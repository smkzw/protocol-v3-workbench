# 自检阻断修复③ · 新纪元R13第3次自检红节点④（2026-10-14 08:30–10:10 CST，实现师，本ask内实跑）

## 红节点（承接自检报告）
④研究设计确认两轮复现的结构性死锁。测试者判断"design推荐包被语料门拦截"+
"采用当前方案文字建议只写UI态不落库"。

## 根因取证（本ask实跑，先证红）
### 甲（主根因）：真实design包候选与误导性骨架占位卡并存
- live证据（proj_user_572869985339，rev13包，2026-10-13 14:34生成）：
  `design_recommendations_unlocked=True`（reason=research_pipeline_round1_material_ready）
  ——语料门**并未**拦截design推荐生成；包内 `package.design` 组同时有：
  ①真实design_package候选（preview"竞品Protocol观察：随机、安慰剂对照"、
  confidence=medium、claim_bindings证据绑定、structured_value含全部design维度）；
  ②确定性骨架占位卡（preview"design模块待AI基于语料生成"、rationale"模块结构已准备；
  待语料准入和独立AI完成证据绑定后生成3–5个候选包"、confidence=none）。
- 组合包按医疗安全策略恒为 manual_only/pending_decision（evidence_binding.py:954
  "Composite packages retain their existing per-path policy gate"）→推荐槽按
  `select_safe_recommended_candidate_id` 契约留空 → UI无预选、骨架卡在列——
  测试者把骨架卡读成"推荐包未生成"，④级联卡死。骨架文案源于
  medical_writing_authoring_prefill.py:913（生成时点为真，AI真实候选到达后失真）。
### 乙：「采用当前方案文字建议」只写UI态
- applyTextSuggestion（Setup.jsx）仅 updateFraming("structured_design")，无任何
  落库动作；刷新/切页即丢（测试者DB查询实证journey侧全空）。
### 丙（本轮新发现的环境性阻断，非本红节点本体但卡住真机复验）
- AI富化传输三面墙：MTPLX对大载荷（135K字符实测）HTTP 507（容量守卫，间歇）；
  opencode-go回退位 **403 订阅失效**（"An active OpenCode Go subscription is
  required"，2026-10-14新出现——昨日还可用）；cms-router对同级载荷 504（上游超时，
  两次实测9:40/7:00）。r1-3昨日rev13富化经MTPLX成功（ai_outcome=completed）证明
  代码路径通，容量边界随服务器状态漂移。

## 修复（反例先红后绿；修链路功能非绕测试）
1. 服务端 `_merge_ai_candidates`（prefill_ai.py）：真实AI候选存活时剔除该组的
   确定性骨架占位卡（preview尾缀"模块待AI基于语料生成"精确定位，仅
   _enforce_deterministic_prefill_safety会生成该文案）——真实内容到位后骨架卡
   即过期误导信息；无真实候选存活时骨架卡保留（该模块确属待AI，文案为真）。
2. 服务端 新增 `_refresh_uncovered_package_scaffold` 并接入 enrich_package 合并环：
   富化已运行（有存活候选）但某package模块无候选时，该模块骨架卡文案如实刷新为
   "XX模块本轮AI未给出建议…可点「更新建议」重试，或在下方表单手动填写"——不再
   声称"待语料准入和独立AI完成证据绑定"。
3. 前端 Setup.jsx：「采用当前方案文字建议」应用后经nonce-effect立即保存第一步
   草稿（structured_design属framing；effect在状态提交后执行避免stale闭包）——
   建议即时落库，刷新/切页不丢。
4. 前端 AuthoringCandidatePackagePanel：无系统预选时的空槽文案改为讲明策略
   （"组合含需医学经理逐项确认的决策（随机化/盲法/对照等），系统不代选；请点选
   下方候选、逐字段确认后采用"）。
5. 环境修复（经产品API，备份在位）：回退链死成员 opencode（403订阅失效）换为
   cms-router/glm-5.3-flash profile（`PUT /api/ai-gateway/fallback-chain`，备份
   `.pre-fallback-swap-20261014`）——原链在主位任何瞬时故障下都被403毒死。
   opencode订阅续费后可由owner换回（订阅续费=owner行动项）。

## 反例与测试（先红后绿实证）
- pytest反例（红→绿）：`test_real_ai_composite_prunes_deterministic_scaffold_placeholder`
  ——修前merged=['真实卡','design模块待AI基于语料生成']（复现现场）→修后仅真实卡；
  配套`test_scaffold_kept_when_no_real_ai_candidate_survives`（无真实候选时骨架保留）；
  `test_uncovered_scaffold_text_refreshed`（文案如实刷新，ImportError红→绿）。
- vitest反例（红→绿）：`AuthoringPicosPendingFramingDraftEscape.test.jsx`新增
  "采用当前方案文字建议应用后立即落库第一步草稿"——摘除接线复跑证红
  （git stash push/pop实证），恢复后绿：POST /stages/framing/draft 发出且
  structured_design.randomization_mode='randomized' 入库草稿。

## FAST定向自查（本ask内实跑）
1. 套件：pytest 桥/预填AI/证据绑定/组合采用/包契约 466 passed + 68 subtests；
   vitest全库存 40文件/226测试全绿（含新反例）。
2. 后端带修复graceful重启，经5186代理 runtime-readiness ready=true
   （api-a0157a8b538f1ff1）。
3. **真实生产数据验证**：取r1-3 rev13包的真实骨架卡+真实AI卡（live快照
   /tmp/j_r13.json），过修复后的 `_merge_ai_candidates` → 输出仅1卡=真实
   design包，骨架卡剔除 ✓（对生产载荷的确定性验证）。
4. 真机HTTP端到端（POST prefill-package/generate ×5）：均因丙（传输三面墙）
  富化失败、确定性骨架包回落——**未能取得一次成功富化的真机绿**，如实报告。
   期间r1-3 journey rev18→23（产品幂等"更新建议"同款操作，事件全留痕）；
   最终态 rev23：framing_complete=True、framing/picos草稿均None、语料门4/5
   （第5条picos_alignment按序待PICOS完成，上一批修复的灰因文案会讲明顺序）。
   一旦传输侧任一路由可达（MTPLX容量窗口/订阅续费/cms-router放宽超时），
   测试者点「更新建议」即得修复后形态的包。

## 未修项（如实）
- 高级微调4tab全disabled/抽屉死点击（任务书④-(5)(6)）：代码读证
  interactionLocked=Boolean(busy||impact)、抽屉open=setState(true)直写——
  无静态死锁路径；无浏览器复现条件下不盲改（疑为busy卡住或impact面板遮挡的
  会话态），入账本待测试者任务包复验时带截图定位。
- MTPLX大载荷507的容量边界与富化载荷瘦身（目录投影裁剪）属产品/环境决策，
  本ask未动，建议账本立案。

## 红线自检
未碰 live 8910/医学监查；模型服务器只经产品API/编排器（探针与富化触发加载）；
未清库未reset（r1-3经产品幂等操作推进并全留痕；运行时配置改动仅回退链一处，
备份在位）；未动immutable；反例先红后绿；主会话并行未提交改动零触碰。
