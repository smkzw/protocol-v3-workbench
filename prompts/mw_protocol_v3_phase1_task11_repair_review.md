# Protocol v3 Phase 1.1 同会话修复复验

## Hard boundaries

- Continue the same independent-review session; read-only review only.
- Do not edit files or start services/model/OCR/translation runtimes.
- Do not run security, adversarial, permission, path, symlink, TOCTOU, malicious-input, destructive-state, or penetration tests.
- Runner-managed output path: `runs/codex_mw_protocol_v3_phase1_task11_independent_luna.md`. Never invoke a write/edit tool on this path; return the report and let the runner persist it.

Read these files only:

- `packages/contracts/workbench_contracts/protocol_v3.py`
- `tests/protocol_v3/test_contract_models.py`
- `runs/codex_mw_protocol_v3_phase1_task11_independent_luna.md`

复验你刚才定位的唯一 P1：`SourceArtifact` 父身份部分输入。实现者已经改为先拒绝 parent ID/hash XOR，再分别要求派生文件具有完整父身份、原始文件不得携带父身份；测试现在覆盖原始/派生两类对象分别只给 ID、只给 hash，以及完整派生身份通过。

实现者在可写的隔离测试环境重新执行了允许的功能检查：

- `tests/protocol_v3/test_contract_models.py`: 16 passed；
- `tests/test_medical_writing_study_schema.py` + `tests/test_medical_writing_document_session.py`: 42 passed；
- 两种原始文件单边父身份独立复现均被拒绝；
- `git diff --check` 通过。

只需核对修复是否真正关闭该 P1、是否引入同因回归，并给出 `READY` 或 `NOT_READY`。若 READY，明确此前只读沙箱无法执行 pytest 不否定由主验收者真实运行的 16+42 功能测试证据；若 NOT_READY，仅列仍存在的确定问题及行号。不得自行修复。
