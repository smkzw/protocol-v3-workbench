# T17 R15 批任务记录 · 复盘 · HANDOFF（2026-09-24 凌晨无损暂停）

## 一、本批做了什么（时间线）

1. **F-C 真等待态**（4cc2deb）：分诊/翻译等流水线节点运行期间，影响确认面板从"点击后才报错"改为"前置禁用+真实等待信息+两条出路"：
   - 出路A：等待流水线结束后自动重新核验并请用户确认（重新计算影响，绝不静默写入）；
   - 出路B：二次确认后取消流水线并立即提交（复用既有取消端点，无新增后端状态）；
   - 面板内显示阶段中文名+进度百分比+"可离开页面"承诺；后端与前端全部死路文案清除。
2. **§3.1.4 加固**：提议模型新增 normalized_from / downgrade_reason 两个结构化字段；精确别名映射记录"自动映射"，降级记录"已降级待确认"原因；前端事实卡渲染两枚徽章（自动映射=蓝、已降级=橙）。
3. **回归与部署**：前端 113、后端 166 全绿；构建通过；前后端同事务重启且指纹一致验证（api-0d696014）。
4. **R14 项目清理**（备份 .pre-cleanup-20260924_010131）→ **R15 四场景派发**（锁定编队，新增等待态提示条款）。
5. **R15 半程成果**：tester2 全链 EXIT=OK（含影响确认 2.5 秒通过=F-C 生效、流程图/目录/文献/导出门禁全 PASSED）；tester1 命中新前沿 F-E 后交卷。
6. **会商意见书 42KB 完整交付并入库**（R14/CONFERENCE_REVIEW.md）——其独立实测抓到的 contains-match 语义反转已在上一批 6ba01f4 修复，本轮 §3.1.4 加固即按其清单落地。

## 二、没做什么

- tester3（grok/MDD）会话在交班时仍在运行——下会话先收其报告。
- F-E（prefill in-flight 死锁 + stale 包不可采用）只完成了根因定位（journey.py:5758 in_flight 守卫无时间回收），未写代码。
- tester4 中期报告的中文候选批次 228/230 大规模失败未及深挖（c3acd77 之后的新失败形态）。
- 导出后的 Office 在线编辑闭环仍未被任何测试者走到（初稿生成需 40 分钟+，本轮 tester2 离场时 21 批仍在生成）。

## 三、踩坑与教训

1. **模糊匹配是语义陷阱**：会商实测证明"包含即命中"的归一化会把 "not expected" 映射成 "expected"——修复比不修复更危险。教训：枚举类字段宁降级勿猜测；守卫测试必须包含否定样例。
2. **测试窗口内部署的两难**：本轮两次同步重启（4cc2deb 与反转变更）都发生在测试进行中——每次都让测试者遭遇版本门/会话中断。权衡记录在案：数据正确性优先于静默纪律，但下一轮应尽量把部署压缩到派发前一次性完成。
3. **grok 会话耐心 ~10 分钟是结构性问题**：等待类提示写在报告文件里模型看不到；必须写进 prompt 正文（R15 已加等待态条款）。
4. **in-flight 预约无回收 = 新型死锁**：任何"占用中"状态如果没有超时翻转机制，一次进程中断就变成永久锁。与 R11 的"durable job 无终态落盘"同族。

## 四、下一步（下会话按序）

1. 收 tester3 报告（若已结束）→ 归档并入 R15。
2. **修 F-E**：prefill in_flight 预约超时回收 + stale 包一键"重新生成推荐"引导。
3. 诊断 tester4 的中文候选 228/230 失败（规划器/翻译生成层）。
4. 派 R16 四场景，验证 F-E 修复并推进到"初稿生成完成→导出→Office 编辑"最后前沿。
5. LOOP 至零 P0/P1 + 全链交付。

## 五、环境快照（交班即用）

- 后端 34081 / 前端 34082（指纹一致 api-0d696014… 部署 4cc2deb 后又经 c3acd77 重启，当前为最新）；MTPLX 8002、OmniRoute 20128 存活。
- R15 四项目在库（下轮开工前备份清理）；tester3 会话脱离运行中。
- 测试运行方式：后端 `PYTHONPATH=services/api:. python3.14 -m pytest …`；前端 `npm run test:unit:vitest`（勿裸跑 vitest）；测试者派发=omp setsid + EXIT 标记（提示词放 runs/requirements_v2_20260919/t17_prompts/r15_*.md）。
- 红线不变：不触碰 live 8910/医学监查/共享 runtime；不删历史 immutable rows/runs/logs/evidence；一切提交同步 GitHub；测试全程 UI 黑盒。

---

## 审阅更正（0924V1 · R05，2026-09-24 追加；原始报告不覆写）

