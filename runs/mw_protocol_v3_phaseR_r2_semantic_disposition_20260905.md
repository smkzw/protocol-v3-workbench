# R.2：共享差异的语义处置

日期：2026-09-05。输入：runs/mw_protocol_v3_phaseR_20260905/source_drift.json（LIVE HEAD d2daef1d099b3fe6c3c5c0582a93022e06bf5168；隔离区 HEAD 3d6772f1014f2a86f96eb3dae4fd878c70a5251c）。源码观察，不是 live runtime 验收；未 import live app、未读取真实业务库。

## 基线身份与完整性

- mutable_source_baseline_20260809.json 是原隔离源基线的精确副本，SHA 32e274b47ec14a40f0bcaa280b4e8b81ccf06f61b3ee0c0606055d4d54f27d67。
- 按 R.2 原文，mutable_source_baseline.json 当前是 LIVE source-only supersession，与 live_source_observation.json 同字节；它不是当前隔离工作树快照，不能用于宣称隔离树与 live 一致。原 baseline_id/determinism 的历史断言仍在旧副本测试，未删改。
- 当前生产/QC Python 消费者检索：旧 authority 测试已指向历史副本；新 reconcile_source_drift 明确 LIVE/ROOT/HISTORICAL。未发现其他 Python 工具消费新文件为“隔离基线”。后续消费者必须检查 root/source_commit/observation_scope，不能只凭文件名。
- 隔离树当前观察为 isolated_source_observation.json（一次性时点证据，后续 Phase R 测试/文档添加不回写旧观察）。
- 差异 313：monitoring_protected 129、medical_writing_review 127、shared_manual_review 57。路径分类是初筛，不是作者归因；下面覆盖 23 个 shared changed 路径及其余差异处置。

## 23 个共享变更：逐项处置

