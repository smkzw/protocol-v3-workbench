# DC-018 不可变决策记录

decision_record_id: `DC-018`
decision_status: `approved`
user_approval_date: `2026-08-09`
accepted_candidate_commit: `2a4837e24a0cb71129fbd3f1e8672b8f9e6e8323`

## 权威输入与哈希

| 对象 | 路径 | SHA-256 |
|---|---|---|
| approved plan | `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md` | `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914` |
| design-v1.2 | `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md` | `321169afc9f33f572b803661b6c6eeb598304267fcb33cdf7de4faf0b00ad0d8` |
| approved decisions | `plans/mw_system_rearchitecture_design_decisions_20260808.md` | `04d99dd3cb239c49f5de52d1b0fe0fdd959007def509e0931907614894eb816a` |

以上哈希由磁盘文件在记录建立前重新计算，并与 Task 0.4 execution context 完全一致。

## 澄清范围

本记录只固化 approved plan 顶部的 DC-018 澄清：应用自有权威图、可替换调度器、LangGraph 首选方向及其事实源/选型边界；包括 P2-G2 通过前的候选状态、PoC 失败时 typed facade 的非发布证明边界，以及生产路线必须另行提交 design amendment 的停止条件。该澄清不扩大 Protocol 范围，也不把调度器候选宣称为已锁定的生产实现。

## approved plan 中的 DC-018 原文（逐字复制）

**DC-018（随本计划待批准的 design-v1.2 澄清）：** design-v1.2 已批准的是
应用自有权威图、可替换调度器和 LangGraph 首选方向；LangGraph 不是事实源，
须通过 P2-G2 才成为 selected adapter。若 PoC 失败，typed facade 只能用于
非发布证明，生产路线须另交 design amendment。用户批准本计划即同时批准此
澄清；实施后将其写入独立不可变 decision record，不长期只靠本计划覆盖设计正文。

## 不可变性规则

- 本记录是 DC-018 的独立不可变 decision record；后续比较器必须以本记录及其
  哈希字段作为独立证据，不以重新解释 approved plan 代替。
- `design-v1.2` 文件本身保持原字节不变；本 Task 0.4 不修改、重写、格式化或
  追加该文件。
- 若 LangGraph PoC 未通过，typed facade 只能用于非发布证明；任何生产路线变化
  必须先形成 design amendment 并取得新的用户批准，不得静默覆盖本记录或
  design-v1.2。

