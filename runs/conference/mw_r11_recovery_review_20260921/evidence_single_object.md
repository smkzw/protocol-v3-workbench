I'll start by reading the required initial read set.

Now let me read the core source files under review. Starting with the agent3 module.

Bash is denied in this session. Proceeding with read-only tools (Read/Glob/Grep) and noting this honestly.

All three test files exist. Note `agent3/product_factory.py` does not — I'll verify that. Now reading the core recovery implementation.

Now the API resume/recover paths.

Now the tests, which encode intended semantics.

我已完成独立审阅。以下是完整报告。

# Conference Output: mw_r11_recovery_review_20260921 - evidence_single_object

## Output

### 0. 工具与边界声明（先说明可信度来源）

- **Bash 被拒绝**：本会话 `Bash` 工具在非交互模式下无权限（两次调用均返回 permission denied）。因此**我没有运行任何测试、pytest、git、ruff 或脚本**。本报告全部结论来自静态阅读（Read/Glob/Grep），不含运行期证据。任何"PASS"都应读作"静态阅读未发现反证"。
- 未读写凭据/运行时配置/DB/handoff 密钥；未写任何文件（含 runner 的 `evidence_single_object.md`）；未读 executor 报告或私有推理；未做 git 变更、清理、网络、服务、浏览器、子进程。
- **读取的初始集合与实际仓库不一致（证据清单缺陷，需 Codex 修正）**：
  - `services/api/app/protocol_workflow/agent3/product_factory.py` **不存在**。glob `agent3/**/*` 无此文件，全库 grep `product_factory` 在 `services/` 下零命中。实际对应文件是 `agent3/product.py`（`create_product_chapter_factory` 在 product.py:18，`lazy_product_chapter_factory` 在 product.py:57）。`tests/protocol_v3/test_chapter_product_factory.py` 通过 `from app.protocol_workflow.agent3.product import create_product_chapter_factory` 导入，可反证。
  - `tests/protocol_v3/{test_manuscript_recovery,test_chapter_product_factory,test_graph_runtime}.py` **三个都存在**（此前一次 glob 因 100 条上限漏显，二次定向 glob 确认）。
  - 影响：若 Codex 依赖该 read set 做路径级核验，会得到"文件缺失"的假信号；建议后续 prompt 用 `agent3/product.py`。本报告已按实际路径审阅。

---

### 1. 逐条判定

| # | 判据 | 判定 | 依据（精确位置） |
|---|---|---|---|
| C1 | 显式 resume 必须在存在"不可重试"或"活跃未知"子章时仍继续未完成兄弟章；已完成章节永不重跑 | **FAIL** | 不可重试分支失败：`manuscript_coordinator.py:100-104, 107-111`。活跃未知分支与"已完成不重跑"通过 |
| C2 | read/recover 保持只读 | **PASS（静态，含 1 处低危附带写）** | `api/manuscript_drafts.py:355-362` → `original()` → `owner.read()`；`coordinator.py:155-182` 只 load_run/read_events。附带写：见 F4 |
| C3 | 活跃未知工作永不自动重派 | **PASS（静态）** | `runtime.py:602-613, 650-655, 843-849, 1174-1201`；`proposal_progress.py:8-10`；`coordinator.py:74-79`；测试 `test_graph_runtime.py:739`、`test_graph_runtime_recovery.py:490` |
| C4 | 显式重试保留身份、次数受限、旧 run 兼容且不静默改写历史、不接受无关图变更 | **PASS（身份/历史/绑定）/ FAIL（次数上限两处）** | 绑定与预算单调扩展：`runtime.py:953-1002`；历史只追加：`runtime.py:1809-1830, 1832-1866`。缺陷见 F2、F3 |
| C5 | 纠错去重必须保住真实输入契约、科学事实、引用、schema 重建与 provider/model 血缘 | **PASS（静态，2 处低危）** | `proposal_correction.py:65-80, 99-120`；`subgraph.py:53-55, 62-69, 90-98`；`chapter_draft.py:71-77, 88, 99-110`。低危见 F5 |
| C6 | API 必须真正调度续跑，前端在核对后调用；单纯刷新不算进展 | **PASS（可续跑时）/ FAIL（不可重试时退化为纯刷新）** | 正常：`manuscript_drafts.py:344-351`（BackgroundTasks）、`ManuscriptWorkspace.jsx:377-380`。退化见 F1 |
| C7 | 识别重试耗尽处理；"看似 running"是否会无活跃工作空转 | **部分 FAIL / 1 项 UNVERIFIED** | 图级有界：`runtime.py:403-417, 436-464`；测试 `test_graph_runtime.py:1223`。产品级见 F1、F6、U1 |

