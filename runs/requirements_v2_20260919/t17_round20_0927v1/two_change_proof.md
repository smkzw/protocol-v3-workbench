# 0927V1 §9验收证明：两个连续局部修改周期的FAST车道验证记录

- 执行人：证明员（独立验证，不属实现师链路）
- 执行时间：2026-09-26 20:40–20:46（本地，gate证据目录时间戳为UTC）
- 仓库：protocol-v3-workbench，HEAD=`5b4c8c11692fc3118eb21bfe80877f5ce9d76c65`（与审阅基线一致，已`git rev-parse`核对）
- 车道：`tools/acceptance/run_acceptance_gate.py --plan fast --root . --json --timeout 540`
- 工作树注意：本仓库工作树在验证前已有实现师在途改动（`model_phase_scheduler.py`、`writing_reference_preparation_batch.py`、`run_acceptance_gate.py`、`tests/test_medical_writing_generation_context_v2.py`）。本记录的两处改动只新增于 `services/api/app/chapter_translation_pipeline.py`（不在共享文件清单：非 run_acceptance_gate.py / writing_reference_* / main.py / models.py，且验证前不脏），未回退、未清洗任何他人改动。

## 环境身份（A13，gate自动记录）

| 项 | 值 | 来源 |
|---|---|---|
| python | 3.14.7（homebrew框架，无仓库venv） | gate `toolchain_identity` |
| package-lock sha256 | `d2b3016…3c237a` | gate `toolchain_identity` |
| python_lockfile | none_in_repo（如实记录） | gate `toolchain_identity` |
| 依赖安装 | 三轮全部 `install_actions: []` | gate JSON |
| deps_unchanged | 周期1=True、周期2=True（与2026-09-26T19:09Z记录身份逐字段相同） | `runs/acceptance_gate/lane_state.json` |
| 离线审计（A10/A16） | 三轮 `offline_audit.clean=true`；父环境代理变量 `NO_PROXY/no_proxy` 被剥离，零WORKBENCH_AI_*/端点泄漏 | gate `offline_audit` |
| 服务 | FAST车道零服务启动/重启；5301 uvicorn无`--reload`（ps核实），源码编辑不触发任何用户服务动作；8910/8001/8002未触碰 | ps 现场核实 + lane设计 |
| 模型 | 零模型冷启/调用（离线选择车道） | gate `offline_audit` |

## 周期0：改动前基线（归因锚点）

在动手前先跑一次FAST，把"当时工作树"的失败集合固定下来，用于逐项归因：

- run：`runs/acceptance_gate/run_2026-09-26T204037Z_27477`
- 结果：421 ran，18 failed，8 skipped，0 collection error，verdict=FAIL
- 18项失败全部位于 `tests/test_writing_reference_preparation_batch.py`（对应实现师在途G2改动的模块）；`tests/test_chapter_translation_pipeline.py` 零失败
- 失败清单快照：`two_change_failed_cycle0.txt`

## 周期1：小改动1——诊断文案补上出错值

**改动内容**（`services/api/app/chapter_translation_pipeline.py:254`）：

```diff
 def enforce_ocr_concurrency(max_workers: int) -> int:
     """Clamp OCR concurrency to the 1..8 range."""
     if max_workers < 1:
-        raise ValueError("OCR concurrency must be at least 1")
+        raise ValueError(
+            f"OCR concurrency must be at least 1, got {max_workers}")
```

**反例先证缺陷（改动前实测）**：输入 `0` 与 `-3` 抛出完全相同的报错——出错值丢失：
```
BEFORE input=0:  ValueError('OCR concurrency must be at least 1')
BEFORE input=-3: ValueError('OCR concurrency must be at least 1')
```
改动后实测：`got 0` / `got -3` 可区分；边界行为不变（16→8，1→1）。

**测试影响核查**：全仓库仅此一处出现该文案；`tests/test_chapter_translation_pipeline.py:199/203` 用裸 `assertRaises(ValueError)`（不断言消息原文），`:206 test_one_is_valid` 锁定 `enforce(1)==1`——现有正负测试全部继续有效，未改任何断言，未新增skip/xfail。

**FAST选择理由**：`chapter_translation_pipeline.py` 命中 `lane_triggers.json` 前缀映射 → `tests/test_chapter_translation_pipeline.py`；另含工作树其余在途文件的映射/惯例测试 + 16个 always_selected 安全哨兵（`lane_triggers.json` + gate `selected_reasons`）。选择为显式映射，非 `--lf`（gate `last_failed_only: false`）。

**验证记录**：run `run_2026-09-26T204302Z_27801`；421 ran，18 failed（与周期0失败集合**逐项相同**：0新增、0消失），本模块测试全绿；elapsed：gate总86.742s（pytest子进程86.58s），`/usr/bin/time` 实测墙钟86.89s。

## 周期2：小改动2——常量提取（下界1 → 命名常量）

