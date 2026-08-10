继续同一独立验收 session，复核你首轮 NOT_READY 的全部问题及其共同根因。保持只读；不得修改文件。

Hard boundaries:
- 只在当前工作区内读取和运行确定性功能检查。
- 不得修改文件，不得启动服务、安装依赖或调用浏览器、模型、OCR、翻译。
- 禁止安全性、渗透、恶意输入、权限、路径、symlink、TOCTOU、破坏性状态测试。
- Runner-managed report path: `runs/conference/mw_protocol_v3_phase1_task14_acceptance_20260810/codex_luna_acceptance_round2.md`. Never write this path with tools; return the complete report and let the CLI adapter persist it.

Initial read set:
- `context/mw_protocol_v3_phase1_task14_acceptance_20260810_conference_context.md`
- `packages/contracts/workbench_contracts/protocol_v3.py`
- `services/api/app/protocol_workflow/canonical/hashing.py`
- `services/api/app/protocol_workflow/canonical/study_definition.py`
- `services/api/app/protocol_workflow/canonical/document.py`
- `services/api/app/protocol_workflow/canonical/__init__.py`
- `tests/protocol_v3/test_study_definition_reducer.py`
- `tests/protocol_v3/test_decision_cas.py`
- `tests/protocol_v3/test_semantic_document_reducer.py`

必须重新运行你首轮的四个复现探针，而非只看新增测试：
1. 伪造更高 StudyDefinition revision、复制旧 decision ID、断开 predecessor hash chain，必须 fail closed；
2. `fact_updates={"revision":"A"}` 与 `{"revision":"B"}` 必须得到不同 exact payload hash，并在相同 CAS identity 下冲突；模型 material hash 对嵌套同名事实键也必须不同；
3. frozen/confirmed facts 中已有值 `None` 时，替换为非空值必须抛出 FrozenFactOverwriteError；
4. FactProposal 传入 set 等非 JSON 可变值必须 fail closed，不能保留别名。

另外核对主会场主动补强：
- StudyDefinitionV3 facts 顶层、嵌套 dict/list 均不能原地修改，且 model_dump(mode="json") 无 serializer warning、JSON 形态不变；
- DecisionEffect/DocumentEffect 及其 ledgers 不得被原地修改或替换既有 effect；
- StudyDefinition 与 SemanticDocument 的 later-descendant replay 都逐级验证 effect revision hash chain；
- 既有合法 replay、文档投影、fact proposal、Ruff、编译和聚焦功能测试没有回归。

复跑三个 Task 1.4 测试（warnings-as-errors）及你认为必要的只读功能探针。最终仅给 READY 或 NOT_READY，逐项关闭或保留首轮 P1/P2，列出命令、证据、剩余风险，并再次注明仅覆盖 Task 1.4，不等于未来端到端两轮 P0-P4 清零。