---

### 2. 主要缺陷

#### F1（最高影响，直接违反 C1/C6）——一个"不可重试"子章把整稿 resume 变成空操作

**证据（代码路径，静态可复现）**

`ManuscriptDraftCoordinator.read()` 把两种语义完全不同的 blocked 折叠成同一个 `{status:'blocked', can_resume:false}`：

```
manuscript_coordinator.py:100-101
stopped = any(item['status'] not in {'not_started','running','needs_content_review'}
              and not item.get('can_resume') for item in applicable)
manuscript_coordinator.py:104
'can_resume': not complete and not stopped and any(item.get('can_resume') for item in applicable),
```

`manuscript_coordinator.py:107-111` 于是直接返回、不进入任何续跑：

```
def resume(self, run_id):
    prepared = self.prepared_request(run_id)
    state = self.read(run_id)
    if not state['can_resume']:
        return state                      # ← 兄弟章完全没有机会
```

`api/manuscript_drafts.py:344` 的 `if state['can_resume']:` 因此不 `tasks.add_task`，`/resume` 返回 202 但**零动作**；前端 `ManuscriptWorkspace.jsx:380` 的 `else if (state.can_resume)` 同样不调用，`resume()` 只 `setRefresh(v=>v+1)`（jsx:390）。

注意 `manuscript_coordinator.py:129-139` 为"一章失败不拖垮全稿"写了逐章 `try/except Exception` 隔离——但**恰好在该用例下不可达**：状态型不可重试子章在全稿闸门处就被拦掉，根本进不了这个循环。异常型失败被隔离，状态型失败没有。

**精确触发（两条都现实可达）**

1. 章节 A：`chapter-generate` 先 `UNKNOWN_OUTCOME`，显式重试后再 `UNKNOWN_OUTCOME`。`allowed_attempts=2`（`subgraph.py:27`），`coordinator.py:80-81` 的 `len(attempts) < allowed_attempts` 变 False → `read` 返回 `status='blocked', can_resume=False`。
2. 章节 A：模型输出结构非法 → 走一次纠错仍非法。`coordinator.py:174-179` 从 correction run 读取，`proposal_outcome` 返回 `{"status":"needs_structure_correction","can_resume":False}`（`proposal_progress.py:20`）。该状态同样不属 `{'not_started','running','needs_content_review'}` → `stopped=True`。

两种情况下章节 B（从未起跑，`status='not_started'`）永远不被起草。

**用户可见后果**：`ManuscriptWorkspace.jsx:463-467` 在 `status==='blocked'` 时渲染按钮，`job.can_resume` 为 false 时文案变成 **"核对未完成章节的状态"**，点击后只刷新——正是判据禁止的"单纯刷新不是进展"。且 `jsx:499` 在 blocked 时隐藏了"核对并继续本次写作"，`jsx:470` 的"按当前研究准备新稿"要求 `plan.study_sha256 !== packet.studySha`（研究变更才出现），因此**同一研究下没有可把兄弟章推进下去的入口**。

**已被测试固化为"期望行为"**（这是最危险的一点）：`ManuscriptWorkspace.test.jsx:36-48` 断言 `blocked + can_resume:false` 时 `resumeManuscriptDraft` **不得**被调用。该断言对"活跃未知"是对的，对"不可重试"是错的——前端测试把两种语义一起锁死了。`tests/protocol_v3/test_manuscript_recovery.py:86-117` 是唯一覆盖整稿协调器的测试，其 blocked 子章写的是 `can_resume: True`，**不可重试分支无任何测试**。全库仅 `test_manuscript_recovery.py` 引用 `ManuscriptDraftCoordinator`（grep 证明）。

