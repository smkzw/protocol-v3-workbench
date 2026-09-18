# Protocol v3 接回审阅与计划优化

时间：2026-09-12；当前owner：Codex。

## 合同
用户授权：完整工程code review、必要验证、细化设计/Plan/Goal prompt。此次不恢复3R.4产品构建，不调用产品模型/OCR/翻译，不启动live或修改运行库；允许隔离检查、工程审阅worker、新审阅证据和文档修订。
当前源：20260912 3R.4交接/暂停、现源码、Trellis、Plan v2及附加修订、源DOCX、最新全局AGENTS；旧总结只作证据。
方式：execution-plus-conference。后端与前端审阅可独立产出证据，Codex负责模板/语义/跨层与计划整合；成稿后由fresh reviewer挑战关键结论和路线，避免把上次交付者自评当验收。
允许写：本review task、runs/mw_protocol_v3_full_review_20260912、新的review/design/plan/goal文档及必要索引；诊断脚本与输出只写新runs目录。产品源码、已有tests/fixtures/历史证据、live、外部SOP、plan-upgrade只读。

## 执行列表
- [x] 读取最新全局AGENTS与最新交接/暂停；正式Goal仍paused、旧objective未随ZCode更新。
- [x] 当前源码/模板/验收血统重锚定与全量模块审阅。
- [x] 后端、前端独立审阅；主owner章节/依赖图/模板源复验。
- [x] 必要现有测试、定向真实反例与跨层路径核验。
- [x] 综合review：可复现问题、已完成范围、未完成产品功能与科学语义缺口。
- [x] 新设计/实施修订、可执行任务拆解和精简Goal prompt。
- [x] Fresh review、修正文档、文件/链接/状态核验。

## 提问与暂停
已批准的20/5、纯安全工程排除、PyMuPDF个人使用、工程subAgent、1R.4兼容语义不重复问。只询问实质用户取舍；本回合完成review与文档后交付，不冒标产品阶段完成。

## 重要初查
HEAD=84488d3，8个新commit已确认。3R.3被上次owner声明111载体/558fixtures完成；这次检验源绑定与谓词是否支持该范围。3R.4是首交付、fresh未完成；旧GLM配额终态属于历史，不采用ZCode路线表覆盖Codex当前route。


## 本轮交付结案（产品暂停保持）
审阅/设计/Plan/Goal文档完成，用户已选择完整可用路径优先。父3R.4仍未验收且user_paused。
源码771文件hash保持、权威模板/旧批准文档hash保持；1860v3、18frontend、1Node及定向反例有证据。
两worker+fresh设计review已终态，具体意见由Codex按源码裁定；runner标签矛盾及同模型独立性限制见owner review。
已更新设计v1.4/Planv3/Goal文本与Trellis3R.4PRD/当前索引；旧Goal原文保存，原生Goal仍paused未改objective。
最终证据runs/mw_protocol_v3_full_review_20260912/final_verification.json。保留历史，无产品源码/原测试修改，无服务或产品调用，无清理。
下一实施动作：用户恢复后先重锚当前树，再3R.4A→B→C→D，进入Ⅱ/Ⅲ期V1完整路径；不要重派旧fresh或从1R.2开始。
