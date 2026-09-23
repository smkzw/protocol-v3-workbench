# N5 验收证据（0923V1，2026-09-23）

环境：vite 5186 → 5301（WP6 isolated runtime，当前源码重启）；MTPLX 8002 为主模型。

## 已闭合
| 项 | 结论 | 证据 |
|---|---|---|
| 本地模型身份+质量（原#1未闭合项） | PASS | LOCAL_ENDPOINT_DISCOVERY_0923V1.json n4_real_local_quality 节：精确身份4路一致、小结构化1.08s、effort支持、截断=length、长结构化820tok/13s全字段、产品网关探针passed=true 2.6s |
| V01 三视口截图（原 PARTIAL，历史 CDP 超时） | PASS | v01_writing_desk_{1440,1920,2560}.png + v01_gapfill_review_overlay_1440.png；三视口 scrollWidth<innerWidth 无外层溢出 |
| V06 真实关键决定卡（原 PARTIAL） | PASS | 研究设计基线→4.2动态章节卡：默认预选"不适用，隐藏章节"→选第二状态 retain_not_applicable+医学依据→应用到方案→greenfield_protocol_module_resolution_applied 事件落库（01:20:58Z）→复原 not_applicable+user_override（01:27:03Z）。medical_writing_greenfield.sqlite3 两笔事件 |
| 版本门禁行为 | 观察 | 旧代码后端 api-2e70aad… 被前端正确拦截（fail-closed 生效）；用当前源码重启后过门禁 |

## 进行中/未闭合（如实记录，恢复入口）
| 项 | 状态 | 精确恢复入口 |
|---|---|---|
| A16 局部AI修订（MTPLX） | BLOCKED-前置 | 设计器单元格已选中（第7行/第1列，rail 文案已切"AI只生成该单元格替换候选"），但 提交AI修订 需要已保存工作副本；"保存工作副本"按钮 disabled，详情=方案文档与当前StudyDefinition一致；待审核1项=85章补写候选未决。恢复路径：完成候选审阅（审阅全文初稿→逐项/批量确认→采用）→保存工作副本→设计器选单元格→提交AI修订（textarea此刻才启用）→审核候选→选用写入 |
| V04 等待/失败/断网出口 | NOT_RUN | 同上工作副本前置；断网模拟=暂停8002进程或断开profile |
| A13/A14 摘要/SOA 人工修改保存重开 | NOT_RUN | 需已保存工作副本+GenOffice |
| A21 IME 组合输入 | NOT_RUN | 同上 |
| V07 全旅程点击计数 | 部分 | 本轮到设计卡应用+复原≈12 clicks/2 texts（未含完整旅程） |
| Study C 样本量 | 维持 | 52f6654 已修限定语保真；数值需统计负责人（不代选） |

## 环境备注
- 5301 已用当前源码重启（原进程为旧代码，build gate 正确拦截）；启动 env 与上一 Agent 完全一致（isolated runtime + product DB），仅补装 python3.14 缺失依赖 xlrd/python-multipart（--break-system-packages）
- vite 5186（本会话启动）→ 5301；历史 vite 5187/5188/5199 代理目标已漂移（5303/5304/5299）勿混淆

## 追加（2026-09-23 11:0x）：A16 全链打通至质量门 + 本地模型质量发现
**执行策略第二层修复**：section_ai_candidate 任务在 `ai_execution_policy.py` 被拒（AiExecutionPolicyDenied）——策略表 `_MTPLX_QWEN38_SPEED_POLICY` 仍为 11234+目录名（R01 的策略层化身）。已批量修正三处（策略表/角色默认 profile 常量/preset 模板）→ 8002 + served id。同时发现并修正 profile `provider` 字段语义：必须为五个产品具名 provider 之一（`mtplx`），`openai_compatible` 是传输名不是 provider 名。
**A16 全链实测（MTPLX 真链）**：全屏编辑正文→全屏表格设计器→选中"方案标题"单元格（rail="当前目标：第 7 行 / 第 1 列"）→填修订指令→提交→durable job 入队→策略通过→调用综合AI（MTPLX）→结构化输出解析→**质量门正确拦截**：
- 4 次尝试（1 次自动重试+2 次手动 retry）两种失败签名交替：`revision.alternatives must contain 2 to 4 candidates`（只回 1 个候选）与 `revision candidates must be textually distinct`（候选雷同）
- 按契约 L09：内容校验失败终止，不换模型绕过——系统行为正确
- 结论=**本地模型质量发现（非代码缺陷）**：MTPLX speed 优化档在"一次产出 2-4 个互异候选"的结构化任务上不可靠。可选方向（需 owner 决策）：①MTPLX 服务端采样温度/多样性调参 ②revision 类任务路由到云端（fallback 已配置 opencode-go）③产品支持本地单候选模式
**UI 提交幂等发现**：同章节重复提交走 create_or_reuse 复用同一 business_key（含失败态），换指令不产生新任务——重提规则需产品语义决策（与本 findings 无关，记录备查）。
**V07 累计计数**：至 A16 提交完成 ≈26 clicks / 3 texts（含门禁重检、模式切换、候选审阅、设计卡应用+复原、单元格选择、指令填写、提交、两次重试）。
**恢复后环境**：independent_ai 绑定已恢复 MTPLX(medium) 主路由；fallback=opencode-go(max)；5301=当前源码（含策略修复）；vite 5186→5301。