**最小修复（后端为主，无需改协议）**

1. `manuscript_coordinator.py:96-105`：把 `stopped` 拆成两个互不混淆的量，并让 `can_resume` 只表达"是否还有可推进的章节"：
   ```python
   resumable = [item for item in applicable
                if item['status'] in {'not_started', 'running'} or item.get('can_resume')]
   non_retryable = [item for item in applicable
                    if item['status'] not in {'not_started','running','needs_content_review'}
                    and not item.get('can_resume')]
   return {..., 'status': 'needs_content_review' if complete else
                        ('blocked' if non_retryable else 'running'),
           'can_resume': not complete and bool(resumable),
           'non_retryable_chapters': [item['node_id'] for item in non_retryable],
           ...}
   ```
2. `manuscript_coordinator.py:110-111`：去掉整稿早退，改为信任已有的逐章闸门（`129-130` 的 `if outcome['can_resume']` 与 `121-128` 的 `not_started` 起跑）；不可重试章自然被跳过、不进循环体。
3. `api/manuscript_drafts.py:344` 与前端 `jsx:380` **无需修改**即可随 `can_resume` 语义修正生效；可选地让 `jsx:466` 用 `non_retryable_chapters` 换一句更准确的说明（如"本章需要按当前研究准备新稿"）。
4. 影响面有界且已核实：`can_resume` 的消费点只有 `manuscript_drafts.py:323,344`、`manuscript_coordinator.py:110`、前端 `ManuscriptWorkspace.jsx:380`（grep 全部命中）。新增字段是附加式，不破坏现有消费者。

**必须补的决定性测试**（当前会是红的）：`tests/protocol_v3/test_manuscript_recovery.py::test_non_retryable_child_does_not_freeze_unfinished_siblings`
- 假 owner：章 A 恒返回 `{'status':'blocked','validation':None,'can_resume':False}`；章 C 返回 `graph_run_unknown`（等价 `not_started`）。
- 断言 `read()['can_resume'] is True`；
- 断言 `resume()` 后 C 被 `start`+`resume` 各一次，A **既未被 `start` 也未被 `resume`**（不重复活跃调用）；
- 断言 `read()['non_retryable_chapters'] == ['chapter-A']`。

---

#### F2（C4，"次数受限"）——孤儿 shell 自动恢复绕过 `allowed_attempts`

`runtime.py:1219-1267` 的 `_recover_zero_attempt_orphan` 在判定 `terminal_state is FAILED and error_code == dispatch_not_started_recovery and transport_attempts == 0` 后，**直接**调用 `coordinator.retry_explicit(... attempt=reservation.attempt + 1 ...)`，**全程没有读取 `allowed_attempts`**。而预算检查只存在于 `GraphRuntime.retry_node`（`runtime.py:861-867`）与 `coordinator.py:80-81`。`ReservationCoordinator.retry_explicit` 本身不接受预算参数（`reservations.py:406-489`）。

**触发**：RESERVED shell（`reserve` 已提交、RUNNING 未提交）→ 进程死 → 下次 `advance` 走 `_execute_node` → `reserve_or_reuse` 把它处置为零尝试 FAILED（`reservations.py:340-364`）→ `_recover_zero_attempt_orphan` 立刻以 attempt+1 真派发。**在该窗口反复被杀，就是无上限的自动重派**，节点即使声明 `allowed_attempts=1`（如 `chapter-validate`、`register-manuscript`）也照样新增 attempt。可达性需要精确落在 `reserve`→RUNNING 之间的窗口，概率低，但这是唯一一条"自动重试不受预算约束"的路径。

