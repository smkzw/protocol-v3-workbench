# Codex Conference Review: mw_r11_v05_medical_review_20260922

Date: 2026-09-22

## Verdict

**REVISE.** v0.5 的事实覆盖与证据绑定质量较高，但决定治理层存在系统性缺陷，不得进入采纳或面向用户的整体审阅。

## Boundary Compliance

审阅者仅只读检查冻结的 v0.5 工件、StudyDefinition 摘要、临床内容合同与任务标准；没有修改源码、工件或运行库。产品生成模型为 `opencode-go/deepseek-v4.1-flash:max`，审阅实际使用独立的 `zcode/zcode/GLM-5.3-Flash:max`，避免同模型自审。
Hermes workflow guard 仅负责会商边界与报告门控，不替代 Codex 对原始工件和医学结论的最终核查。

## Participant Outputs Reviewed

已完整阅读 `runs/conference/mw_r11_v05_medical_review_20260922/evidence_single_object.md`。报告核对 85/85 节、73 张决定卡、367 个章节证据绑定，并给出逐节可审阅范围与优先修复顺序。

## Conference Panel Review

独立审阅确认：正文与 StudyDefinition r8 未发现数字级矛盾，13 个来源缺口均诚实保留；同时发现 5 类高影响问题：未确认推荐提前写入正文、同一路径重复或冲突卡、已确认事实字段被运营问题误用、估计目标源事实本身术语混用、SUSAR 定义缺少适当依据。73 张卡也明显超过目标用户的点击预算。

## Main-Venue Codex Review

Codex 复核原始工件并逐项统计全部决定卡的 `fact_path`。审阅者关于 `design.open_label_extension` “不存在”的表述需收窄：该路径在现有 `SUPPORTED_ADOPT_PATHS` 中存在，但当前项目并无适合让章节卡写入的未确认值。其余核心发现均被源码与工件直接支持。Codex 裁定 Q2/Q3 无需再问用户：推荐预选不等于确认；非医学运营决定不得占用医学写作者点击。估计目标混用保留为统计专业决定，不在正文层静默改写。

## Codex Independent Verification

冻结工件 SHA-256 为 `a9731b65bf919ac83cb32da94b16fae6a24e857c08df39d6a83cb8b1d6c59c40`；章节、证据与 AI run 对账见同轮阶段记录。此次为医学内容会商，未把尚未修复的 v0.5 浏览器呈现当作验收。随后 owner 已实现 v0.6 决定合同：只允许仍未确认且语义明确的少量整字段决定；每字段只由一个章节承载；待决定正文为空，确认后才重写；确认瞬间再次检查字段仍未确认。集中回归 120 passed。

## Final Decision

接受独立审阅的 `REVISE` 结论。v0.5 保持不可采纳历史证据；v0.6 需通过真实产品模型重跑、同类医学复核和浏览器呈现核对后，才能进入用户审阅。模板是否增加独立 §3.2/参考文献节点继续作为模板权威问题保留，不阻断当前工程修复。
