# Conference Participant Output: mw_protocol_v3_1r4_contract_fresh_20260905 - general_single_object

## Boundary Check

- 角色按派工执行:`zcode/GLM-5.3-Flash:max`,独立代码设计审阅，未读取其他参会方输出，未启动会商，未联网。
- 三个冻结源哈希逐一复核通过：protocol_v3.py `928d2549…5799`、harness.py `263aae74…b44f`、document.py `e7529205…eca65`,与 context 声明完全一致。
- 产品源码与既有测试零改动。仅写入授权目录 `runs/mw_protocol_v3_1r4_contract_fresh_20260905/`(两个探针脚本，见下)。未写 runner 报告路径。
- HEAD 历史对比按授权仅对 `packages/contracts/workbench_contracts/protocol_v3.py` 执行 `git show`;harness.py/document.py 未取历史版本，以当前源码直接审计。
- 未触碰 SQLite/reservation 并行切片(storage/selected.py 等)、1R.5、模型/OCR/翻译/Word/live 调用与清理；未做全仓测试套件。
- 本报告为独立审阅证据，不主张任何最终验收权。

## Independent Work Product

**总体结论(评审立场)：Task1R.4 压缩实现与声明的验收边界一致，legacy 同一性经字节级证实成立，真实绑定点有效；发现 1 个低危设计观察(摘要域无模型身份)、2 个覆盖缺口建议、3 个文档级残留，均不构成阻断。** 依据如下。

### 1. 实现结构(证据：当前源码通读 + HEAD diff)

`git diff` 显示改动最小且纯增量：新增 `DependencyBoundModel` 基类(protocol_v3.py:260-311),四个类型(`SemanticDocumentRevision`/`ChapterLockSnapshot`/`NodeExecutionContract`/`SubmissionEvidencePackage`)改为继承并声明各自 `dependency_field`;依赖字段从 `Annotated[tuple[Sha256,...], Field(min_length=1)]` 改为默认 `()`,非空与唯一性校验移入基类 `validate_dependency_binding`。v1 路径要求"有非空元组且无摘要”，v1_1 路径要求“有摘要、若元组存在必须与摘要一致"，通过后用 `object.__setattr__` 在构造期清空元组(验证期归一化，非事后变异)。`@model_serializer(mode="wrap")` 对 v1 弹出 `dependency_sha256`、对 v1_1 弹出原始元组，保证两种版本的持久化字节各只含一种表示。`_material_value` 对应地让 v1 材料载荷含原始元组、v1_1 含摘要，任一版本材料载荷都恰好含一种依赖表示——这是“顶层 material hash 绑定该摘要”的正确实现。

### 2. Legacy 字节/哈希同一性(证据：探针 probe_general_single_object.py,与 HEAD 模块同进程对比)

对四个类型各构造同一 v1 payload,分别用 HEAD 模块与当前模块实例化:`model_dump_json()` 字节相等、`model_dump()` 字典相等、`material_sha256()` 相等，4×3 项全部通过。`schema_version` Literal 对非依赖模型未放宽；wrap serializer 弹出的键恰好是新增键，字段顺序无扰动。既有测试另固定了四类 legacy 材料 hash 锚点(如 `44678e0c…`、`580a1f5b…`、`062fff6d…`、`7e0670d3…`),在我运行中全部复现。结论：**"raw v1 model_dump 与 material hash 不变”成立，且有双层证据(HEAD 对比 + 测试锚点)。**

### 3. 真实 harness 绑定(证据：harness.py:777-803 + 探针 probe_replay_harness.py H1-H6)

`_validate_artifact_binding` 通过 `node_contract.matches_dependencies(passed_hashes)` 实现 v1 元组直比 / v1_1 摘要重算双路匹配;`build_request` 后的 dispatcher 复验(`_request_matches_binding_evidence`)对压缩合同同样生效。探针证实：v1_1 合同可端到端 build→revalidate→物理 dispatch;build 后篡改 artifact 在复验处 fail-closed;重复 ref、缺项、乱序、替换、重复哈希均被拒。绑定语义未被压缩放松。

### 4. 文档 reducer 与回放(证据：document.py:1035-1065, 1119-1145 + 探针 R1-R9)

