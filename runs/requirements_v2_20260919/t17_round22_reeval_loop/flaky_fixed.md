# A11 flaky 族修复与复验记录（R22，2026-09-27）

仓库根：`implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313`，HEAD=d3682a9（本记录撰写时工作树含本轮未提交改动）。
本文件按测试分节记录：失败机制、红证据、修法、绿证据、移出"已知 flaky 观察清单"的依据与重新入册条件。
所有命令均在仓库根实跑，`PYTHONPATH=services/api:.:tools/acceptance`，离线零模型，不涉 live 8910/医学监查/共享 runtime。

---

## ① tests/test_medical_writing_synopsis_import.py::SynopsisAsyncJobTest::test_cold_recovery_missing_or_changed_route_is_non_retryable

### 失败机制（如实归因：不是"租约窗"）

- **可见性竞态（已观测失败的真实机制）**：`start_job` 只同步插入 job 行（phase='parsing'，`medical_writing_synopsis_import.py:910-939`），parse→chunk 落库在分离线程完成（`:948-963` → `:1099-1115`）。`recover_stale_jobs` 用 **INNER JOIN chunks** 选 stale job（`:2074-2085`）——chunk 行未落库的 job 对恢复完全不可见：恢复返回 0、job 停留 pending，测试断言 `['failed','failed'] != ['pending','pending']`。pending 项入选（`:2083`）**无需租约过期**。
- **租约判定（第二维度，拨钟使其确定化）**：租约过期判定（recover 的 `now` 于 `:2060`、过期 chunk 重置于 `:2064-2073`、认领租约写入于 `:573/:720/:1349`，`claim_timeout_seconds` 默认 360 秒 `:101`）依赖真实墙钟，测试此前不可控。

### 红证据（本会话实捕，早于轮询层落地时）

修复前循环实跑（命令：`python3 -m pytest "tests/test_medical_writing_synopsis_import.py::SynopsisAsyncJobTest::test_cold_recovery_missing_or_changed_route_is_non_retryable" -q`，连跑 12 次）：
**12 跑 5 败**（run5/8/10/11/12 报 `1 failed`）。失败断言原样输出：

```
>           self.assertEqual(["failed", "failed"], [row[1] for row in states])
E           AssertionError: Lists differ: ['failed', 'failed'] != ['pending', 'pending']
E           First differing element 0:
E           'failed'
E           'pending'
tests/test_medical_writing_synopsis_import.py:1762: AssertionError
```

（注：行号 1762 为该轮修复前的行号。）

### 修法（两层）

1. **冻结时钟（产品缝）**：`MedicalWritingSynopsisImportService.__init__` 新增 `clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)`（默认值逐字等于原行为，生产无感），存为 `self._clock`；全文件 23 处 `datetime.now(timezone.utc)` 机械替换为 `self._clock()`（残留检查 `rg -n "datetime.now(timezone.utc)" services/api/app/medical_writing_synopsis_import.py` 仅剩默认 lambda 定义行 108）。测试侧 `_AdjustableClock`（实例自有状态、只向前拨）传入 `self.service` 与 `recovered` 服务；恢复前 `self.clock.advance(self.service.claim_timeout_seconds + 60.0)` 使租约过期判定确定化。
2. **顺序隔离（可见性）**：拨钟后、改 route 快照与调恢复前，有界轮询（截止 10 秒、间隔 50 毫秒、超时以明确信息 fail）等待两个 job 的 chunk 行落库——即恢复查询真正依赖的条件。`_shutdown_requested` 只挡 AI worker 生成（`_spawn_chunked_worker` 直接 return），不影响 chunk 落库。

**如实声明**：仅 clock 注入修不掉已观测的失败模式（红证据全部是 pending 可见性断言，与租约无关）；仅轮询不解决租约维度的潜在时序。两层合用后所有交错路径收敛到同一确定结局：route 缺失→`_load_frozen_route` 报错（`:289-307`）、route 变更→哈希不一致（`:265-270`），双双走恢复失败路径（`:2117-2123`）。

### 绿证据

修复后连跑 3 次（ask 门槛，原样输出）：

```
=== run 1 ===
1 passed, 18 warnings in 1.54s
=== run 2 ===
1 passed, 18 warnings in 1.40s
=== run 3 ===
1 passed, 18 warnings in 1.42s
```

统计强度补充：同命令再连跑 30 次 → `THIRTY_RUN_FAILURES=0`（即累计 33 连跑 0 败）。整文件一次：`python3 -m pytest tests/test_medical_writing_synopsis_import.py -q` → **33 passed, 18 warnings in 3.66s**。

> 诚实备注：3 次全绿是 ask 门槛但统计上弱（修复前约 30% 概率蒙对 3 连绿）；故补充了 30 次。33 次全绿仍不等于"永不再 flaky"，见下节重入册条件。另：工作树在 3 次门槛测量时已同时包含两层修复（轮询层在本工作树早一轮已落地），本轮绿证据测的是**双层合并**的效果。

---

## ② tests/test_ai_execution_policy.py（收集期播种）× tests/test_medical_writing_generation_context_v2.py（digest）

### 机制

