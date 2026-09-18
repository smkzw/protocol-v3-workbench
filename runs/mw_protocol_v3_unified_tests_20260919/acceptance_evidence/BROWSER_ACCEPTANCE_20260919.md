# 医学写作子系统 ego(lite) 实浏览器验收记录 — 2026-09-19

## 环境
- 隔离后端 :5274（`runs/mw_protocol_v3_unified_tests_20260919/start_browser_backend.sh`，独立SQLite `browser_acceptance.sqlite`，`WORKBENCH_PROTOCOL_V3_PRODUCT_PROFILE=deepseek`，不触live/8910）
- vite :5175（既有进程，代理→5274），ego(lite) TaskSpace「医学写作验收走查」p1
- 模型回执证据：observed_provider=deepseek / observed_model=deepseek-flash / reasoning=max（事件流raw_response内）
- 数据库快照备份：/tmp/browser_acceptance_pre_clean.sqlite

## 已验证链路（全部真实模型，ego实浏览器点击）
1. **资料整理 intake**：brief（667字，含操作性定义）→ run `research-intake:6584a21e…` real deepseek → ready_for_review，12字段
2. **研究上下文绑定**：study `study:v3:97f28c85…` inputs update（CAS expected_revision链 6→…→12），matches_selected_inputs=true
3. **设计要素建议**：页面点击「生成设计要素建议」→ run `design-elements:62e9482d…` real deepseek → **ready_for_review、零未决问题**；NI/期中在优效+无期中设计下正确置空
4. **三卡确认（objectives-endpoint / estimand / sample-size）**：ego逐卡点击「确认本卡片内容」→ 全部成功，零报错；每卡显示「当前研究已保存本卡片内容；研究信息变化时会提示重新核对。」（确认双绑定语义）；study revision 随确认递增
5. **证据截图**：acceptance_evidence/02_design_cards_before_confirm.png、03_design_cards_confirmed.png

## 本轮发现并修复的缺陷（均有测试佐证）
| # | 缺陷 | 修复 |
|---|------|------|
| 1 | design生成指令缺status契约：模型可返回 ready_for_review+questions（schema拒收，correction仍失败→UI显示空问题） | DESIGN_INSTRUCTION 增补 status 规则 + questions 仅限缺失输入信息、输入已给值按recommendation采纳（design_elements.py） |
| 2 | DesignElementsCards StrictMode双挂载：cleanup置 alive=false 不恢复 → poll永不setState → 卡片区空白 | 挂载effect恢复 alive.current=true |
| 3 | 卡片确认CAS链断裂：elements GET不携带study revision/snapshot，UI `??0`兜底必409；确认后state不随receipt更新 | GET增 `?study_definition_id=` 富化 expected_revision/snapshot_sha256（design.py）；confirmCard用receipt.revision/revision_sha256回写state；api client传参 |
| 4 | prepare发布expected id早于start提交：poll首GET 404即永久放弃 | poll对404有界重试（≤40次退避） |

另：设计卡intent缺`card`字段（schema必填）——由VALIDATION_PROBE临时探针定位后修复（intent加`card`，探针已移除）。

## 决定性发现：设计要素→初稿之间的"章节事实确认"阶段未建
- manuscript-plan 门：72适用章全部 needs_information，共缺 **350个章节级事实**（ae.*/statistical.*/visit.*/appendix.* 等），另有39章条件适用性未决；`all_applicable_inputs_ready=false` → 「生成完整初稿」禁用
- 服务端 `prepare_study_chapter` 使用同一绑定（bind_applicable_chapter），缺事实同样阻断
- 契约/绑定无默认值机制；study侧亦无任何环节写入这些路径（framing.*/document_control.* 属旧authoring journey事实空间）
- **结论**：goal（2026-09-13）所列"七类剩余推荐"中的章节事实提案/确认流是设计卡与整稿生命周期之间的下一建设阶段；本验收推进至该边界面属预期前沿，非缺陷回退
- 量化输入：/tmp/plan.json 快照（缺失路径并集与每章计数已留存）

## 遗留
- 2个既有失败待owner裁定：fact_labeled_impact alias方向语义、v2_v3 verifier隔离脆弱
- fake-opener事故已清理：f306b587 键的事件/reservation全部清零（内容寻址artifact无残留），教训：禁止对产品库跑fake transport脚本