**测试缺口（可核实）**：`tests/` 全库无任何对 `_recover_zero_attempt_orphan` 的引用（grep 证明）；既有孤儿测试都在协调器层（`test_execution_reservations.py:649`、`test_durable_reservation_dispatch.py:211,401`）；真实进程死亡矩阵的 `kill` 指令是"在 dispatch 内、RUNNING 之后"死亡（`test_graph_runtime_recovery.py:63-64`），产生的正是 UNKNOWN_OUTCOME 而**不是** RESERVED 孤儿；`test_kill_before_node_leaves_no_partial_state`（:418-457）杀在节点开始之前，节点保持 pending，也不覆盖该路径。

**最小修复**：在 `runtime.py:1246` 取 `inputs` 之前加预算闸门：
```python
if len(self.reservation_attempts(workflow_run_id, node.node_id)) >= plan.node(node.node_id).allowed_attempts:
    return outcome            # 保持 FAILED，交给显式 owner 决策
```
**决定性测试**：用已提交仓储播种一个零尝试 RESERVED shell（`allowed_attempts=1`），换新 runtime `advance`，断言不产生第二次 attempt 且节点为 `failed`；如 Codex 认为"零 transport 孤儿可重试"是刻意语义，则应改为断言 attempt 索引等于 `allowed_attempts` 或把该例外写入判据——**目前代码与文档都没有表态，这是判据空洞**。

---

#### F3（C4，"次数受限"/潜在）——固定重试身份使"提高预算"在旧 run 上不可达

`coordinator.py:101` 的 `retry_decision_id=run_id + ':retry:1'` 是**硬编码常量**，而 `runtime.py:829-842` 对同一 `retry_decision_id` 是幂等返回（`reservations.py:682-692` 派生 key 不含 attempt 号）。于是该协调器对一个节点**最多只能显式重试一次**：第一次成功后，第二次 `_retry_node` 在 `runtime.py:841-842` 直接返回快照，不再分配 attempt。

这与 `runtime.py:953-980` 的 `_retry_budget_compatible` **明确允许把旧 run 的 `allowed_attempts` 单调上调**（并有测试 `test_graph_runtime.py:902-954` 证明）形成矛盾：预算被提到 3 时，产品路径无法创建 attempt 3。当前无触发（`subgraph.py:24-30` 只有 1 和 2），属**潜在**缺陷，但一旦有人按该特性上调预算就会静默失效。

**最小修复**：把身份按可分配次数派生（如 `f'{run_id}:retry:{len(attempts)}'`），或由调用方传入 `retry_decision_id`。**决定性测试**：`allowed_attempts=3` + `new_plan` 预算扩展，连续两次显式重试后断言 attempts 序列为 `[1,2,3]`。

---

### 3. 次要/低危（已核实，供 Codex 取舍）

