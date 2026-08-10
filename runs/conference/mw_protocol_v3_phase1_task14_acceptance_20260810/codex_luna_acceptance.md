verdict: NOT_READY

P0 findings: none

P1 findings:

1. StudyDefinition 高 revision replay 可被伪造状态绕过。
   `[study_definition.py:552](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/canonical/study_definition.py:552)` 在 `current.revision > result_revision` 时只检查同 aggregate、包含 `decision_record_id`，未验证真实结果哈希或完整 predecessor chain。探针构造 revision 3、伪造 facts、复制 decision IDs 后返回 `accepted=True`。

2. material hash 递归剥离合法事实路径 `revision`，导致不同 payload 不冲突。
   `[protocol_v3.py:124](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/packages/contracts/workbench_contracts/protocol_v3.py:124)` 与 `[hashing.py:101](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/canonical/hashing.py:101)` 会删除嵌套同名键；`fact_updates={"revision":"A"}` 与 `"B"` hash 相同，重放结果为 `replayed=True` 且保留 A，违反同 CAS identity 不同 payload 必须冲突。

3. 冻结事实值为 `None` 时可被覆盖。
   `[study_definition.py:654](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/canonical/study_definition.py:654)` 使用 `.get()` 并将 `None` 当作不存在。冻结定义中的 `{"picos.nullable": None}` 可被 accepted decision 改为其他值，未抛出 `FrozenFactOverwriteError`。

P2 findings:

- `FactProposal` 的声明类型是 `Any`；`_deep_freeze` 对 set 等其他可变对象原样返回。经 reducer 传入可变 set 后，调用者修改会反映到 proposal，未满足绝对的深层不可变/不别名要求。JSON dict/list 场景测试通过。证据：[document.py:419](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/canonical/document.py:419)。

P3 findings: none

P4 findings: none

关键不变量证据：

- CAS identity 正确绑定 decision ID、snapshot、expected revision：[hashing.py:113](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/canonical/hashing.py:113)；相关 CAS、重复重放、payload 冲突测试包含在 119 项通过测试中。
- Document reducer 对完整 document effect hash chain 做了校验：[document.py:946](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/canonical/document.py:946)。
- `study_definition_sha256` 使用 revision-aware hash，而非 material hash：[study_definition.py:608](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/canonical/study_definition.py:608)；对应测试通过。
- SemanticDocument 没有 `facts` 字段，block 只接受存在于 StudyDefinition 的 fact paths：[protocol_v3.py:685](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/packages/contracts/workbench_contracts/protocol_v3.py:685)、[document.py:923](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/canonical/document.py:923)。
- `fact_or_uncertain` 不创建 document revision，仅返回 proposal：[document.py:818](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/canonical/document.py:818)。
- canonical 包未发现 medical-monitoring、OCR、翻译、模型或服务调用；纯函数检查通过。

实际读取文件：

- `AGENTS.md`
- 指定 conference context
- 冻结 plan 与 approved design
- `protocol_v3.py`
- canonical 下 `hashing.py`、`study_definition.py`、`decisions.py`、`document.py`、`__init__.py`
- 三个 Task 1.4 测试文件
- `tests/__init__.py`（仅为解释 pytest 临时目录问题）

未读取任何 worker、manager、Codex 报告或推理。

实际执行：

- 三个确定性测试：`119 passed`
- `python3 -m ruff check --no-cache ...`：`All checks passed`
- 9 个目标 Python 文件 compile 检查：通过
- 冻结 plan SHA-256：与 context 中 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914` 一致
- git tracked diff：无；仅观察到目标实现/测试为 untracked，未修改文件
- 运行了上述 CAS、lineage、冻结 None、proposal immutability 只读探针

未验证项与剩余风险：

- 未验证真实 repository/event store 的跨进程 restart persistence；本次只覆盖纯 reducer 与显式 ledger。
- 未验证 API、UI、服务、浏览器、模型、OCR、翻译及未来端到端流程。
- 未执行安全性、权限、路径、symlink、TOCTOU、恶意输入或破坏性状态测试。

本结论仅覆盖 Protocol v3 Task 1.4，不代表未来端到端两轮 P0-P4 清零。
