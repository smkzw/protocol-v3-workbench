# t17_round25 真实并发压测报告（0928 仲裁机制）

- 执行人：压测员（工作流子代理）
- 日期：2026-09-28 09:34–09:55
- 结论先行：**本轮判定 = 不通过（clean=false）**。排队与驻留窗机制本身按设计工作（121次采样未见双载、2732次在役请求零失败、600秒驻留窗精确生效）；但压测触发了一次"切换中途失败"，机制**不回滚已启动的模型服务器**，导致压测结束后系统进入**持续双载状态（P0，当前仍然存在）**，且让排队10分钟的用户最终收到报错（P1）。

---

## 一、前置：重启 5301 并核对指纹

压测开始前，运行中的 5301（旧 PID 49961，9月27日21:39启动）**早于**仲裁增量代码的修改时间（orchestrator 09:06:40、gateway 09:01:50），确认未加载新机制，按任务授权执行重启：

- 按 round22/23 沿用的 HANDOFF_0924V2_BATCH1 §一配方重启：杀旧监听 → `python3.14 -m uvicorn app.main:app --host 127.0.0.1 --port 5301`，env 五件套照抄（RUNTIME_DIR / AI_SETTINGS / ROLE_SETTINGS 指向 `wp6_0922v2_20260922/real_http_acceptance/isolated_runtime`，WORKFLOW_ENABLED=1，WORKFLOW_DB=real_http_acceptance/protocol_v3_product.sqlite——该库 mtime 9月27日20:15，为现役库）。
- 新进程 PID 7759，09:34:14 启动，晚于全部增量文件 mtime → 已加载新代码。
- `/api/runtime-readiness` = ready:true；`/api/health` 正常；项目数据完好（4个项目、审计链无违例）。
- 行为指纹：重启后首笔托管请求在 actions.log 留下 `[arbiter/switch] 原因=dispatch`（09:36:34），该审计标签只有新版仲裁器能产生，确认 5301 进程内仲裁器已生效。

## 二、压测方法

两个负载全部经 **5301 产品入口**（`POST /api/ai-gateway/probe`）打进 5301 进程内的仲裁器（网关对托管端点的每次分发都包在 `managed_lease` 里，见 ai_gateway.py:1125、1152）：

- 负载甲（翻译相位）：循环探测 profile `translation_body_local_omlx`（oMLX 8001），串行连续循环 600 秒；
- 负载乙（分诊相位）：循环探测 profile `independent_ai__mtplx_qwen38_local`（MTPLX 8002），同一时刻发起；
- 第三线程每 5 秒采样：8001 已加载模型表 + 8002 是否存活，两者同时有模型即记一次双载；
- 全部请求与采样逐条落盘 `concurrency_drill_events.jsonl`。

探针说明：产品探测入口要求模型只回一个最小 JSON（实测返回 `{"status":"ok"}`）；生命周期自身的 A18 载入探针由配置 `probe_max_tokens: 8` 硬上限约束（审计可见 "max_tokens=8"）。

## 三、实测数据（10 分钟窗口）

| 指标 | 实测值 |
|---|---|
| 翻译相位请求 | 2732 次，**全部成功**，单次最长 0.758s |
| 分诊相位请求 | 1 次：09:36:48 进入 FIFO 队列（位置1），等待 **637.04s** 后 **502 报错**（见缺陷B） |
| 切换次数 | 2 次（09:36:34 授予翻译；09:46:49 授予分诊） |
| 单次最长等待 | 客户端视角 637.04s；仲裁器审计"排队后授予"耗时 601.13s |
| 窗口内双载采样 | **0 / 121**（600 秒驻留窗精确生效：09:36:48 排队，09:46:49 即驻留窗期满后第一时间授予） |
| 过载错误 | 窗口内无过载类错误；唯一的失败是切换中止错误（缺陷B） |
| 队列超时(1800s) | 本轮最长等待 637s，未触发 `phase_queue_timeout`，**该报错路径未实测到** |

审计原文（actions.log 81–85 行）：

```
09:36:48 [arbiter/queue] queue_enter | triage@mtplx | 前状态=current=omlx, users=1 | queued at position 1
09:46:49 [arbiter/switch] phase_switch | triage@mtplx | 前状态=current=omlx | granted, queued=0
09:46:49 [arbiter/wait]  queue_grant  | triage@mtplx | granted after wait | 耗时=601.13s
09:46:49 [action/start]  launch_detached | mtplx@8002 | 原因=ensure(triage) server offline
09:47:25 [refused/busy_connections] lifecycle_refusal | omlx | refused: omlx has in-flight work
```

## 四、缺陷清单

### P0-A 切换中途失败不回滚 → 持续双载（当前仍存在）