- **F4（C2 附带写）**：`agent3/product.py:45` 在每次 read 都构造 `LocalArtifactStore`，其 `__init__` 执行 `os.makedirs`（`artifacts/local_store.py:87-88`）；`runtime.py:612-613` → `storage/sqlite.py:2087-2104` 在探测活跃租约时 `directory.mkdir(exist_ok=True)` 并 `open("a+b")` 创建且**永不删除**锁文件。都是幂等文件系统副作用，**不改领域状态、不派发、不重写历史**；是否算违反"read-only"由 Codex 定标准。若要求严格只读，最小做法是让 `read` 路径使用轻量仓储视图，而不是 `_owner()` 每次新建 store。
- **F5（C5 低危）**：`_compact_correction_input` 删掉 `source_material.evidence` 后，`chapter_draft.py:20` 的固定指令仍写"source_material 如存在，包含完整源结构"——对纠错调用略有失准（顶层 `evidence` 仍在，引用身份不受影响）。最小修复：`proposal_correction.py:111` 的 `instruction` 追加一句"本次 source_material.evidence 与输入 evidence 相同，已省略"。
- **F5b**：`structure_correction_inputs` 的 `error_prefix + "_correction_budget_exhausted"`（`proposal_correction.py:103-104`）是未映射的 `ValueError`，不是图级 blocked 状态。按生产路径**不可达**（原始 run 的 roots 只有 `chapter_intake`，`subgraph.py:18`，其 receipt 不可能含 `correction-context` 输入）。仅作防御性说明，建议至少映射为带原因的 blocked，避免未来变成无法收敛的重试环。
- **F6（C7 表述）**：`runtime.py:615-668` 接收 `resolution_id`/`reason` 但**只校验非空、不持久化**（转换只写 `error_code='crash_resolved_failed'`）。docstring 声称"显式、可审计"，实际审计链看不出谁以何身份关闭了崩溃窗口。若 Codex 认为需要，最小修复是追加一个携带该身份的领域事件（`ExecutionReservation` 无字段可放）。
- **F7（死分支）**：`_load_reservation_states`（`runtime.py:1050-1054`）把 RESERVED 也放进 repairs，但 `_apply_reservation_repairs`（:1845-1848）只处理 RUNNING/UNKNOWN_OUTCOME。RESERVED+已提交 result 无法由本代码路径产生（result 在 RUNNING 之后写，:591-610）。删掉或补齐，属清洁度问题。
- **类型标注**：`_recover_zero_attempt_orphan` 声明返回 `ReservationOutcome`，实际返回 `retry_explicit` 的 `ExecutionReservation`（`runtime.py:1248` vs `reservations.py:488`）。二者都有 `.terminal_state`，行为正确，但标注错误；`retry_node:900` 用 `del outcome` 说明作者本来知道差别。

---

### 4. PASS 部分的关键证据（避免 Codex 重复验证）

- **旧图重试兼容（我的目标项之一）实现正确且已被测**：`material_payload()` 含 `project_id/branch_id/graph_id/graph_version/schemas/root_inputs`（`graph/plan.py:328-354`），`_retry_budget_compatible` 先剥离 `allowed_attempts` 再要求**整体相等**（`runtime.py:972-976`），因此换 graph_version、增删节点、改依赖/逻辑键都会被拒；`_assert_binding`（:982-1002）在 `exact or compatible` 才放行。测试：`test_graph_runtime.py:604-629`（旧版本拒绝、历史保留）与 `:902-954`（预算单调扩展、attempts `[1,2]`）。
- **章节失败隔离**确实存在（`manuscript_coordinator.py:118-139`），逐章 `try/except Exception` + stderr 记录，且不 `start` 已存在 run（`coordinator.py:43-56` 的 `load_run` 幂等）。
- **身份保持**：`prepared.chapter_requests()`（`manuscript_request.py:37-45`）用 `canonical_json({**shared, **chapter})` 重建的载荷与建单时逐字节一致（`shared`/`local` 键集互斥，`manuscript_request.py:77-92`），故 `owner.run_id()` 稳定，兄弟章不会因重算身份而被当成新任务。
- **纠错去重不破坏契约**：`_compact_correction_input` 只在 `source_material["evidence"] == payload["evidence"]` 时删重（`proposal_correction.py:75-79`），而 `read_chapter_draft` 的引用全集取自**顶层** `payload["evidence"]`（`chapter_draft.py:88, 99-110`），`resolved_facts` 在未触碰的 `chapter_input` 内；纠错 run 的 `chapter-intake` 工件哈希与 `validate` 重算的 `prepared.input_sha256` 同源（`subgraph.py:54-60, 90-98`），故 `chapter_response_input_mismatch` 不会误报。provider/model/effort 血缘经 `chapter_correction_model_mismatch` 强校验（`subgraph.py:64-66`）。测试：`test_chapter_product_factory.py:10-104`。

---

### 5. 分层结论

- **观察（证据）**：以上所有 file:line、grep 命中、测试断言均为我直接读到的仓库内容。
- **推断**：F1 的用户可见路径（点击"核对未完成章节的状态"仅刷新）由 `manuscript_drafts.py:344` + `ManuscriptWorkspace.jsx:380,466,499` 静态串联得出，**未经浏览器验证**。
- **建议**：F1 的修复方案我做了消费点穷举（grep `can_resume` 全 services 命中），影响面可控；F2 的修复是一行闸门。
- **不确定**：见 U1；以及我未运行测试，因此无法确认 F1 的新测试当前为红（预期为红，但这是推断）。