| 路径 | 当前差异的含义 | 对 legacy/v3 接口假设的影响与处置 |
|---|---|---|
| AGENTS.md | live 增加 9 月路由与 Trellis 指令 | 不是产品 API；执行遵循用户指定的最新全局及隔离指令，不拷贝 live 指令 |
| README.md | monitoring R3-B/R3-C 边界、启动说明新增 | 不是写作产品完成证据；不合并 |
| frontend/package.json | live 未含隔离测试脚本/devDependencies/精确 engines；添加监查 synthetic 启动项 | 不覆盖隔离依赖锁和 test inventory；否则会丢已验收测试入口 |
| frontend/package-lock.json | 与上述不同依赖面对应 | 不使用 live lock 重装隔离依赖；无 runtime merge |
| frontend/src/App.jsx | monitoring 大块提取到 RouteOutlet，AppShell/根路由与风险跳转变化 | WritingPage 位于无差异中段；保留其行为。未来 6R/8R 只能补丁式挂载写作入口，严禁用隔离 App 整文件覆盖 live |
| frontend/src/styles.css | 仅新增 monitoring-product-active 下 topbar 隐藏规则 | 写作 CSS 无此次漂移；不为写作合并监查规则 |
| packages/contracts/workbench_contracts/__init__.py | live 新 workbook 类导出；隔离独有 v3 exports | 整文件合并会删除 v3 导出；后续仅显式 named imports，不把 workbook 变更误作 v3 schema 迁移 |
| packages/contracts/workbench_contracts/models.py | ListingSheetPayload 增加 source_headers/physical manifest/可选元数据 | v3 StudyDefinition/DomainEvent 合同不在此文件；真实 legacy listing 读取必须保留新增元数据而非旧 schema 重序列化丢字段，8R parity 前不得宣称兼容 |
| scripts/start_stable_backend.zsh | live 改 .venv/python、默认单用户身份 | 不执行或移植启动器；1R 用独立显式 composition 配置，不带入监查身份开关 |
| services/api/app/ai_gateway.py | 配置 expected_response_model 但响应缺 model 时新 fail-closed | 是跨子系统真实质量修复；1R.6 写作 identity 测试必须覆盖 missing/mismatch，不整文件移植，不启用 monitoring 配置 |
| services/api/app/ai_role_runtime_settings.py | 新监查主分析/独立核对 roles，依赖 monitoring mapping_gate | 不得以共享 roles 的默认值替代写作 v3 registry；GLM 写作按用户独立配置解析 |
| services/api/app/ai_runtime_settings.py | 新 zhipu preset 与 key 环境别名，引用 monitoring 包 | 凭证“同来源”不等于 runtime import monitoring；1R.6 仅在内存解析已授权 binding，禁止复制 key/日志 |
| services/api/app/listing_file_parser.py | source_headers、多行 header、工作簿物理证据、公式缓存缺失等扩展 | 涉及真实源数据解释，不是无害字段增补；本轮不改/不合并。后续 legacy read 以已注册源快照读取，不重新解析重建历史事实；需要新 source format 时另做契约映射 |
| services/api/app/main.py | 390 additions/5 deletions：监查 admission/双模型/文档权威/R5-R7 wiring、单用户 middleware、synthetic 项目 | 写作路由主体未变；无法整文件替换。1R.2 在隔离 composition 追加默认关闭工厂；8R 对 live 当前 HEAD 再锚定后手术式接入 |
| services/api/app/paddle_ocr_adapter.py | submit code 非零作为明确拒绝，不混为 unknown | 写作未来复用时需保留“明确拒绝”与“提交结果未知”区别；不得顺带沿用监查的自动 fallback 决策；本轮不重跑 OCR |
| services/api/app/source_content_validation.py | 仅 protocol 角色检查适应症/方案版本；IB/SAP/eCRF 角色细化 | 旧“一种方案规则适配所有文件”假设不再成立；4R source role adapter 要按 role+版本映射，未知角色拒绝，不重写旧校验回执 |
| services/api/app/source_intake.py | registry 从 append 改受锁 transaction/atomic replace；监查 promoted 元数据可替换；locator/权威回执新增 | **不能假设 live JSONL 只会尾部追加或 mtime=版本**。未来 legacy read 必须读取一致文件快照并按内容 hash/项目/locator 固定，不以字节 offset 增量充当 canonical；禁止调用 live append/register。当前 legacy mapper 仅处理传入记录，未接真实 reader，H-R 不授予 cutover |
| tests/test_ai_role_runtime_settings.py | 新监查角色断言 | 监查 owner 测试，不移植或改 expected |
| tests/test_frontend_safety_projection_contract.py | 风险跳转改产品 RouteOutlet 参数 | 监查/安全链接合同，不合并；8R 挂载需零回归 |
| tests/test_listing_file_parser.py | 增加原始 label 和 semantic code 同存断言 | 佐证 parser schema 漂移；不能删除 source_headers |
| tests/test_paddle_ocr_primary_fallback.py | provider 非零拒绝/不 poll、fallback 用例 | 写作只继承拒绝分类需求，不视为用户授权切 OCR 模型 |
| tests/test_source_content_validation.py | 空 eCRF 不强制 STUDYID | 佐证 role-specific 语义；不改写隔离旧预期 |
| tests/test_source_registry.py | transaction rollback、并发不丢写、无 validation 拒绝、坏 promoted 回执不回退 | 佐证实际 registry 行为变化；读取时保留回执、不把“新可读结构”当医学准入通过 |

方法：逐项 git --no-pager diff --no-index；大文件结合全部 diff hunk 位置、关键变更函数与调用方检查。未对 monitoring 实现做临床或生产正确性裁定。

## 其余差异

- shared 的 34 个单边文件：pnpm 文件、监查 synthetic __main__、浏览器只读脚本、mm_c* 测试、d07–d10 oracle/fixture 工具归 live 工程；隔离独有的旧监查 UI 测试及 real IBDQ fixture 保留。均不复制、不删除、不运行真实数据流程。
- 129 个 monitoring_protected：全部保留所属工作区原样，不合并、不验收监查产品。
- 127 个 writing 分类中唯一双边 changed 是 tests/test_medical_writing_study_schema.py：live 直接 import records 中的旧真实脚本，隔离使用已抽出的纯 fixture。**保留隔离纯 fixture**，避免测试导入旧 runs/records 脚本潜在副作用。其余为单边 v3/工程文件，不能解释为 live 已有 v3 产品。

## 当前门结论与后续门

R.2 语义处置已完成为“不合并；显式登记未来 reader/挂载风险”，不是“313 项全部等价”。当前仅 source-only 重锚定可进入独立 H-R 复核；1R/P1R/8R 仍分别要求产品存储、隔离 composition、真实快照 parity、备份恢复和用户 cutover 授权。

本轮声明差异：R.1–R.3 的 QC/fixture/test 文件，以及当前 task ID 下的 context/plans/prompts/reviews/metrics/conference/runs/logs 证据。后者属于用户要求的独立工程审阅/计划更新，不是未声明产品改动；保留而非清理。产品 services/api/app、frontend、packages/contracts、monitoring 路径本轮零修改。