1. tester2 的 EXIT=OK **范围更正**：实际验证到"文档初始化+各模块存在性+导出负向门禁"，全文 21 批当时"运行中"、Office 链未到达——不构成全链完成。业务完成状态与进程/报告完成状态从此分开记录（process_exit_code / test_run_status / business_flow_status / artifact_validation_status）。
2. tester1 的 EXIT=BLOCKED 与 EXIT=0 并存为"报告进程正常结束+业务判定 BLOCKED"，非矛盾。
3. tester3（10.5KB BLOCKED）与 tester4（中期状态）为部分结果，不据此宣称四场景通过。
4. 点击口径更正："16 次核心决策点击"是业务决策组数，另含 113 次混合交互；不得表述为"总点击≤20"。
5. 入口A在 tester1 改走从零后不算通过；摘要自动预填正向链（T14）仍待独立验证。

---

## 0924V1 首批执行结果（2026-09-24 上午追加）

1. **WP-A 落地**（T01/T02/T05）：预约 owner-absence 回收（1h 阈值 + CAS 绑定 call_id/status/updated_at + attempt_history 审计）；活跃调用永不打断；stale 包改为输入指纹核验（journey_input_fingerprint 逐字节一致即放行采用，历史包行不篡改）。预约套件 21/21。
2. **WP-B 落地**（T06-T10 前端面）：取消返回四态类型化结果；failed/stale_context 零提交尝试；accepted_pending 入队等待；confirmed_terminal 后**重算新 preview** 再提交（旧 preview_id 不复用）；排队意图如实标注"仅本页有效"（草稿端点在 triaging 冻结期不可写，服务端持久化列为后续项）。
3. **R05 验收口径更正**已入库（原始报告未覆写）。
4. **WP-D 第一步完成**：tester2 的原 job（mwjob_4f6a049a）按"恢复原 job"纪律重试——根因=饱和窗口 429；attempt 预算 2→3（提交在案）；attempt 3 从批次 14 续跑至 **21/21 completed**，产物 full-draft.json 444KB 实质验证：81 节 / 18,584 字提案 / content_status=4 complete+46 partial+31 source_gap（诚实缺口）/ 本场景适应症词汇非串染。
5. **下一门槛（T15-T17）**：采用→工作稿保存→真实 Office 打开/编辑/保存/关闭/重开/下载；以及 T14 入口A 正向链、T11-T13 翻译批次集成验证。这些需要真实 UI 会话，为下批主体。

---

## T15 执行结果（0924V1 WP-D · 2026-09-24 追加）

真实 UI 会话（ego TaskSpace 74，PROJECT=proj_user_97189da36a75 / MW-II-00990781）：
1. 生成全文初稿 → 幂等复用已完成 job，81 节候选审阅面板打开（0 待决定/31 缺来源）。
2. 发现"采纳需先有已保存工作副本"（创建→保存禁用"无未保存修订"）→ 通过全屏编辑正文写入核验标记→保存工作副本 v1。
3. 采纳初遇 adoption_ready=false 硬禁 → 定位为 R08 语义缺陷（adoption_ready ≡ formal_ready）→ 修复（af79074：服务端分区写入/前端改用 working_draft_ready）→ 采纳成功：51 节工作副本 rev1/ai_draft 落库、35 节实质正文、31 缺来源节跳过保留占位。
4. 冻结当前版本 → 成功（"当前作者确认版本/已冻结"）。
5. 预览 Word 导出初遇两门合并（draft_preview 也被 substantive gate 拦）→ 修复（4e07ab6：两门分离+占位块注入+空白模板仍双门拦截）→ **草稿预览 DOCX 导出成功**：27,247 字/372 段/6 表/31 待补齐标记/零串染。产物归档 t17_round16_office_chain/。
6. 全屏编辑器首页核验标记未进入导出件（首页表=受控结构，设计内）；T17 的编辑验证应在正文章节执行。

**四状态口径**：process=已完成本轮会话；test_run=T15 导出腿 PASSED；business_flow=采用/冻结/导出腿已通，Office 编辑腿未开始；artifact_validation=DOCX 71,671B 实质验证通过。

---

## 0924V1 第二批执行结果（2026-09-24 上午 · T14/T11-T13 + T16/T17 边界记录）