## 追加2（2026-09-23 12:2x）：修订路由云端已生效+A16采用链P1缺陷定位
**云端路由生效实证**：owner决策"修订任务路由云端"已实现并验证——
- 代码：`ai_execution_policy.py` resolver新增 `_capture_revision_cloud_route`（MEDICAL_WRITING_REVISION主路由=批准fallback链中第一个cloud profile）；`resolve_internal`与`route_identity_snapshot(task_type=...)`两处应用；`medical_writing._policy_identity`提交时传revision任务类型（提交/执行身份一致）
- 回归：tests/protocol_v3 2608全绿（一次批量）
- 实测：durable job `mwjob_872085bf`（版本单元格，provider=opencode-go，model=deepseek-v4.1-flash）**completed**，云端产出4个互异候选（标准推荐/精炼/结构重排/保守，各带依据说明）
**新P1发现（A16采用链）**：绿地桌面（无已保存工作副本）上，新完成候选在"选用并写入"时**必被stale守卫拒绝**："candidate generation context is stale relative to current authoritative state; re-generate"。regenerate→adopt循环复现2次（不同单元格）。根因假设：无保存工作副本时authoritative状态基线持续移动（绿地候选基线vs工作副本双轨），候选digest永远追不上。**修复方向**：①采用前以当前digest重新校验而非拒绝 ②绿地桌面先强制"创建并保存工作副本"再开放AI修订入口（前置门控已存在但创建按钮不可达/保存按钮disabled的链条有断点）。此缺陷使A16的"写入"一步在绿地新项目上不可达=用户视角P1。
**MTPLX本地模型质量（非缺陷，owner已决策云端）**：4次尝试两签名（alternatives 2-4不足/候选雷同）→决策=修订任务路由云端（已实现）；MTPLX仍为其他任务主模型。

## 追加3（2026-09-23 13:4x）：A16 stale 守卫精确根因（实证 diff）
诊断方法：digest 构建处临时记录完整 semantic JSON（证据=gencx_semantic_evidence.jsonl，5 行），对比同线程"提交时"vs"采纳时"重建。
**精确根因**：digest 构建时点不对称——
- 提交时：`submit_revision_durable` 在表格锚解析**之前**构建 digest（semantic.anchor_path=""、table_cell_anchor.block_hash=""）
- 执行器/采纳时：锚已解析回填（anchor_path=结构化 block/cell/row ids、block_hash=内容哈希）→ 重建 semantic 必然不同 → 采纳永远 stale
次要混淆：同 section 多线程按 DOM 顺序堆叠，"选用第一个"会采到旧路由时代的线程（跨线程误采，非缺陷但易混淆）。
**修复方向（下批）**：将 digest 构建统一移到锚解析回填之后（submit 与 executor 同点构建）；或 revalidate 先复现提交时的解析前状态。建议同时：采纳失败时 UI 提示应指引"重新生成"而非静默（当前已有提示文本，合格）。
**暂行状态**：本轮已交付修复的前半（digest 排除 working_copy 块 + 版本升 v3 + 错误分层/可诊断日志已移除但方法保留）；后半（时点统一）需动 submit/executor 构建时序+回归，独立成批。

## 追加4（2026-09-23 14:3x）：A16 采用链闭环 + A13 手动编辑保存重开 PASS
**A16 修复生效实证**：digest v4（排除 anchor_path/block_hash/source_kind 执行期回填字段）下，重新提交修订（版本单元格，指令"AI修订核验V4b"）→ 任务 completed → 候选浮现 → **选用并写入成功**（DB: working copy rev 0→1、applied_revision_thread_ids=[thread_075a7efaf5]、thread status=author_selected）。云端模型正确拒绝了 AI 自述性占位标记（写入的是其术语候选——质量判断正确），写入路径已验证（WC rev bump + applied ids）。
**A13 PASS**：全屏编辑正文中手动键盘输入"（人工编辑核验A13）"→ 保存工作副本 → **版本 2 已保存** → 页面重载后标记与版本均在（a13_manual_edit_persisted.png）。人工编辑→保存→重开链路闭合。
**V04 失败/断网出口**：云端死端点场景（opencode-go→127.0.0.1:9）→ 提交修订 → 任务 failed → UI 显示类型化错误"AI修订失败：AiExecutionPolicyDenied…base URL must be one of…"（失败出口可见、可重试、不损坏状态）。等待出口：多轮任务 running 期间 UI 显示进行中状态无假失败。
**V07 部分**：本轮完整 journey（进入写作→修订提交→任务等待→采纳→手动编辑→保存→重载验证）累计点击/输入 ≈35 次（含调试与轮询；正常用户路径预估 ≈15 次）。
