# Codex Conference Review: mw_r11_v08_medical_review_20260922

Date: 2026-09-22

## Verdict

**REVISE.** v0.8 已关闭三套安全窗、DLQI 冲突日程、伴侣妊娠/新生儿推断和 21 个空 required 壳，但把方案概要误判为缺资料，把疾病背景、盲态人员、AE 定义和多项项目实施规则误标为 complete，并漏掉唯一应保留的统计升级。因此该工件不得采纳或进入整体用户审阅。

## Boundary Compliance

冻结工件 SHA-256 为 `767923242f5cc7ca95837e67a68322990a14b2b7a1512793ccf0ce9023259133`。产品生成实际使用 `opencode-go/deepseek-v4.1-flash:max`；独立审阅实际使用 `grok/grok-build/grok-4.7:high`，无 fallback。审阅者只读检查工件和指定资料，没有修改源码、运行库或工件，也没有调用采纳接口。
Hermes workflow guard 负责会商边界、路由记录和 review gate；Codex 仍负责冻结工件核验与最终裁决。

## Participant Output Reviewed

已完整阅读 `runs/conference/mw_r11_v08_medical_review_20260922/evidence_single_object.md`。报告核验 85/85 节、70 complete、3 decision_required、12 source_gap、4 张决定卡、407 条证据绑定和 22 个 AI run，并逐类对照 v0.5、v0.7 缺陷。

## Conference Findings Accepted

- 剂量、疗程、访视、终点、样本量及统计数字没有出现第二套冲突值。
- §1 已有足够已确认设计事实，不应因运营细节缺失而整章留空；§2.1 缺流行病学、疾病负担、指南和治疗现状来源，不应标 complete。
- §8.2 已承认 AE/SAE/TEAE 定义缺失，§8.2.1 却自行写入通用 AE 定义；§4.4 也自行指定盲态人员范围。
- 估计目标源事实同时出现“治疗策略”和停药/救援按“复合策略”判无应答，必须保留一个统计专业升级口，不能以零 required 隐藏。
- 允许/禁止合并用药两张卡在救援治疗尚未定义时可能与估计目标冲突；探索性卡缺少“不设置”选项。
- §5.5、§6.3、§6.4、§7.1.3、§8.3、§11.5 等章节仍用通用或条件性句子伪装完成；CMS-D017 公司语料也不应作为本项目 AE 规则的直接证据。

## Owner Repair Decision

不修改冻结工件，生成器升为 v0.9：

1. 决定卡字段收窄为探索性目的与探索性终点，并强制包含“不设置”；合并用药、救援、避孕和安全时限等缺项目来源时返回 source gap。
2. §1 必须从确认设计事实形成可用概要；§2.1、剂量调整、计划外访视、药物过量、试验药管理、AE/SAE/SUSAR、具体药物风险和保险赔偿缺对应项目文件时不得标 complete。
3. 禁止自行写入盲态人员名单、通用 AE 定义及由访视/排除标准推导出的安全日程或妊娠规则。
4. §9 同时出现复合策略时保留一个 required 统计升级；高影响事实在设计摘要统一核对，不恢复章节级空确认。
5. 决定卡确认前正文保持为空，同一研究字段只能由一个指定章节承载。

## Codex Independent Verification

Codex 直接核对冻结工件统计、路由回执和审阅报告，并将 v0.9 的集中受影响测试一次性运行：90 passed。真实 v0.9 工件和后续 fresh 医学会商另行验收；本结论不代表 Word、浏览器、统计、PV、运营或申报验收。

## Final Decision

接受 `REVISE`。v0.8 保留为不可采纳历史工件；后续仅依据新逻辑键生成 v0.9，不重复上游检索、分诊、下载、OCR 或翻译。