`_build_revision` 以 `revision.schema_version == current.schema_version` 决定是否 `compact_dependencies()`——v1 链保持 v1,v1_1 链保持 v1_1,新修订按 apply 时传入的章节哈希重新绑定摘要，源对象零变异，ledger 仍 append-only(`with_effect` 返回新账本)。回放语义：同一 CAS 三元组 + 同一原始元组 → 幂等返回 `current` 本体；同 CAS + 变更元组 → `DocumentPayloadConflictError`(payload hash 由调用方原始元组计算，与表示版本无关)。快照哈希 `document_revision_hash` 含材料 hash,而材料 hash 对 v1_1 含摘要——伪造摘要即改变快照链，无法冒充原修订。同一内容 v1/v1_1 的修订哈希不同，符合"新 canonical hash 明确版本”。

### 5. “真删除冗余表示还是只加无人调用的类”(证据：产品代码 grep)

产品代码中 `compact_dependencies` 唯一调用点是 document.py:1064;`matches_dependencies` 唯一调用点是 harness.py:795。即：**四类中两类已真实接线**(SemanticDocumentRevision 经 reducer 继承、NodeExecutionContract 经 harness 匹配)，**两类(ChapterLockSnapshot、SubmissionEvidencePackage)当前只有能力与测试、无产品调用方**；且不存在任何产品路径引导出第一个 v1_1 实例(首实例只能来自对已存在 v1_1 current 的继承或存储回放)。这与修订计划的自我声明一致("2R.1 typed facade 显式采用为下游要求;当前实现和测试不等于此后接线或全1R.4验收完成”),属诚实范围声明而非虚报完成。v1_1 实例的表示压缩本身是真删除(v1_1 持久化字节与内存均不含原始元组)，不是缓存叠加。

### 6. 声明测试命令

按 context 原 env 逐字执行，四个测试文件 **237 passed in 0.53s**,零失败零跳过。

## Evidence And Assumptions

**证据(可复现)**

- 探针 A `runs/mw_protocol_v3_1r4_contract_fresh_20260905/probe_general_single_object.py`:86 项检查,85 过。含:HEAD 对比 12 项全过；每型 20 项压缩语义(源对象不变、dump 弹键、摘要一致、材料 hash 分叉、matches_dependencies 对原始/乱序/缺项/替换/重复实际输入的判定、JSON 往返、幂等、冻结、冲突元组+摘要被拒)；重复/缺失 v1 字段被拒。
- 探针 B `runs/.../probe_replay_harness.py`:15 项全过。含 reducer 版本传播链、摘要重绑、内存元组清空、源对象不变、精确回放同对象、变元组同 CAS 冲突、伪造摘要经快照链可检测、harness 压缩合同端到端、build 后篡改复验 fail-closed、v1 路径不回归。
- 声明 pytest:237 passed。
- 关键源码行号:protocol_v3.py:185-210(`_material_value` 双版本跳位)、260-311(基类)、818/846/921/1130(四类型);harness.py:794-799;document.py:1062-1065、653-659/673-681(payload hash)、1119-1145。

**推断(基于上述证据)**

- 唯一 FAIL 项：同字段名 + 同哈希 → 同摘要。`_dependency_hash` 域为 `{"domain":"mw_protocol_v3_dependencies_v1","field":<字段名>,"hashes":[…]}`,不含模型身份;`SemanticDocumentRevision` 与 `SubmissionEvidencePackage` 共用 `chapter_contract_hashes` 字段名，故跨类型摘要相等。推断为低危:摘要从不出所附模型实例单独旅行或被比较，matches_dependencies 绑定实例，材料 hash 覆盖其余全部字段，产品代码不存在跨类型比较路径。
- v1_1 "空元组 + 任意外来摘要”在四类型上均可通过模型验证(探针证实)，且无法从存储对象本身辨别摘要真伪。推断为不透明压缩的固有属性而非实现缺陷：序列化 v1_1 必然缺元组，验证端无从复核；安全性由两个外部验证点保障(harness 对实际输入、快照链对摘要字节)。
- `matches_dependencies` 传 list 时 v1 返回 False(元组 != 列表)而 v1_1 返回 True(仅 JSON 序列化)的不对称——产品仅传元组，判为装饰性。

**假设**

- 假设声明测试环境(`runs/mw_protocol_v3_1r_integration_20260905/venv`,38 包哈希锁)可信，未另行审计环境本身。
- 假设 `git show HEAD` 即“改动前”状态(工作树自上次提交后该文件未被再改过，冻结哈希与声明一致支持此假设)。

## Risks, Gaps, And Verification Needs

按影响排序，均不阻断 1R.4 当前门：

1. **[设计观察/跨类型摘要不可区分]** `_dependency_hash` 域缺模型身份,两类同字段名合同摘要可互换。现无产品路径可比较跨类型摘要,无实际漏洞；但一旦 2R.1 typed facade 同时物化两类 v1_1,审计语义上"摘要属于哪个合同类型"只能靠外层模型背书。建议：**现在决定**是否把 `type(self).__name__` 纳入摘要域并同步升 domain 字符串——v1_1 尚无任何持久化实例，此刻改动零迁移成本；待 2R.1 落地后任何改动都要迁移。这是我发现的最高影响决策点。
2. **[覆盖缺口/摘要算法无 golden 锚]** 测试固定了全部 legacy 材料 hash,但没有任何测试固定 v1_1 摘要值或压缩后材料 hash。`_dependency_hash` 的 JSON 布局(键序、domain 字符串)若被无意改动，旧 v1 锚不报警，而未来持久化的 v1_1 将全体漂移。建议：为四类型各加 1 个 golden digest/压缩材料 hash 常量测试(纯测试改动)。
3. **[残留/不透明摘要的可验证性]** "空元组+外来摘要可过验证”应记入契约 docstring 作为声明残留，并明确安全前提：摘要只经 matches_dependencies(实际输入)与父级材料 hash 两个路径获得意义。当前 docstring("legacy payloads and hashes stay intact")未陈述这一点。
4. **[覆盖缺口/负向 fixture 分布]** 冲突元组+摘要的 ValidationError 直接断言仅覆盖 lock/submission 两型(test_compact:120-123);文档/执行合同型经共享基类机制间接覆盖(我的探针补齐了四型)。legacy 缺字段负向仅对 NodeExecutionContract 显式断言。若 Codex 要求逐型显式负向 fixture,可按修订计划“原全部负向 fixture 原样保留”精神补齐；我的判断是机制共享、风险低，可不补。
5. **[装饰性]** harness.py:797 错误消息在压缩合同下仍引用 `input_artifact_hashes`(实际已清空)；v1_1 schema Literal 与 `compact_dependencies` 中 `"mw_protocol_v3_contract_v1_1"` 字面量重复两处，建议提常量防漂移。
6. **[未验证/明确留白]** 存储层(事件/rows)对 v1_1 序列化的实际落盘、JSON schema 面变化(`dependency_sha256` 出现在生成 schema,外部严格 schema 消费者可见新可选属性)的影响、以及首个 v1_1 实例的引导时机(2R.1),均在本切片外，需在 2R.1 门单独验证。

**供 Codex 裁决的边界问题**:(a) 观察点 1 是否现在改摘要域(我倾向：改，含 domain 串升级与四常量锚同步，一次测试提交内完成);(b) 观察点 2/4 是否作为 1R.4 门内补测试，还是记入 2R.1 前置清单;(c) 确认“无产品引导首个 v1_1”是本门预期状态。安全暂定路径：三项均不动产品源码，仅以测试/文档形式落地，不改变本门结论。

## Recommended Next Step

1. Codex 对上述三个边界问题给出裁决；若采纳观察点 1,先改 `_dependency_hash` 域(加模型身份 + domain 串 `…_v2`)并同步补四类型 golden digest 锚，再冻结 v1_1;若不采纳，把跨类型摘要语义写入契约 docstring 记为已接受设计。
2. 补测试(仅 tests/,不动产品)：四类型 golden digest/压缩材料 hash 锚 + 冲突元组负向补齐文档/执行合同两型；随后在声明 env 重跑四文件确认 237+ 全绿。
3. 本报告连同两个探针脚本移交 runner 持久化;2R.1 启动时，将“首个 v1_1 引导路径、存储落盘字节、JSON schema 面变化”列为该门必验项(继承本报告第 5、6 节结论，避免重复审计)。