污染文件在**收集期** `from services.api.app.main import app`（main.py 导入期读取 WORKBENCH_RUNTIME_DIR 并播种 ai_provider_settings.json），受害者的 resolver 若未带 `test_only_provider_injection=True`，`route_identity_snapshot(refresh=True, task_type=medical_writing_revision)` 会读 live 设置并覆盖钉死的路由（`ai_execution_policy.py:458-464`、`_capture_revision_cloud_route :359-383`），两个 digest 变得相同 → policy-change 断言失败。受害者文件 3 处 resolver 构造均已带冻结旗标（`tests/test_medical_writing_generation_context_v2.py` 的 `_policy_runner:70`、`:682`、`:1309`）。

### 三步验证（ask 指定，命令与输出原样）

```
1) 单跑：env -u WORKBENCH_RUNTIME_DIR python3 -m pytest \
     "tests/test_medical_writing_generation_context_v2.py::GenerationContextDescriptorTests::test_policy_change_changes_digest" -q
   → 1 passed in 1.10s

2) 污染前置+目标：env -u WORKBENCH_RUNTIME_DIR python3 -m pytest \
     "tests/test_ai_execution_policy.py::AiExecutionPolicyTests::test_ai_result_reads_fail_closed_before_runner_access" \
     "tests/test_medical_writing_generation_context_v2.py::GenerationContextDescriptorTests::test_policy_change_changes_digest" -q
   → 2 passed, 18 warnings in 2.02s

3) 逆序：第 2 步两节点交换顺序重跑
   → 2 passed, 18 warnings in 2.05s
```

### 红探针（证明单点修复承重；临时撤旗标、跑红后立即还原，不入库）

操作：删除 `_policy_runner` 第 70 行 `test_only_provider_injection=True,`（行定位精确删除），重跑第 2 步：

```
______ GenerationContextDescriptorTests.test_policy_change_changes_digest ______
    def test_policy_change_changes_digest(self):
>       self.assertNotEqual(a["digest"], b["digest"])
E       AssertionError: 'b165adc16bd335b856ce4ff3c9a69f0ba6aa8219119662173eae1a6dcf352ab0' == 'b165adc16bd335b856ce4ff3c9a69f0ba6aa8219119662173eae1a6dcf352ab0'
tests/test_medical_writing_generation_context_v2.py:244: AssertionError
FAILED tests/test_medical_writing_generation_context_v2.py::GenerationContextDescriptorTests::test_policy_change_changes_digest
1 failed, 1 passed, 18 warnings in 1.98s
```

与 `tests/acceptance/test_order_pollution_a11.py:15-19` 证据链记录的失败签名一致（digest 相同 → policy-change 断言失败），无其他失败签名。随即 `git checkout -- tests/test_medical_writing_generation_context_v2.py` 还原，`git diff --stat` 该文件为空（干净）。

首次探针尝试因锚点不唯一在修改前被断言拦下（文件未被改动，随后的 2 passed 为未修改文件上的运行，不作为探针证据）；第二次以行号定位成功。

### 整文件双序复跑存档（补充）

```
=== order A: 污染文件 → 受害者文件 ===
55 passed, 18 warnings, 3 subtests passed in 41.02s
=== order B: 受害者文件 → 污染文件 ===
55 passed, 18 warnings, 3 subtests passed in 41.24s
```

②预期无需改代码：三步全绿 + 双序整文件全绿，未触发条件性 tearDown 隔离，`tests/test_medical_writing_generation_context_v2.py` 工作树零改动。

---

## 移出"已知 flaky 观察清单"的依据与重新入册条件

### 移出依据

- ①：红证据（12 跑 5 败、断言原文）→ 双层修复 → 3 连绿（ask 门槛）+ 累计 33 连跑 0 败 + 整文件一次绿；失败机制的两个维度（可见性、租约判定）分别由轮询与拨钟确定化，所有交错路径收敛到同一确定结局。
- ②：三步验证全绿 + 整文件双序各 55 passed；红探针证明冻结旗标是承重修复（撤掉即复现文档化失败），且守卫（`tests/acceptance/test_order_pollution_a11.py` 的家族级静态守卫，R21 加入）会在未来任何未冻结 resolver 构造点变红。

### 重新入册条件（任一即重新入册）

1. 出现**新的失败签名**（非 `['failed','failed'] != ['pending','pending']`、非 digest 相同断言）；
2. 改动触及本修复依赖的路径：分离线程启动时序（`_finish_import_start` / `_spawn_chunked_worker` 的 shutdown 判定）、恢复查询的 INNER JOIN chunks（`recover_stale_jobs`）、构造函数 clock 缝（`medical_writing_synopsis_import.py:95-110`）、或收集期播种机制（`main.py` 导入期设置 bootstrap / `test_only_provider_injection` 语义）；
3. 上述任何绿证据命令在相同环境下复现失败。

### 有限次数的诚实边界

任何有限连跑次数都不能证明"永不再 flaky"。本记录的结论是"在当前代码与环境下，失败机制的两个维度已被确定化，且累计 33 次（①）/ 双序整文件（②）未见复发"，不是"已消除 flaky"。