`ensure()` 的顺序是**先启动目标服务器、再去排空对方**（model_lifecycle_orchestrator.py:713 起，启动在互斥排空之前）。09:46:49 MTPLX 被 launch 后自行加载模型；09:47:25 对 oMLX 的排空被 `busy_connections` 拒绝（见缺陷C），ensure 立即中止——**但已经 launch 出去的 MTPLX 进程无人回收**。实测后果（09:48–09:55 多次直查确认）：

- 8001：Hy-MT2（翻译，约30GB）仍驻留；
- 8002：MTPLX 模型已加载并在服务；
- mtplx_server.log 显示内存已达 **96.6 GB，逼近 100 GB 红线**，预填充已被降级（"4096-row chunk not granted…over the 100.0 GB line"）。

这正是本机制要防的不变量（两模型不得同时驻留）被打破，且**不会自愈**（idle_recycle_seconds=1800 属 MTPLX 块的释放参数，无自动触发点）。**恢复处置未由我执行**：此刻有另一个智能体会话正在经 MTPLX 实时工作（mtplx_server.log 持续新增生成记录），排空 MTPLX 会毁掉他人现场（红线1/3）。需要主会话裁决恢复时机：先静默该会话，再经编排器 `release(triage)` → `ensure(translation)` 收敛回单载。

### P1-B 排队 10 分钟后用户收到报错（承诺"排队不报错不丢弃"被打破）

分诊用户排队 637 秒后，切换在最后一步被拒，错误直接抛给用户：`Managed local model server unavailable: omlx has in-flight work`（502）。排队机制的前半程（FIFO、驻留窗、攒批）都正确，但**切换失败没有兜底**：既不回滚（P0-A），也不重试/改期，把等了最久的用户直接报错。

### P1-C 排空判定"一票否决"且过脆

`_busy_reason`（model_lifecycle_orchestrator.py:524）把三种信号都当作忙碌：网关在途计数、oMLX 活动接口、**8001 端口上的任意已建立 TCP 连接**。最后一项意味着任何旁路连接（管理界面、文档转换 MarkItDown、其他会话、监控探测）都能否决切换。09:47:25 的拒绝即由 `busy_connections` 触发（当时压测两负载均已停止；无法完全归因是采样器瞬时连接还是第三方会话对 8001 的使用，但无论哪种，都属于"旁路连接否决切换"这一脆弱点）。ensure 侧排空是 `wait_for_zero=False` 的**一次性拒绝**（:594–614），不给忙碌信号消散的窗口。

### P1-D（代码推断，本轮未实际观察到）切换失败后驻留窗把两个相位一起冻住

切换失败路径只把 `_current` 清空（:1312），**不复位 `_switched_at`**（:1210 设置）。此后两个相位的新请求都会因"驻留窗未满"继续排队，最长冻结约 10 分钟（到驻留窗期满才有人能再次发起切换）。本轮压测负载在失败前已停止，未观察到此现象，属代码级推断，请实现师复核。

## 五、边界与未尽事项

1. 队列超时报错（`phase_queue_timeout`，1800s）未实测触发——本轮等待最长 637s，未达阈值。该路径的端到端表现本轮**未验证**。
2. 窗口内 0 双载指 5 秒间隔采样的观测结论；MTPLX 模型加载完成发生在最后一个采样（09:46:50）之后，双载成立于压测窗口结束后数十秒内，由事后直查确认。
3. 我的采样器本身每 5 秒会连一次 8001 管理口，理论上可能成为 busy_connections 的触发源之一，无法排除，已在 P1-C 如实标注。
4. 未跑全量测试套件（按分工归每轮收尾脚本）；增量自带的编排器验收测试（tests/acceptance/test_model_lifecycle_orchestrator.py 有修改）由实现师/收尾脚本覆盖。

## 六、证据文件

| 文件 | 内容 |
|---|---|
| `runs/requirements_v2_20260919/t17_round25_loop/concurrency_drill.py` | 压测脚本（双负载+采样器） |
| `runs/requirements_v2_20260919/t17_round25_loop/concurrency_drill_events.jsonl` | 2734 条请求/采样逐条记录 |
| `runs/requirements_v2_20260919/t17_round25_loop/concurrency_drill_summary.json` | 汇总统计 |
| `runs/requirements_v2_20260919/t17_round25_loop/backend_5301_round25_restart.log` | 重启后 5301 运行日志 |
| `runs/requirements_v2_20260919/t17_round25_loop/start_5301_round25.sh` | 重启配方脚本 |
| `runs/requirements_v2_20260919/t17_round21_model_scheduler/actions.log`（81 行起） | 仲裁器审计原文 |
| `runs/requirements_v2_20260919/t17_round21_model_scheduler/mtplx_server.log` | MTPLX 内存压力与第三方会话证据 |
