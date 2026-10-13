# 自检阻断修复② · 新纪元R13第2次自检红节点④（2026-10-13 12:30–13:05 CST，实现师，本ask内实跑）

## 红节点（承接自检报告）
④研究设计确认未达终态。任务书给出的三层次表象：循环依赖链（完成第二步被
"先保存并完成第一步变更"门槛锁住、语料门第5条picos_alignment又依赖PICOS完成）、
design推荐包恒空（"待语料准入和独立AI完成证据绑定后生成3-5个候选包"）、
交互深度超25分钟节点预算。⑤-⑧未到达。

## 根因定位（本ask实证，先证红）
### 甲（服务端，推荐包恒空的本体）：桥接验证器与写入器形状不一致
- live证据（proj_user_ee45e60e004d，r1-2项目）：prefill_package.partial_source_failures
  = `CorpusPrefillBridgeError: round-1 corpus analysis frozen AI route does not match
  the journey-bound route` → AI富化 enrich_package 直接失败 → 候选0、design包0。
- 形状差异（读库实证）：journey侧 `research_pipeline.round1_ai_route` 是
  `freeze_active_route()` 的完整信封（主路由+fallback_chain+fallback_chain_id，
  含opencode-go回退成员）；而 `analyze()` 持久化的分析行 ai_route 永远只是主路由
  （`route.audit_payload()`，corpus_analysis_ai.py:691/2513-2542）。当日全部12条
  分析行 fb=null。`verify_round1_analysis` 的全量 canonical 比对
  （prefill_corpus_bridge.py:448）要求两侧逐字节相等——凡配置了回退链后冻结的
  项目桥接必炸。3d26ddb5（2026-09-23 fallback routes 特性）引入信封，写入器从未跟上。
- 级联：AI预填死 → 无design包 → 测试者只能手填PICOS六模块+五必填维度 → 超25分钟
  预算 → ④未达终态 → ⑤-⑧全堵。
### 乙（前端，循环依赖链的锁）：framing草稿乒乓+误导文案
- live证据（事件表）：rev18 `framing_committed`（04:25:11）→ 62秒后 rev20
  `framing_draft_saved`（04:26:13，missing=0 完整草稿）——完成第一步后一次草稿保存
  重新制造 framing_draft。
- 锁的三重结构（MedicalWritingAuthoringJourneySetup.jsx:1357/3141/3314）：
  framingPendingDraft 锁"完成第二步"、锁picos导航、页脚/按钮title指示
  "请先**保存**并完成第一步变更后再提交PICOS"——而保存正是（再）制造锁的动作。
  r1-2 测试者按指引操作即入环。
### 丙（顺序不明的伪环）：对齐记录门
- "记录PICOS核对结论"按钮此前在 picos_complete=false 时可点、点了才收服务端422
  （"PICOS must be complete before corpus alignment review"）——界面不讲顺序，
  测试者看到的是"记录核对结论"与"完成第二步"互等。

## 修复（反例先红后绿；修链路功能非绕测试）
1. 服务端 `medical_writing_authoring_prefill_corpus_bridge.py::verify_round1_analysis`：
   路由身份比对锚定主路由（从journey-bound信封剥离 fallback_chain/fallback_chain_id
   再比对canonical JSON）。回退链是执行韧性元数据（实际应答者已由行内
   effective_ai_route/output_hash 单独钉住），不参与"分析在哪条主路由上产生"的身份
   判定。主路由漂移仍然拒收（反例②守护）。
2. 前端 `MedicalWritingAuthoringJourneySetup.jsx` 页脚：
   - picos页内新增一键「并入第一步变更」（data-action=promote-framing-draft-in-picos，
     条件 framingPendingDraft && framing_complete；点击=既有 saveStage("framing")
     契约：impact-preview→commit→幂等复核检索），用户不必离开PICOS页；
   - "完成第二步"锁定title改为"第一步草稿未并入：请点击「并入第一步变更」…（无需再保存草稿）"，
     framingDirty分支同理去掉"先保存"指引；页脚文案同步指向新按钮。
3. 前端 `WritingReferencePanel.jsx` 对齐按钮：picos_complete=false 时显式灰因
   "先完成第二步PICOS设计，再记录核对结论（语料门第5条在PICOS完成后即可闭环）"。

## 反例与测试（先红后绿实证）
- pytest反例（红→绿）：`test_fallback_chain_envelope_on_bound_route_still_verifies`
  修前 CorpusPrefillBridgeError（与生产同错）→ 修后过；配套
  `test_fallback_envelope_does_not_mask_primary_route_drift`（漂移仍拒）。
- vitest反例（红→绿）：`frontend/tests/AuthoringPicosPendingFramingDraftEscape.test.jsx`
  ——以r1-2真实状态（rev20+framing_draft完整+framing_complete+picos页）挂载真实组件：
  修前按钮不存在（红）→ 修后出现、title不再含"请先保存"、点击走
  impact-preview→/stages/framing/commit、成功后按钮消失锁解除。

## FAST定向自查（本ask内实跑，全经产品API/真机）
1. 后端带修复重启（复制原env+CMS_ROUTER_API_KEY，graceful kill 57037 → 新pid）；
   `/api/health`=ok；经5186代理 `/api/runtime-readiness` ready=true
   （新指纹 api-471c873e94b2cdab，vite逐请求现算对齐，无需手动build）。
2. MTPLX预热探针 passed（16.8s，产品头）。
3. **真机链路复验（r1-2原项目原路径）**：POST prefill-package/generate(force) →
   桥接零报错，AI富化真实执行（ai_provider=opencode-go，链式回退生效；
   model=deepseek-v4.1-flash；16个证据绑定候选、15个可选、10个无效项被质量门拒）
   → 包落到 rev21：28字段组、44候选（field 36 / module 6 / **design_package 2**）
   ——测试者被承诺的"3-5个候选包"恢复供给。经5186代理读回一致。
4. 套件：bridge+corpus_analysis 162绿；prefill两件 143+48sub绿；adopt/binding/contract
   161+4sub绿；前端 vitest 40文件/225测试全绿（含新反例）；node runner 66/66。
   修后窗口后端日志 Traceback=0。

## 附带复盘（任务书指派）
- r1-1（proj_user_000bbf0a3331）"三连质量门拒收"：错误全文=「independent AI produced
  no evidence-bound corpus findings; rejected: cross-indication finding contains
  non-transferable clinical logic ×3」。检查确认 prompt v12 已明令
  "跨适应症只允许pattern_kind=regulatory_common_structure且module为…"
  （corpus_analysis_ai.py:2381）——门行为正确（跨适应症临床迁移是医学上必须拦的），
  属 MTPLX/glm 输出间歇违约；整单拒收后管线保留工作可重试。不改门；如再现高频违约，
  建议账本立"分析prompt对结构化约束的服从率"项（模型侧问题，非链路缺陷）。
- 任务书产品缺陷观察A（UI与DB口径不同步：batch failed时UI显20/20、一键确认(N)确认0项）
  与B（"生成候选"触发165项…截断）：未在本ask复现路径内，入账本待测试者任务包复验。

## 红线自检
未碰 live 8910/8911/医学监查；模型服务器只经产品API（探针/预填触发编排器加载）；
未清库未删历史未reset（r1-2 journey按产品契约推进到rev21——预填生成本身是测试者
"更新建议"同款操作，幂等留痕）；未动immutable行；产品代码改动三处均为链路功能修复
（bridge比对/页脚出口/灰因文案），反例先红后绿；主会话并行改动零触碰
（medical_writing_authoring_journey.py 的 NEW-37 未提交段原样保留）。