---

### 6. 未验证项（诚实标注）

- **U1**：`job.status==='running' && can_resume===false`（活跃未知）时前端按 `jsx:275` 每最迟 30s 轮询、无终止条件。只要租约探测（`storage/sqlite.py:2097-2104`，flock）在持有者进程存活期间恒为 True，而持有者已卡死（未在 adapter 超时内收敛），UI 就会长期显示"正在撰写"。**我未能验证 adapter 超时是否真的会中断卡死的 dispatch**——需要读 `runtime/adapters/zhipu_api.py` 中 `REQUEST_TIMEOUT_SECONDS` 的落地执行（`subgraph.py:13,41` 只引用常量并写进契约）。请 Codex 指定该文件为读集后我可在同会话补验。若超时确实生效，此项降级为可接受。
- **U2**：未做任何运行时验证（Bash 被拒）：F1/F2/F3 的测试均为"应新增"，不是"已运行且红"。
- **U3**：未审 `agent2/*` 的同类 `can_resume` 模式（`agent2/coordinator.py:70`、`design_coordinator.py:72` 与 agent3 形状相同），它们不在我的范围；若整稿修复引入通用语义，需 Codex 决定是否同步。

---

### 7. 给 Codex 的质疑、决策点与有界问题

**最重要的反对意见（一句话）**：C1 的措辞（"必须在存在不可重试子章时仍继续兄弟章"）与当前实现是**直接冲突**，而不是边缘情形——因为整稿状态机把"活跃未知"（必须停）与"重试耗尽/纠错后仍非法"（必须继续兄弟）合并成了同一个 `blocked + can_resume:false`。前端测试 `ManuscriptWorkspace.test.jsx:36-48` 还把这一合并锁成了期望行为。**做修复必须同时改这个前端测试的意图**，否则代码改了测试仍旧绿→语义继续被冻结。

**被挑战的假设**：计划第 4 条"章节失败隔离"可能被误读为"已实现"。更准确的说法是：**隔离仅覆盖异常型失败；状态型不可重试失败被全稿闸门拦在隔离层之外**。请 Codex 在验收陈述里用后者，避免把"有 try/except"当成"覆盖了判据"。

**决策点（需要 Codex 定，不应由我代定）**
- D1：不可重试子章的最终呈现语义——`status` 保持 `'blocked'`（可见失败）但 `can_resume` 为真？还是新增 `status='blocked_partial'`？我倾向保持 `blocked` + 新增 `non_retryable_chapters` 字段，改动最小。
- D2：F2 的孤儿自动重试是"刻意允许"还是"必须受预算约束"？两条路都能自洽，但必须选一条并写进判据 + 补测试，不能留空。
- D3：F4 的文件系统副作用是否触碰"read-only"红线？若触碰，是改 `read` 路径还是改判据措辞？

**有界问题（回答可直接改变我的结论）**
- Q1：`chapter-generate` 的 `allowed_attempts=2`（`subgraph.py:27`）是契约上限还是仅为初值？若被明确设计为"原始 1 次 + 显式重试 1 次"，则 F3 只是潜在问题；否则 F3 需立即修。
- Q2：是否存在我未读到的产品级"重新准备该章节而非整稿"入口（例如仅按 `node_id` 重建单章 run）？若有，F1 的用户死路程度下降，但 C1 的"继续未完成兄弟"仍然 FAIL。
- Q3：是否需要我在同会话继续验证 U1（读 `adapters/zhipu_api.py` 的超时执行）与 U3（agent2 同形模式）？这两项我可以在同一会话内补齐，不需要新 session。

**建议的下一步顺序**：修 F1（含新增决定性测试与前端测试意图修正）→ 定 D2 后修/文档化 F2 → 决定 D3 → 补 F3 测试或降级为文档说明 → 再让我做一次同会话复验（此时需要允许 Bash 以取得真实测试证据；否则我只能继续给静态结论）。
