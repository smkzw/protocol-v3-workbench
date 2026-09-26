# A11 顺序污染：定位、修复与回归记录（0927V1 · 2026-09-27）

仓库：protocol-v3-workbench；HEAD=5b4c8c11692fc3118eb21bfe80877f5ce9d76c65（全程未变）。
污染对（侦察档案B类→本轮当场实跑锁定）：

- **polluter**：`tests/test_ai_execution_policy.py`——其【收集期导入】即触发（第27行 `from services.api.app.main import app`）。
- **victim**：`tests/test_medical_writing_generation_context_v2.py` 的6个route digest用例（GenerationContextDescriptorTests 5个 + DurableReuseAndDistinctJobTests::test_policy_change_creates_distinct_job）。

## 一、现象（修复前当场实跑）

| 命令（cwd=仓库根） | 结果 |
|---|---|
| `PYTHONPATH=services/api:. pytest tests/test_medical_writing_generation_context_v2.py` | 34 passed（单跑绿） |
| `PYTHONPATH=services/api:. pytest tests/test_medical_writing_generation_context_v2.py tests/test_ai_execution_policy.py`（victim先） | **6 failed, 49 passed** |
| 单victim节点 + 单polluter节点（victim先） | **1 failed, 1 passed**；失败断言：`assertNotEqual(a["digest"], b["digest"])` 两digest同为 `b165adc1…` |
| victim节点单独 | 1 passed |

受害断言失败消息：污染下两次 `build_generation_context_descriptor`（中间把runner从deepseek换成openai_compatible/other-model）digest完全相同——策略变更未反映进快照。

## 二、决定性分类：导入期污染，非执行期残留

pytest收集完成后、任何测试执行前取 `AiExecutionPolicyResolver("deepseek","deepseek-chat").route_identity_snapshot(refresh=True, task_type="medical_writing_revision")`：

| 场景 | 快照 | env(WORKBENCH_RUNTIME_DIR) |
|---|---|---|
| victim单独收集 | deepseek / deepseek-chat / disabled | 会话私有tmp |
| victim+polluter（两序皆然） | **opencode-go / deepseek-v4.1-flash / local_private_clinical** | 会话私有tmp（同一机制） |

两序快照都翻转、env相同 ⟹ 与执行顺序、env差异无关，是**收集期导入**改变了快照来源。故修复前"逆序绿"不可达（导入顺序=收集顺序），A11四步字面全绿只有在修复后才成立——修复前逆序同样红，未提前改任何断言（红线8）。

## 三、根因链（全部当场取证）

1. 导入 `app.main` 在**模块级**引导 AI 运行时设置单例（main.py:1840→:1588），经 ai_role_runtime_settings.py:526→ai_runtime_settings.py:343/401/476/554-555 的 `_atomic_write`（os.replace调用栈已抓取），向**当前 `WORKBENCH_RUNTIME_DIR`**（现为测试会话私有目录）播种 `ai_provider_settings.json` + `ai_provider_secrets.json` + `ai_role_bindings.json`。
2. `ai_provider_settings.json` 内含enabled的cloud fallback链（local_private_clinical / opencode-go / deepseek-v4.1-flash）。
3. victim的 `_policy_runner` 构造 `AiExecutionPolicyResolver(provider_name=…, model_name=…)` 时**未传** `test_only_provider_injection`；`route_identity_snapshot(refresh=True, task_type="medical_writing_revision")` 会走 `_capture_revision_cloud_route`（ai_execution_policy.py:359-383, 458-464）：读live设置的fallback链，把第一个enabled cloud profile**覆盖**到显式注入的路由上。
4. 于是：solo会话设置文件不存在→捕获落空→构造路由生效→digest随策略变化→PASS；只要同会话任何先前收集导入了main→设置被播种→两个runner被同一条cloud路由覆盖→digest相同→FAIL。 PASS/FAIL完全取决于**同会话其他文件的导入顺序**，即顺序污染。
5. 侦察阶段的载体假设（test_source_registry 的 sys.path.insert/绝对路径常量）被二分**证伪**：逐成员新进程导入实验中，仅 `services.api.app.main` 播种设置（demo_repository/ai_task_runner/monitoring_identity_authorization/source_intake均否），且polluter第27行直接导入main，与 `from tests.test_source_registry import _minimal_xlsx_bytes` 跨导入无关。test_source_registry未做任何修改（避免范围膨胀）。