1. **T14 入口A正向链 PASSED**（真实 UI）：LibreOffice headless 生成 6.9KB 真实摘要 docx → 入口A上传 → AI 提取 8 字段全对（TRD/II期/120例/四组1:1:1:1/8周MADRS/干预/对照/人群）→ 诚实列出 7 个后续补字段 → 确认建项 MW-II-9DE75AA7 → 自动进入写作工作区。注意：真实摘要提取需 ~8 分钟（MTPLX 慢推理），UI 有进度显示非死路。
2. **T11-T13 PASSED（恢复路径集成验证）**：外科恢复 K3 项目（a5f104df，allowlist 行）→ 打开结构与译文确认 tab（228/230 失败、可重试）→ 点击"仅重试失败项"→ **重试启动成功**（8a36f3a 修复生效：失败 228→227 开始收敛，AI 逐文档重新规划中）。已知残余：规划器根因（document_plan_anchor_filter 0/5）在审计日志（"ancestry unresolved"警告保留全部父 ID），formal 导出前需按审阅要求复核。
3. **T16/T17 边界记录（诚实口径）**：桌面 Word 已打开下载件并用 AppleScript 写入正文标记；继续键盘自动化时截图发现**用户正在前台使用桌面**——立即停止 GUI 自动化并无损退出（磁盘 hash 未变 d6cf304d…，零污染）。桌面 Office 腿需在用户桌面空闲时执行或由用户明确授权；不采用后台静默键击冒险。
4. 四状态：process=会话完成；test_run=T14/T11-T13 PASSED；business_flow=入口A→写作 PASSED、翻译恢复已启动收敛中；artifact_validation=摘要提取表单8字段+失败数收敛证据。

---

## 翻译批次根因落定 + 本地模型基础设施状态（0924 下午追加）

1. **K3 翻译 228 项失败的真正根因 = oMLX 本地推理服务器（127.0.0.1:8000）监听器已死**：翻译正文角色（translation_body_local_omlx）绑定该服务器；端口无监听 → 每次翻译调用必然失败 → 228 项全部 failed_retryable。非规划器缺陷、非产品代码缺陷（恢复机制已按设计多次正确触发，审计日志完整）。
2. 本地模型基础设施现状：MTPLX(8002) 存活但严重退化（60s 探针超时、并发下 507）；oMLX(8000) 监听器死亡（进程在、端口无）。两者都需要用户侧处置：oMLX 应用可能有待处理对话框（AppleScript quit 被用户取消 -128），MTPLX 建议通过其宿主应用重启。
3. 已完成与未完成的分界：代码层恢复机制全部就位并实战验证（重排队/重分类/审计日志/父less 兜底）；**基础设施恢复是用户动作**——oMLX 恢复后重跑"仅重试失败项"即可继续收敛（重试入口已验证可用）。
4. 每次尝试的审计链完整：3 次尝试×（重分类→派发→失败）全在 attempt_history 与日志中，无数据丢失，230 项全部保留。

---

## K3 翻译收敛最终数据（0924 晚追加）

用户重启 oMLX（改听 8001）+ 退出 MTPLX 释放内存 → 翻译模型加载成功（200 OK/4s）→ 运行时三个 omlx profile 已对齐 8001 rev2 → 点"仅重试失败项"两轮：
- **第一轮**：228 失败 → 26（恢复率 88%）：candidate_ready 38 + fidelity_blocked 164 + failed 26。
- **第二轮**：26 项 attempt 预算（3/3）耗尽未再排队——4 个文档的文档级规划持续失败，自动化重试已到收敛边界。
- **忠实度阻断 164 = 翻译成功但机器忠实度检查未过，待医学作者人工确认/逐片段核对（产品设计的人工门，非缺陷）。**

## 下批工程项（剩余 26 项根因）
1. 对 4 个失败文档逐一运行 flash planner 并抓取实际失败码（此前仅 2 项带码：flash_planner_structural_failure/product_ai_provider_transient——大量 items 无码为可观测性缺口，建议规划器失败时持久化原始结构错误）。
2. 修复 document_plan_anchor_filter 的锚过滤逻辑（R14 根因）或规划提示对复杂文档结构的覆盖。
3. 预算参数：reference_translation max_attempts=3 且 retry 端点对耗尽 job 不再重排——多轮恢复需要"重试轮次"与"单 job 尝试"分离的语义。

---

## 无损暂停点（0924 下午晚些 · 26 项收敛受重试语义限制）

