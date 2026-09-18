# 1R 接线前独立准备与旧链反例

主执行所有权，不与worker_01的storage/sqlite.py、selected.py和两份测试重叠。无live或monitoring修改，无服务或产品模型调用。

- Homebrew Python3.12.13链接SQLite3.53.4；旧candidate3.53.1仅历史证据。原环境缺cryptography/fitz/pypdfium2。
- test_runtime_directory_configuration.py实测1failed，子进程stderr定位main→ai_gateway→ai_runtime_settings缺cryptography。
- uv venv以Homebrew3.12新建本目录venv；uv pip install --require-hashes -r services/api/requirements-protocol-v3.lock成功，38包，未改requirements/全局/live环境。原始安装结果在主会话工具回执；该环境不是已验收产品环境。
- 再次运行原运行目录隔离用例并查看子进程stderr：main→listing_file_parser.py:12缺xlrd。未把捕获异常后shell0当测试PASS。
- AST静态扫描main依赖闭包183模块（包含可选/函数内import上界）：xlrd=listing_file_parser:12；fitz=writing_reference_ocr_consistency_service:9；pymupdf=writing_reference:2004/4212/4315与eligibility_raw_intake:569。没有import这些产品模块或调用OCR。
- 历史verify_toolchain_rebuild.py:79的import_probe_modules仅scripts.qc.protocol_v3.verify_toolchain_rebuild；原H4/H6并未覆盖真实main导入。

## 旧全文采纳反例

命令：PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api:packages:. runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python runs/mw_protocol_v3_1r_integration_20260905/reproduce_legacy_full_draft.py

结果：multiple_body_blocks→全文初稿采纳遇到正文变化sec_1，saved_before_error=[]；later_section_stale→全文初稿采纳遇到章节版本变化sec_2，saved_before_error=[sec_1]。每例fake_model_calls1，real_model_calls0。实际服务、真实tmp SQLite durable job和磁盘候选；repo保存为既有测试fake，故证明方法控制流与错误，不声称真实用户数据受损。

新链门要求已加入review_amendment；不改旧源码或旧负向测试。用户的旧链测试依赖选项待回复；1R.1继续。

## 旧UI与身份接线复核（13:51）

`node runs/mw_protocol_v3_1r_integration_20260905/reproduce_legacy_full_draft_ui.mjs`执行实际App回调，全部网络fake：A采纳响应晚于切换B时，B收到成功message/reload/busy三项回写；状态查询模拟网络失败后locator操作为saved→removed。脚本断言均通过，证明反例存在，不称UI回归已修复或浏览器验收通过。

准确限定部分采纳发现：App:10457已有逐章写入/冲突停止提示，并非承诺原子性；问题是异常路径没有已落稿明细和刷新/恢复回执。新链整稿任务采取文档级事务，逐章采用则必须明确部分结果。

新锁环境运行test_medical_writing_principal_acl.py、test_medical_writing_signature_adapter.py、test_medical_writing_artifact_rollback.py：24 passed in0.19s，JUnit=acl_signature_rollback.xml。这些是纯函数和tmp SQLite合同；rg核实main和v3 router没有调用require_medical_writing_authorization、execute_artifact_rollback或create_verified_signature_record；v3 mutation当前直接转发body.actor_type/actor_id。记录为接线缺口，未声称真实越权攻击成立；新链人审门须绑定可信身份，不扩建多租户系统。

同环境test_medical_writing_durable_jobs.py四类TestCreateDedupe/TestClaimLease/TestHeartbeat/TestCASCompleteFail共19 passed in0.81s；JUnit=durable_store_focused.xml。不运行历史真实任务；不把本地CAS安全外推为外部调用不重复。

reproduce_legacy_quality_false_positive.py：实际MedicalWritingContentQualityDetector把完整条件句“未提供书面知情同意者不进入筛选。”与“样本量尚待医学经理确认。”都标unresolved_draft_marker且approval_blocking=true。前者是合成分类反例，不是项目临床建议。旧test_ai_task_runner_accepts_a_source_bound_full_draft的正例仍是泛化正文；其通过只证明传输/浅层合同，不证明对应章节实质可用。3R/7R新增上下文负对照和逐叶事实义务。

