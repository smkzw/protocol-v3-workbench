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