**改动内容**（同文件 :39 与 :253-257，行为保持）：

```diff
 WRITING_REFERENCE_OCR_MIN_DPI = 200
+WRITING_REFERENCE_OCR_MIN_CONCURRENCY = 1
 WRITING_REFERENCE_OCR_MAX_CONCURRENCY = 8
 ...
-    if max_workers < 1:
-        raise ValueError(
-            f"OCR concurrency must be at least 1, got {max_workers}")
+    if max_workers < WRITING_REFERENCE_OCR_MIN_CONCURRENCY:
+        raise ValueError(
+            f"OCR concurrency must be at least "
+            f"{WRITING_REFERENCE_OCR_MIN_CONCURRENCY}, got {max_workers}")
```

依循同文件既有 `WRITING_REFERENCE_OCR_MIN_DPI/MAX_CONCURRENCY` 常量惯例（:38-39），上下界从此对称；行为实测与周期1逐字节一致（`got 0`/`got -3`，16→8，1→1）。

**环境未变声明（A13/A14/A16）**：锁文件未变（package-lock sha相同、python相同）→ **零依赖安装、零浏览器下载**；**零模型冷启**（离线审计clean）；**零服务重启**（未启停任何服务，FAST不启动服务，5301/5186/8910进程未受任何信号）。

**验证记录**：run `run_2026-09-26T204502Z_28097`；421 ran，18 failed（仍与周期0逐项相同），8 skipped（全部为 `tests/test_phase1_corpus_source_boundaries.py` 既有skip，三轮数量一致，非本改动引入），0 collection error，`security_sentinel_blocked=[]`、`missing/skipped_required_nodes=[]`；elapsed：gate总86.363s（pytest 86.19s），墙钟86.52s。

## §8 阶段计时（三轮实测，秒）

| 阶段 | 周期0(改前) | 周期1 | 周期2 | 来源 |
|---|---|---|---|---|
| env/install | 0.022（install=0） | 0.016（install=0） | 0.015（install=0） | gate `phases.env_check_s`+`install_actions` |
| 服务启动/重启 | 0 | 0 | 0 | 车道设计+现场ps |
| 模型加载/排队 | 0 | 0 | 0 | offline_audit |
| selection | 0.148 | 0.115 | 0.124 | gate `phases.selection_s` |
| collection+会话收尾+报告（残差，推导值） | 8.66 | 8.22 | 8.20 | pytest_s − junit用时和（推导，非直接测量） |
| 测试体（junit逐用例用时和，含用例级setup/teardown） | 84.29 | 78.36 | 77.99 | junit.xml |
| pytest子进程墙钟 | 92.95（自报91.70） | 86.58（85.34） | 86.19（84.82） | gate JSON+stdout尾行 |
| gate总墙钟 | 93.156 | 86.742 | 86.363 | gate `phases.total_s` |
| 端到端墙钟（含解释器启动与结果落盘） | 93.31 | 86.89 | 86.52 | `/usr/bin/time -p real` |

**FAST预算实测**：单周期端到端 ≈1.5分钟，P95≤5分钟目标实测满足（本批实测，非承诺外推）。case_time_sum为用例用时之和，非墙钟，二者均列出。

## 重复准备计数（A23）

2个修改周期 + 1个归因基线 = 3次gate调用：依赖安装0次、环境重建0次、模型冷启0次、服务启停0次、pytest子进程每周期1次（设计使然）。

## 诚实边界：未跑什么 / 未通过什么

- **verdict=FAIL（三轮一致），不冒充通过**：18项失败全部属于实现师在途G2模块（`test_writing_reference_preparation_batch.py`），集合与改前逐项比对无新增无消失；本轮两改动不消除也不掩盖该债务。
- 未跑：全量套件（11043项口径）、REPLAY车道、LIVE车道、前端Vitest、lane选择之外的其余模块测试——FAST按设计是部分选择，`not_run_scope` 已由gate如实记录，全库报告保持独立车道。
- 8项既有skip（phase1 corpus边界套件）原样保留，未因本轮改动增加或减少。
- 计时说明：junit不单列collection时长，上表"collection+报告"为pytest墙钟减用例用时和的残差（含解释器与会话收尾），已标注推导。

## 证据文件

- 本目录：`two_change_fast_cycle0_pre.json/.time`、`two_change_fast_cycle1.json/.time`、`two_change_fast_cycle2.json/.time`、`two_change_failed_cycle0.txt`
- gate权威结果：`runs/acceptance_gate/run_2026-09-26T204037Z_27477/`、`run_2026-09-26T204302Z_27801/`、`run_2026-09-26T204502Z_28097/`（各含 result.json/junit.xml/nodeid_report.json/pytest_stdout.log/pytest_stderr.log）
- 代码改动：`services/api/app/chapter_translation_pipeline.py`（+5/−2，仅此一个文件，见上diff）