UI复现脚本第三例：从useDurableMwJob.js读取实际startJob callback，复用实际durableJobState.mjs函数；启动时A，screenGenRef.current更新为B后完成A的fake202响应，B可见状态仍收到project_id=A/job-A。未运行React renderer，证明回调闭包与ref校验缺口；后续必须补真实hook渲染/切换测试。已更正review中对共享hook“已隔离”的过度外推，不改历史纯函数测试expected。

既有MedicalWritingContentQualityDetectorTests六个合成检测器测试6 passed in0.53s，quality_detector_focused.xml。未运行同文件真实Word fixture。14:03复核live git status仍为空，Plan v2和历史source baseline哈希仍匹配；worker的adapter/selection与两份测试已出现，仍未终态，不读取其报告作验收、不抢改。

`reproduce_legacy_full_draft_crash_window.py`使用实际full_draft方法和临时DurableJobStore，在模型返回后的chunk写入点注入SystemExit，模拟进程中断而不真kill。时钟前移601秒后实际recover_on_startup+claim，同job再次执行，fake_model_calls=2/real_model_calls=0。AiTaskRunner.submit_internal→_execute实际每次分配新run_id，全文chunk恢复不先查对应旧run。说明旧“已有chunk复用”合同不足以证明模型返回到chunk落盘窗口的去重；新1R.4/2R必须保留发送前占位及unknown对账。未对当前运行worker注入故障，未重跑历史任务。
# Additional export/entrypoint review (2026-09-05)

Further deterministic checks:55Phase0 native receipt schema tests passed0.04s (native_receipt_schema_contracts.xml), no producer/Word call. Actual React SSR repro reproduce_stale_preview_component.mjs first validates its exact synthetic payload via real MedicalWritingDocumentPreview, then bundles unchanged component in memory and renders static markup. Result: backend_contract_validated=true, stale heading=true, verified CSS tone=true, final-layout claim=true. Source28–49 prioritizes historicalWordbasis overstale; legacy2helpertests miss component composition. Current main does not visibly construct stale responses in inspected paths, so do not claim a reproduced live-user incident; contract-valid input mismatch is the proven defect. Initial local probe lacked required page dimensions; corrected before claiming contract validity, and final exact payload validation succeeds. No frontend product source changed.

Ran isolated locked-venv pytest on test_medical_writing_document_export_jobs.py, test_medical_writing_word_verification.py, test_medical_writing_word_verification_repository.py:15passed in1.48s, export_receipt_contracts.xml. Inspected tests before run: fake DOCX callback bytes, synthetic receipts, test-owned temporary SQLite, no Word/main/model call. These are contract checks, not native-render acceptance.

Read actual main Word endpoint9497–9562/9913–9974, models1972–2059, exporter6205–6275, receipt repository fully, and Phase0 word_receipt/contract.py + roundtrip_lineage.py fully. Legacy API recomputes supplied PDF pixel hashes but trusts external producer assertions; Phase0 already defines separate input/saved/PDF identity and stronger execution evidence. Carry that existing contract into7R.4; no new producer design required and no claim of a reproduced live exploit.

Entrypoint isolation preflight: main PROJECT_ROOT=Path(__file__).resolve().parents[5] points above isolated checkout; WORKBENCH_RUNTIME_DIR is mandatory for tests. Explicit inherited WORKBENCH_AI_SETTINGS_PATH, WORKBENCH_AI_ROLE_SETTINGS_PATH and WORKBENCH_ELIGIBILITY_ARTIFACT_DIR bypass that root and must also point to test-owned locations or be removed in a sanitized child environment. Read ai_runtime_settings.py/ai_role_runtime_settings.py source only; no real settings/secret material inspected. Main startup contains monitoring and writing recovery hooks; do not run TestClient lifespan unguarded. This preparation is read-only, not1R.2 implementation.