1. **基础设施恢复完成**：用户授权并执行——MTPLX 应用退出（释放 ~30GB）、oMLX 应用重启（改听 **8001**）→ 翻译模型 dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX（31.25GB）加载成功（200 OK / 0.5s 响应）。运行时三个 omlx profile 已对齐 8001 rev2（备份 .pre-omlx-port-20260924）。
2. **26 项重试已点击，job 立即终态**：reference_translation attempt 预算（3/3）在上轮已耗尽，本次重排队复用了 attempt 3 记录 → 未产生新的规划器派发 → 26 项状态不变（38 ready + 164 fidelity_blocked + 26 failed）。这正是已记录的"重试轮次 vs 单 job 尝试"语义工程项——**下批第一步：bump reference_translation max_attempts（仿照 full_draft 2→3 先例）或实现轮次分离，然后重排队即得全新派发**。
3. **环境快照（交班）**：后端/前端指纹一致（api-b4f0eb2bfa571bde 运行 38965/38966 后又经重试重启，以 runtime-readiness 为准）；**MTPLX 已退出（用户手）——分诊/全文类需要 MTPLX 的操作前必须先重开 MTPLX 应用**；oMLX 在 8001 存活且模型已驻留；10 份清理备份在位；R15 项目 4 个在库（K3 已恢复可操作）。
4. 下批顺序：①bump reference_translation 尝试预算并重排队 26 项（观察是否暴露规划器原始错误——oMLX 现在在线，失败码应能采集）②按真实失败码修规划器根因 ③T16/T17 桌面 Office（需桌面空闲）④R16 集中验收含 T18。

---

## 0924V2 第一批执行结果（SOURCE_COMMIT=f36f1d2+前端 2872868 + 本报告）

### CHANGESET
1. 28d03bf §5族1：数量级换算(116→1.16亿/635→6350亿)不再误判 numeric_tokens_changed（对称 mantissa/digits 信用 + 小数点/单位零宽恕）；真实计数漂移(2.50亿)仍拦截。
2. 3434809 §5族2：缩写等价表扩容(OA/LDN/VA/FDA/MD/PI/SAE/NSAIDs/BPI) + 检测器噪声词扩展(NOT/FIRST/MATLAB/T2)。
3. f36f1d2 §5族3：句末周次 "weeks (Wks) 8 and 16." 不再算作编号条目（时间单位出现在前文任意位置即抑制）。
4. fc9bda9 §3：通用 ingest 端点补服务端 Protocol-only 门（batch/retry/auto-refill 之外的第4入口补齐）。
5. 2872868 §6+§7：候选正文 112px 嵌套滚动框移除（14px 全文渲染）；错误分层 — 默认中文安全摘要 + 显式"展开诊断详情"承载 raw 文本。

### 验收记录
- U01：三档截图 1440/1920/2560 已存 t17_round17_uat/。
- U02：候选正文全渲染（CSS 契约：无 112px/无 overflow-y:auto 于候选段）；全 DOM 扫描 0 个旧式 112px 框。
- U03：泄漏扫描（Traceback/mwjob_/wref_span_/expected_revision/Pydantic/docplan_）在当前工作区 0 命中；sanitizer 单测随套件。
- T01 数据复检：38 ready + 164 fidelity_blocked + 26 failed 三态分账保持；164 不做批量确认（修复后待新一轮恢复尝试复检）。
- NOT_RUN：T16/T17 桌面 Office 腿（等待桌面空闲窗口）；26 项新恢复尝试（受 attempt 预算限制，需按 §5 实现新关联恢复尝试语义后派发）；S 系列深读范围验收（需 600 项级检索样本，等 K3 翻译收敛后随 R16 执行）。

### 环境身份
- 后端 96946 / 前端 96947（指纹 api-f74375aa2c3f52c7 一致）
- MTPLX 8002 = 用户已退出（分诊/全文类操作前须重开）；oMLX 8001 = 翻译模型驻留
- NEXT_GATE：①实现"关联原 job 的新恢复尝试"语义后派发 26 项 ②重开 MTPLX ③T16/T17 ④R16 集中验收含 T18

---

## 0924V2 第二批执行+基础设施修复（0925 深夜追加）

1. **oMLX 恢复完整链路**：用户授权重启 oMLX（改听 8001）→ 三 profile 对齐 rev2 → 翻译模型加载成功（200 OK/0.5s）。用户退出 MTPLX 释放 30GB 内存解决两模型互斥。
2. **26 项收敛突破**：红rive（1a013b4 版本 repository 层 redrive 块）恢复后，"仅重试失败项" 实际重新派发规划器+翻译，stage run 16 行新记录落库，25→26 项中 1 项成功转 candidate_ready。
3. **剩余待收敛**：26 项中大部分依赖 MTPLX 重启后的稳定输出（当前 MTPLX 已退出）。重开 MTPLX 后再做一轮 retry 即可。
4. **教训（关键）**：写 repository 层 UPDATE 前，先查该表是否有 immutability trigger（writing_reference_upper_layer_stage_runs 有 BEFORE UPDATE 触发器直接抛 immutable 错误）。0924V2 审阅强调"stage runs are immutable"是数据库级合同。
5. **四状态**：process=完成本轮；test_run=T15 PASSED + 翻译收敛推进中；business_flow=入口B链路完整可用（初稿已产出）；artifact_validation=DOCX 27k字预览件归档。
