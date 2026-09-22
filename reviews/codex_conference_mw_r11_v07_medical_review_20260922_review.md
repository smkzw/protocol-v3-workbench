# Codex Conference Review: mw_r11_v07_medical_review_20260922

Date: 2026-09-22

## Verdict

**REVISE.** v0.7 已把决定项从 73 个降为 4 个，待决定正文保持为空，7 个明确来源缺口也均未用通用文字填充；但部分缺失的项目实施规则被写入 `complete` 正文，且 21 个 required 章节没有任何可确认卡片，因此不得采纳或进入面向用户的整体审阅。

## Boundary Compliance

冻结工件只读，SHA-256 为 `e199d57fd14d6d78ea630e02bdc8ba20592f01dc06233f4fd83d32f41c1a99ce`。产品生成实际使用 `opencode-go/deepseek-v4.1-flash:max`；独立审阅实际使用 `grok/grok-build/grok-4.7:high`，无 fallback。审阅者没有修改源码、运行库或工件，也没有调用采纳接口。
Hermes workflow guard 负责会商边界和报告门控；Codex 仍对冻结工件、医学结论与最终 verification 负责。

## Participant Output Reviewed

已完整阅读 `runs/conference/mw_r11_v07_medical_review_20260922/evidence_single_object.md`。报告按结构化脚本覆盖 85/85 节、4 个决定项、7 个来源缺口、22 个唯一 AI run，并复核 v0.5 的既有缺陷是否关闭。

## Conference Findings Accepted

Codex 直接核对冻结工件后接受以下关键结论：

- 数字事实层未发现与 StudyDefinition r8 冲突的另一套剂量、样本量、终点、访视或分析数字。
- v0.5 的预确认正文、73 张重复卡、SUSAR“转归”定义和错误字段路径已明显改善。
- v0.7 仍把访视日推断为全套安全性检查日程，把 TEAE 窗、伴侣妊娠/新生儿随访、DLQI 时点、依从性访视和研究结束定义写成未确认规则。
- `治疗策略人群` 与停药/救援按 `复合策略` 判为无应答的源事实混用仍未得到统计专业处置。
- 21 个 required 章节全部没有决定项，4 个真实决定项却位于 standard 章节；“请逐卡确认”与实际可操作对象不一致。
- 合并用药两张卡推荐的是清单写法而非可执行医学边界，不能安全预选。

审阅者将证据绑定计为 469 条；会议上下文中的 218 来自前一版统计口径，已判定为上下文误写。v0.7 的 `evidence_bindings` 与逐节 `evidence_span_ids` 实测均为 469，后续记录采用该值。

## Owner Repair Decision

不手工润色冻结工件。生成器升为 v0.8：

1. 禁止由访视日推断实验室、生命体征、心电图、体格检查或依从性日程；禁止自行定义 TEAE 窗、DLQI 时点、研究结束、伴侣妊娠或新生儿随访。
2. `complete` 必须是可直接入方案的句子；“本章需要覆盖/本节应列明”等范围说明不能冒充正文。
3. 决定选项必须是点击后可直接写入字段的具体、互斥答案；来源不足时返回 source gap，不能用“按类别列出”冒充科学选择。
4. 已确认高影响事实只在合并设计摘要统一核对，不再把每个复述章节都设为 required；跨项目语料只生成适用性 advisory。
5. 统计分析中同时出现治疗策略与复合策略时保留一个明确的 required 统计升级口。
6. 对已识别的未支持具体规则增加确定性降级，避免模型重复输出后直接进入 complete。

## Final Decision

接受 `REVISE`。v0.7 保留为不可采纳历史工件；v0.8 必须完成同产品路由真实重跑、owner 逐节核对和 fresh 独立医学复核，才可决定是否进入用户审阅。此结论不代表 Word、浏览器、统计、PV、运营或申报验收。
