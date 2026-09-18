# 当前研究/来源上下文衔接：独立审阅合同

Owner为Codex。本单元是Protocol v3先打通Ⅱ/Ⅲ完整可用路径的中间工程，当前仍没有整稿/Word接受。遵循plans/mw_protocol_v3_implementation_plan_v3_20260912.md、design v1.4及最新用户决定；纯安全专项排除，科学/类型/数据不丢不重复/真实交互仍要求验证。不得将旧流程门作为暂停点，不改产品或任何历史日志/expected/fixtures来造通过。

## 审阅对象
读取runs/conference/mw_protocol_v3_research_context_review_20260913/artifact_manifest.json中完整受影响定义与对应测试/依赖；App.jsx仅需实际ProtocolIntakeWorkspace挂载行及相关actor约定，不为读全文件消耗上下文。API当前读取已有StudyDefinition，创建仅research.input_context；活动资料更新通过显式操作/CAS，来源或seed变化可使旧给药输入绑定stale。给药fresh采用比对当前资料和原prepared，保存producer run/input/output/source_context；原操作先lookup保留后继。前端StudyContextWorkspace创建/选study/更新/重开，App actor沿现有medical_manager个人工作台角色，不冒称实名或医学批准。

## 必须挑战
1. 实际source_intake和seed/output身份覆盖，missing/source drift/错误study不误采用，原引用保留。不要只因有hash就判完整。
2. 当前study发现/创建的并发与重开，多个study不静默误选；确定未执行vsUNKNOWN不重派，实际方法调用/返回体/StrictMode/切project/seed不误标成功。
3. 资料变化的current/stale/unverified与历史回执严格分开；后继不回退；创建baseline不采用医学候选或默认10mg。
4. 新通路与现有apply/lookup及旧阶段兼容。不要把真实needs_information旧参考run自动采用。

## 有限范围与待办
RecommendationOption与ClaimEvidenceLink实体、picos同源投影、当前有效性UI、其余7类决策/全章节/Word未完成，不能算已通过。设计模型目前读取source/seed，没有加入当前StudyDefinition医学事实；若该边界在本路径产生具体缺陷，请给可复现影响和分阶段修复，不把真正科学依赖改名安全后排除。run未按唯一study id登记，fresh采用依赖显式目标及source context相等；请挑战其充分性。

## 可用证据和可写范围
Owner实际浏览器限定证据runs/mw_protocol_v3_v1_1_20260913/browser_functional/context_browser_verification.json、context_after_adoption.json、context_before_browser.json。source/seed/design是预存合成fixture，各fake1次，无真实模型；浏览器仅3次关联/找回/采用及刷新，并非全路径≤20点击。不要让计数或owner摘要代替你的源/反例核对。
只准写runs/conference/mw_protocol_v3_research_context_review_20260913/scratch/，可运行临时SQLite/fake transport反例；原scratch、产品、live、监查、8910、其他runs不可写。不得新服务/浏览器/产品模型/OCR/翻译/清理/递归派发/联网研究。真实浏览器最终验收归owner，无法做要如实说。
使用既有runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python；PYTHONPATH=services/api:tests:tests/protocol_v3:tests/protocol_v3/integration:.；vitest从frontend目录运行React配置。hash初终核，报告实际命令/结果/范围与具体行。返回完整中文Evidence/Inference/Recommendation/Uncertainty，有限接受与未决分别列清，runner保存，不直接写report。
