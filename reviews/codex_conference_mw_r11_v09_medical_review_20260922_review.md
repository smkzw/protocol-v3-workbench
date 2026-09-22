# Codex Conference Review: mw_r11_v09_medical_review_20260922

Date: 2026-09-22

## Verdict

**REVISE.** v0.9 是目前最诚实、最接近低负担审阅的全文候选：85/85 节覆盖，44 complete、1 decision_required、40 source_gap；两张探索性卡推荐“不设置”，唯一统计升级已恢复。剂量、人群、终点、访视和样本量没有 Critical 级冲突。但仍有四类 complete 正文超出项目事实，因此该工件不得整包进入用户审阅或 Word。

## Boundary Compliance

冻结工件 SHA-256 为 `d1e5ad959fd5cdce693e86f072ae39fff9a4056d1601320b86061bfa9d216820`，schema 为 `protocol_full_draft_artifact_v9`。产品生成实际使用 `opencode-go/deepseek-v4.1-flash:max`，22/22 批、attempt 1、无 fallback。独立审阅实际使用 `grok/grok-build/grok-4.7:high`，session `0384d0f2-205a-4a4b-9d9f-42a2e824631b`，单轮终态完成、无 fallback。审阅者只读工件和指定资料，没有修改或采纳。
Hermes workflow guard 负责会商边界、路由记录和 review gate；Codex 仍负责冻结工件核验与最终裁决。

## Participant Output Reviewed

已完整阅读 `runs/conference/mw_r11_v09_medical_review_20260922/evidence_single_object.md`。报告用结构化提取覆盖全部 85 节、44 节正文、40 个空缺口、2 张卡、264 个节级证据引用和 104 个持久来源绑定，并复核 v0.5 缺陷闭合。

## Conference Findings Accepted

Codex 直接核对工件后接受以下结论：

- §9.5 无来源写入“自第1天起采集”安全性数据；采集窗应由项目安全文件决定。
- §3.1 把源事实中的“治疗策略人群”改写为“估计目标采用治疗策略”，§2.4 又省略复合策略，跨章措辞不一致；唯一统计升级仍只显示在 §9。
- §7.3.1 把体格检查写入安全性终点，而已确认安全性终点只包含实验室、生命体征和 12 导联心电图。
- §10.3、§11.3、§11.4、§12.1–§12.4、§12.7 把公司方案语料写成本项目实施义务，并与父节 source gap 冲突。
- §4.5 的“约24周”和 §10 的“签署知情同意后进入筛选”属于较小但明确的生成措辞问题。
- 两张探索性卡各自可答、默认推荐“不设置”，但目的和终点可以交叉点选，后续应合成一张原子决定卡。

## Owner Decision

本阶段不再启动 v0.10 长任务，以便形成稳定、可供专家审阅的冻结基线。v0.9 不采纳、不写入 Word。下一阶段修复包按优先级：

1. 删除无来源安全性采集起点和体格检查终点句。
2. 估计目标四个相关章节共用一个统计决定，不由医学写作层改选策略；同时提示关键次要终点多重性和救援治疗定义未定。
3. 公司语料只能提供写作参照，缺本项目文件的运营、伦理和质量程序降为 source gap。
4. 将探索性目的/终点合并为一张原子卡，推荐“不设置”。
5. 修正组名、全身暴露、最长24周和知情同意起句，再生成 v0.10。

## Codex Independent Verification

- 冻结哈希、85/85、44/1/40、2 张决定、1 个 required、264 个节级证据引用、104 个来源绑定、22 个 AI run 均由 owner 脚本复核。
- 产品模型身份探针返回 `opencode-go/deepseek-v4.1-flash`，与声明一致。
- 受影响集中测试最终 `106 passed`；Python 编译与 `git diff --check` 通过。
- 首次扩展测试因缺少 `tests` 的 PYTHONPATH 未加载共享 fixture；纠正命令后暴露旧阶段断言未带当前 schema/证据链。测试已升版为使用真实当前工件合同，最终通过。没有修改产品门控或 expected 来掩盖产品缺陷。
- 本阶段没有浏览器或 Word 验收，因为 v0.9 医学审阅未通过且未采纳。

## Final Decision

接受 `REVISE`。v0.9 作为不可采纳的专家审阅基线保存；后续从 v0.10 生成规则修复开始，不重复检索、分诊、下载、OCR、翻译，也不重复已经终态完成的 v0.9 job。