## 四、修复（最小diff，测试侧，不碰红线4文件）

`tests/test_medical_writing_generation_context_v2.py::_policy_runner` 增加 `test_only_provider_injection=True`——产品自身文档化的harness边界冻结（ai_execution_policy.py:446-452"resolution must not consult live runtime settings"），且同文件durable harness（:672/:1299）早已使用该旗标，此处是遗漏。**断言零改动**：digest仍须随两条不同的显式策略而变化，只是不再依赖"会话里恰好没人播种设置"。产品侧是否应在导入期播种设置（main.py:1840）属于集成人决策，本Pass不改、仅记录。

## 五、四步绿灯输出（修复后当场实跑）

永久回归 `tests/acceptance/test_order_pollution_a11.py`（4次定序子进程pytest，各带240s timeout硬顶（红线6②），离线零模型（A16），子进程env不带WORKBENCH_RUNTIME_DIR→conftest每次供新私有runtime，步间零状态泄漏）：

```
python3 -m pytest tests/acceptance/test_order_pollution_a11.py -q
→ 4 passed（修前同命令：3 failed, 1 passed，红日志 a11_red_before_fix.log）
```

显式四步（真实命令逐条）：
1. victim单跑：`1 passed in 2.31s`
2. polluter先：`2 passed in 4.07s`（修前 `1 failed, 1 passed`）
3. victim先：`2 passed in 4.25s`（修前 `1 failed, 1 passed`）
4. 定seed随机序（`-p pytest_order_control --order-seed=20260927` 与 `--order-seed=7 --order-reverse`）：均 `2 passed`
整文件级复核：victim文件+polluter两序均 `55 passed, 3 subtests passed`（修前victim先为 `6 failed, 49 passed`）；`test_source_registry.py + victim` 对照亦绿。
teardown/资源释放：每步为有界子进程、正常退出码0收尾；步间独立私有runtime，无跨步状态（回归测试内建该断言语义）。

工具：新增零依赖排序插件 `tools/acceptance/pytest_order_control.py`（`--order-reverse` / `--order-seed=N`，`-p pytest_order_control` 加载，符合A13不装依赖）。定seed随机序只证该seed稳定，非全排列安全（seed已记录）。

## 六、A03附注（独立漂移，严格分离，不入本A11证据）

`tests/test_medical_writing_synopsis_import.py::SynopsisAsyncJobTest::test_cold_recovery_missing_or_changed_route_is_non_retryable` **单独连跑呈flake**：同命令5连跑=pass/fail/pass/fail/pass（约半数失败），失败断言 `['failed','failed'] != ['pending','pending']`（recover_stale_jobs未将两任务归类为failed）。无polluter参与、同env下结果波动 ⟹ 与本A11导入期污染**不同根因**，疑似stale判定阈值与时钟竞态。未在本Pass修复（范围边界），移交集成人/后续批单独诊断；不得自动归KNOWN（红线2/A03）。

## 七、债务边界（不带owner不收口）

- 跨测试导入面：`rg -c "from tests\." tests/*.py` 命中55个文件。本轮证明其中真正引爆点是被导入模块的**导入期副作用**（本例=app.main播种设置），而非跨导入本身。未做大扫除；后续任何测试文件新增 `from services.api.app.main import …` 的导入链，都会把设置播种进会话runtime——凡依赖"设置不存在"的用例都应显式用注入冻结旗标或显式settings路径。owner：实现师（下批FAST车道映射扩展时逐文件核对）。
- 产品侧观察（不改，交集成人）：app.main在**导入期**写 `ai_provider_settings.json/secrets/bindings`（main.py:1840模块级引导，一次导入重复播种8+次）。任何以WORKBENCH_RUNTIME_DIR为隔离边界的测试会话，只要收集中出现过main导入，边界即被"合法产品内容"填充。owner：集成人。
- 定seed随机序覆盖边界见第五节；更多排列需扩展pytest_order_control（复用门修复Plan的插件族）。
