# K3 快照权限门修复设计笔记（2026-09-26，主会话侦察）

## 缺陷定性
`writing_reference_translation_batch.py::_snapshot_scope`（:4109-4148）对合法早期旅程状态死锁：

1. **search_plan=None 是模型层合法状态**：`medical_writing_authoring_journey.py:494-497`
   `search_plan=(self._search_plan(...) if search_ready else None)` —— 建项时 framing 未就绪
   即为 None；模型层 ：173-182 还有早期记录的 search_plan 形状迁移逻辑，字段本身可选。
2. **门的两处强求**：
   - Path B（:4140-4143）：`journey.search_plan is not None and journey.search_plan.latest_snapshot_id == snapshot_id`
   - 门后无条件检查（:4150-4156）：`journey.search_plan is None or latest_snapshot_id != snapshot_id` → raise
   - 后果：即使 Path A（finalized triage）通过，search_plan=None 的旅程也会被无条件检查拦死。
3. **与 26 项根因同族**：读侧（批次门）索要写侧（bootstrap 流程）从未保证的状态。
   K3 批次 09-23 18:55 创建即 574 项 failed_retryable，非清理丢失、非模型故障。

## 权威事实（调度员实测，见 k3_gate_diag.md）
- discovery_basket_projection 存在且 confirmation_id=ct_conf_ebb394de59fb68021378、
  snapshot_id=wref_search_4d2c5d3b8476515fc38b 与批次完全一致；
- 权威快照行 wref_search_4d2c5d3b8476515fc38b 在 writing_reference_search_snapshots
  （created 2026-09-23T17:21:39，与 bootstrap 同刻）；
- prep 批次 wref_prep_cc8a67c458de4225cd09ce38 在；
- journey 行 mwjourney_f234ada236f028ce9849 rev=6 已从 pre-cleanup-20260924_040239 备份
  原值 INSERT 恢复（同源 bootstrap 事件，纯新增合规）。

## 修复方向（待 planner→评审→实现→测试门）
核心：**快照权威已由“确认的发现篮投影+冻结 prep 批次”独立成立时，search_plan 不应是一票否决**。

方案 A（最小，倾向）：无条件检查改为——
`search_plan 存在时才绑定 latest_snapshot_id`；search_plan=None 时若 Path B 已通过
（确认投影的 snapshot_id 与批次一致），投影即为当前性权威（投影在篮子确认时写入，
若之后有新检索会产生新快照与新确认，旧批次持有旧快照属预期冻结语义，且门随后
`preparation_service.latest(project_id, snapshot_id)` 已把范围钉死在本批次快照上）。
Path A 通过时同理：finalized triage 自带 triage.snapshot_id==snapshot_id 匹配，已验当前性。

方案 B（补充，可并行）：bootstrap 建项时若已产生搜索快照，则同步写入 journey.search_plan
（修写侧缺口，惠及未来项目）；存量项目靠方案 A 解锁。

## 守卫
- search_plan 存在 → 行为不变（现有测试不得回归）；
- search_plan=None + 无确认投影 → 仍拒绝（错误文案不变）；
- 新增回归测试：from_zero 旅程（search_plan=None）+ 确认投影匹配 → 门通过且
  retained 范围来自冻结 prep 批次；
- 红线：不动 immutable 行；K3 重放用“关联原 job 的新恢复尝试”语义（§5 已批），
  不扩 max_attempts；项 attempt 已 7，若项级硬顶挡路带证据升级。

## 关联
- 26 项根因修复（同族第一例）见 entry_diag.md 与本日工作流台账；
- K3 重放须等本修复 + 后端重启 + 指纹验证后执行。
