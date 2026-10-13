# mem_probe · oMLX(8001) 双模型共存实测（2026-09-29）

## 背景
OCR 角色由 `ocr_paddle_official`（PaddleOCR 云端）改绑为 `ocr_local_omlx`（GLM-OCR-bf16 @ http://127.0.0.1:8001/v1）。
翻译模型 `dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX`（translation_body 角色）同驻 oMLX(8001)。
主会话要求实测两者关系（能否共存 / 谁加载时谁卸载）。

## 实测序列（全部经产品自身 API 发起真实推理，未手工触碰模型服务器生命周期）

| 时刻 | 动作 | oMLX server RSS | 响应耗时 |
|---|---|---|---|
| 10:28 前 | 冷态（探针前） | 53 MB | — |
| 10:28:27–10:28:38 | OCR 视觉探针 #1（GLM-OCR-bf16 读图 "CMS VISION 7429"）→ **passed** | 33,042 MB（含首次加载） | 11.06 s（含约 10 s 冷加载） |
| 10:30:40–10:30:41 | 翻译探针（dawncr0w 结构化输出 {"status":"ok"}）→ **passed** | 33,043 MB | 0.55 s |
| 10:31 | OCR 视觉探针 #2 → **passed** | 33,044 MB | 0.40 s |

证据文件：`probe_visual_response.json`、`probe_visual_response_round2.json`、`translation_probe_response.json`、`mem_before_translation.txt`、`mem_after_translation.txt`（同目录）。

## 结论
1. **共存，无互斥卸载**：OCR（GLM-OCR-bf16）与翻译（dawncr0w）交替调用均成功，翻译调用后 OCR 复测仍亚秒级（0.40 s）通过；服务器 RSS 全程稳定在 ~33 GB，未出现"谁加载谁卸载"的跷跷板现象。oMLX 服务器内部自行完成多模型服务/按需加载，首次冷加载 GLM-OCR-bf16 约 10 s，此后驻留。
2. **对流水线的含义**：语料准入（OCR）与参考翻译（translation_body）在同一阶段先后触发时，无需人工干预模型切换；两角色绑定均指向 8001，由同一服务器承接。
3. **phase 感知管理现状（按授权只记录，不加代码）**：模型生命周期编排器（/api/model-lifecycle/status）当前以"服务器"为管理粒度（8001 oMLX / 8002 MTPLX 的健康、驻留、仲裁），不感知服务器内部的多模型驻留；`binding_flags.translation_body=ok`、triage/design=binding_disabled。本次探针流量使仲裁器 current 从 mtplx 切到 omlx，MTPLX(8002) 随后按"最小驻留"策略被编排器正常释放（owned=false、reason=process_not_running、release_unconfirmed=false、无 inflight/draining 残留；8002 无监听）——这是已压测验证的全自动设计行为，AI 任务需要时将自动重启，非异常。若后续语料准入+翻译高并发场景出现 8001 内部模型频繁冷加载拖慢流水线，可考虑（本轮不做）把 OCR 专用模型的驻留纳入 phase 感知或延长最小驻留窗口。

## 红线自检
- 未手工启停任何模型服务器；全部流量经产品 API（probe-visual / ai-gateway probe）。
- 未触碰 8910 live、医学监查、共享 runtime。
- 本轮启动的 5301 仍由 round27 脚本管理，日志延续 backend_5301_round27_restart.log。

---

# 复测 · 2026-10-01 18:09–18:10（R27环境预检·第1轮，环境管理员）

绑定状态延续核验：`ai_role_bindings.json`（revision 15）ocr 角色 = `ocr_local_omlx / GLM-OCR-bf16`（enabled，capability_status=specialized_whitelisted）。改绑产物经 r4–r8 多次重启后仍在生效，本轮无需再改绑定/重启（改绑备份 `ai_role_bindings.json.pre-ocr-rebind-20260928` 仍在）。

实测序列（全部经产品自身 API，运行中 5301 pid 19523；探针前 oMLX(8001) 已监听但 GLM-OCR-bf16 未驻留，RSS 0.04 GB）：

| 时刻 | 动作 | oMLX server RSS | 响应耗时 |
|---|---|---|---|
| 18:09:29–18:09:47 | OCR 视觉探针 #1（读图 "CMS VISION 7429"）→ **passed** | 16.29 GB（含 GLM-OCR-bf16 冷加载） | 17.84 s |
| 18:10:08–18:10:09 | 翻译探针（dawncr0w 结构化输出 {"status":"ok"}）→ **passed** | 16.29 GB | 0.90 s |
| 18:10:13–18:10:14 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 16.29 GB | 0.87 s |

结论与 09-29 一致：**共存无互斥卸载**，翻译调用后 OCR 热复测仍亚秒级通过；本轮 RSS 峰值 ~16.3 GB（低于 09-29 的 ~33 GB，因翻译模型该次未被重复加载，oMLX 按需加载两模型之一驻留即可承接交替调用）。证据：`../env_precheck_20261001/` 下 `ocr_probe_visual_response.json`、`translation_probe_response.json`、`ocr_probe_visual_round2.json`。

追加（18:2x，环境管理员第1轮复核）：再次经 `POST /api/ai-gateway/roles/ocr/probe-visual`（产品 API、运行中 5301 pid 19523）实测一次 OCR 视觉推理 → HTTP 200 / 0.78 s，roles[ocr] `availability=available、ready=true、capability_status=specialized_whitelisted`（绑定 `ocr_local_omlx/GLM-OCR-bf16`）。距上表翻译探针约 15 分钟后 OCR 仍热态亚秒通过，进一步佐证共存无互斥卸载。证据：`../env_precheck_20261001/ocr_probe_visual_myrun.json`。

---

# 复测 · 2026-10-03 18:14–18:16 CEST（R27环境预检·新一轮第1轮，环境管理员）

绑定状态延续核验：`ai_role_bindings.json` revision 19，ocr 角色 = `ocr_local_omlx / GLM-OCR-bf16`（enabled，capability_status=specialized_whitelisted）；改绑备份 `ai_role_bindings.json.pre-ocr-rebind-20260928` 仍在。PADDLE_OCR_API_KEY 复核仍不存在（`grep -c PADDLE ~/.config/cms-medical-workbench/ai-runtime.env` → 0；运行中 5301 进程环境亦 0 命中），维持主会话裁决路线。运行中 5301（pid 28117，11:32 起）已加载该绑定，无需重启。

实测序列（全部经产品自身 API；探针前 8001 /v1/models 已同时列出 GLM-OCR-bf16 与 dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX，oMLX RSS 32,329,680 KB）：

| 时刻 | 动作 | oMLX server RSS | 响应耗时 |
|---|---|---|---|
| 18:14 | OCR 视觉探针 #1（读图 "CMS VISION 7429"）→ **passed** | 32,329,680 KB | 165 ms（热态） |
| 18:15 | 翻译探针（translation_body_local_omlx / dawncr0w，结构化 {"status":"ok"}）→ **passed** | 32,329,680 KB | 352 ms |
| 18:16 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 32,332,144 KB | 162 ms |

结论与 09-29 / 10-01 两节一致：**共存无互斥卸载**；翻译调用后 OCR 热复测仍亚秒级通过，RSS 全程稳定（~32.3 GB）。证据：`../env_precheck_round1_20261003/` 下 `ocr_probe_visual_r1.json`、`translation_probe_r1.json`、`ocr_probe_visual_r1_round2.json`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改任何产品代码（本节为环境侧验证记录）。

---

# 第2轮复核 · 2026-10-04 15:4x CEST（R27环境预检·第2轮，环境管理员）——实测被环境冲突阻断

绑定侧就绪：`ai_role_bindings.json` revision 23，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted）；PADDLE key 复核仍不存在（密钥文件与运行进程均 0 命中）；备份仍在。

**本轮 OCR/翻译实测无法执行**：8002 被用户自有 MTPLX.app（pid 1203，04:43:21 起）拉起的服务器（pid 1759，04:44:19 起）占用；编排器台账 pid 91607 已于 03:44:00 被自己 SIGTERM，对 1759 判 owned=false 并按设计拒绝停止（refused/server_unowned）。防双载要求切相到 omlx 前先释放 mtplx → 释放被拒 → 所有 omlx 相派发自 05:06 起被拒（fail-closed 设计行为）。OCR 视觉探针实测 HTTP 502 CompositePipelineUnavailableError（0.16s）。8001 本身健康、GLM-OCR-bf16 与 dawncr0w 均在驻留列表——数据路径无恙，纯仲裁切相受阻。已升级主会话裁决（杀 1759 违反"模型服务器只经编排器管理"红线且属用户自有应用，本管理员不处置）。

阻断解除后应重跑本文件既有序列（OCR→翻译→OCR）。上一次完整共存实测：2026-10-03 节（共存无互斥卸载）。证据：`../env_precheck_round2_20261004/`。

---

# 复测 · 2026-10-05 08:08–08:10 CEST（R27环境预检·第3轮，环境管理员）——阻断解除，序列恢复

前情：第2轮（10-04）OCR/翻译omlx相派发被8002外来占用阻断（见上节与 ../DIAG/env_blocker_8002_20261004.md）。本轮只读探测：8002仍被 pid 1759 占用（MTPLX.app 1203 本体已退出，守护化服务器存活，按主会话裁定继续不碰）。**但阻断实际解除**：实现师修订批改动了 `model_lifecycle_orchestrator.py`（当前为未提交工作树状态，指纹 api-9e5511fbd42397bf 前后端一致）——切相不再要求先停不拥有的服务器（actions.log 08:05:41 phase_switch translation@omlx granted，无 refused/server_unowned；双服务器并存由 identity/exclusion/memory 前置校核把关）。

实测序列（全部经产品自身 API、运行中 5301 pid 18213）：

| 时刻 | 动作 | 结果 | 耗时 |
|---|---|---|---|
| 08:08 | OCR 视觉探针 #1（读图 "CMS VISION 7429"） | **passed**（capability_verified_at 同步更新 2026-10-05T06:09:44Z） | 1797 ms |
| 08:09 | 翻译探针（dawncr0w，结构化 {"status":"ok"}） | **passed** | 255 ms |
| 08:10 | OCR 视觉探针 #2（翻译后热复测） | **passed** | 118 ms |

共存结论与 09-29/10-03 节一致：无互斥卸载，翻译后 OCR 热态亚秒通过。本轮 oMLX(8001) RSS ~9.0 GB（低于 10-03 的 ~32.3 GB，当前驻留权重组合不同，如实记录）；8001 模型列表中 GLM-OCR-bf16 与 dawncr0w 并存。绑定 revision 26，ocr=ocr_local_omlx/GLM-OCR-bf16 enabled+specialized_whitelisted；备份仍在；PADDLE key 复核仍不存在（文件与进程均 0 命中）。证据：`../env_precheck_round3_20261005/`。

备注（非本岗问题，如实记录）：actions.log 08:05:41 显示一个 translation@omlx 派发排队等待 600.05s 才获相——与已立案 P2（跨相队头等待/客户端耐心）同型，非新回归。

红线自检：未杀任何进程、未动 1759/MTPLX 遗留、全部流量经产品 API、未改产品代码。

---

# 复测 · 2026-10-05 16:38–16:50 CEST（R27环境预检·第3轮，环境管理员）——8002阻断解除后恢复

背景：第2轮的 8002 环境阻断（用户自有 MTPLX.app 占用，见 ../DIAG/env_blocker_8002_20261004.md）已解除——用户侧旧应用进程不在，16:33:37 编排器自己 launch_detached 拉起 mtplx（pid 50555，owned=true），防双载仲裁恢复正常。

绑定核验：`ai_role_bindings.json` revision 27，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted）；PADDLE key 复核仍不存在（密钥文件/运行进程均 0 命中）；备份仍在。

实测序列（全部经产品 API；首探针恰逢 mtplx 最小驻留窗口，入队 16:38:19→16:43:36 放行（317s，已立案 P2 跨相等待设计行为，客户端 300s 超时属正常），放行后编排器停 mtplx、oMLX 相就位）：

| 时刻 | 动作 | oMLX server RSS | 响应耗时 |
|---|---|---|---|
| 16:48 | OCR 视觉探针 #1（读图 "CMS VISION 7429"）→ **passed** | ~33.9 GB | 125 ms（热态） |
| 16:49 | 翻译探针（translation_body_local_omlx / dawncr0w，结构化 {"status":"ok"}）→ **passed** | 33,938,400 KB | 275 ms |
| 16:49 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,938,400 KB | 99 ms |

结论与 09-29 / 10-03 各节一致：**共存无互斥卸载**；8001 /v1/models 同时列出 GLM-OCR-bf16 与 dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX（co_resident=true），RSS 稳定。证据：`../env_precheck_round3_20261005/`（ocr_probe_visual_r3_1.json、translation_probe_r3.json、ocr_probe_visual_r3_2.json）。

附注（对测试者的含义）：跨相任务（如刚跑完初稿再进语料翻译）可能遇到 5–10 分钟的最小驻留排队（本序列实测 317s），属既知 P2（客户端耐心 vs 服务端队列）设计行为，非本环境异常。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动用户 MTPLX.app。

---

# 复测 · 2026-10-05 22:36–22:44 CEST（R27环境预检·第4轮，环境管理员）

绑定核验：`ai_role_bindings.json` revision 31，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted）；PADDLE key 复核仍不存在（密钥文件/运行进程均 0 命中）；备份仍在。

实测序列（全部经产品 API；探针#1入队等 mtplx 最小驻留+切相+GLM-OCR冷加载合计349s，属既知P2跨相等待设计行为）：

| 时刻 | 动作 | oMLX server RSS | 响应耗时 |
|---|---|---|---|
| 22:37–22:43 | OCR 视觉探针 #1 → **passed** | ~33.9 GB | 349.2 s（含排队/切相/冷加载） |
| 22:43 | 翻译探针（dawncr0w，{"status":"ok"}）→ **passed** | 33,923,088 KB | 323 ms |
| 22:44 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,923,088 KB | 106 ms |

结论与历轮一致：共存无互斥卸载（GLM-OCR-bf16 与 dawncr0w 同驻 8001，co_resident=true）。证据：`../env_precheck_round4_20261005/`。

附注：本轮预检期间 durable 有2个活跃任务（research_pipeline+competitor_triage，22:17 UTC起，心跳实时、租约有效）——非卡死，系第3轮收尾自检在跑；探针#1的排队等待部分源于与它们的跨相互斥，符合设计。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码。

---

# 复测 · 2026-10-06 04:43–04:56 CEST（R27环境预检·第5轮，环境管理员）

绑定核验：revision 34，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted）；PADDLE key 复核仍不存在；备份仍在。

实测序列（经产品 API）：探针#1排队541s获切相（mtplx被正常SIGTERM释放）后 **memory_guard 三连拒**（`model_memory_max=26.13GB < est×factor=34.375GB`，评估发生在mtplx刚被杀、~30GB内存尚未回收的同一秒04:52:33）→客户端502；**立即重试即通过**（系统128GB、89%空闲，内存回收后守卫放行，GLM-OCR冷加载+读码7.8s）。此为内存守卫与刚停服务器内存回收的时序竞态（同秒三拒、无退避重评），自愈型，记录为产品侧观察项（本轮不修，环境岗只实测）。

| 时刻 | 动作 | oMLX RSS | 耗时 |
|---|---|---|---|
| 04:43–04:52 | OCR 探针 #1 → 排队541s+memory_guard误拒502（时序竞态，见上） | — | 541s 失败 |
| 04:55 | OCR 探针 #1重试 → **passed**（冷加载+读码） | ~33.9GB | 7.76 s |
| 04:56 | 翻译探针（dawncr0w，{"status":"ok"}）→ **passed** | 33,921,568 KB | 315 ms |
| 04:56 | OCR 探针 #2（翻译后热复测）→ **passed** | 33,921,568 KB | 108 ms |

结论与历轮一致：共存无互斥卸载（co_resident=true，RSS稳定）。证据：`../env_precheck_round5_20261006/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码。

---

# 复测 · 2026-10-06 10:42–10:52 CEST（R27环境预检·第6轮，环境管理员）

绑定核验：revision 37，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted）；PADDLE key 复核仍不存在（文件/进程 0 命中）；备份仍在。

实测序列（经产品 API；探针#1排队+切相+GLM-OCR冷加载合计397s，无memory_guard误拒——上轮竞态未再现）：

| 时刻 | 动作 | oMLX RSS | 耗时 |
|---|---|---|---|
| 10:43–10:49 | OCR 视觉探针 #1 → **passed** | ~33.9GB | 397.3 s（含排队/切相/冷加载） |
| 10:50 | 翻译探针（dawncr0w，{"status":"ok"}）→ **passed** | 33,932,592 KB | 264 ms |
| 10:50 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,932,592 KB | 96 ms |

结论与历轮一致：共存无互斥卸载（co_resident=true，RSS 稳定）。证据：`../env_precheck_round6_20261006/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码。

---

# 复测 · 2026-10-06 17:31–17:45 CEST（R27环境预检·第7轮，环境管理员）

绑定核验：revision 39，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted）；PADDLE key 复核仍不存在（文件/进程 0 命中）；备份仍在。

实测序列（经产品 API；期间mtplx相有活跃full_draft流水线在跑，探针#1排队359.6s后获切相）：

| 时刻 | 动作 | oMLX RSS | 耗时 |
|---|---|---|---|
| 17:32–17:38 | OCR 视觉探针 #1 → **passed** | ~33.9GB | 墙钟 359.6 s（排队+切相+冷加载） |
| 17:39 | 翻译探针（dawncr0w，{"status":"ok"}）→ **passed** | 33,919,760 KB | 281 ms |
| 17:39 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,919,760 KB | 103 ms |

口径附注：探针#1响应内 `elapsed_ms=1266594`（21min）与实测墙钟359.6s不符——该计时自payload构建起跨网关lease排队预算累计，疑含在跑流水线的共享门等待，属计量口径观察项（passed结论不受影响，读码成功方才200）。共存结论与历轮一致：co_resident=true、RSS 稳定。证据：`../env_precheck_round7_20261006/`。

运维帽执行记录（用户指令20261006）：本轮durable仅1条running（protocol_full_draft，16:59Z创建于16:47Z后端重启之后、心跳实时、租约有效，与mtplx inflight=1吻合）——判定为进行中的收尾/验证任务，非卡死非遗留，未行使cancel；如后续轮次发现心跳死亡/租约过期的悬置job，按指令立即POST /jobs/{id}/cancel。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码。

---

# 复测 · 2026-10-06 23:49–2026-10-07 00:02 CEST（R27环境预检·第8轮=运行上限轮，环境管理员）

绑定核验：revision 43，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted）；PADDLE key 复核仍不存在（文件/进程 0 命中）；备份仍在。

实测序列（经产品 API；探针#1排队452.3s获切相——mtplx最小驻留+GLM-OCR冷加载；时序正常无memory_guard误拒）：

| 时刻 | 动作 | oMLX RSS | 耗时 |
|---|---|---|---|
| 23:50–23:57 | OCR 视觉探针 #1 → **passed** | ~33.9GB | 452.3 s（含排队/切相/冷加载） |
| 23:59 | 翻译探针（dawncr0w，{"status":"ok"}）→ **passed** | 33,924,752 KB | 262 ms |
| 23:59 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,924,752 KB | 96 ms |

结论与历轮（09-29/10-03/10-05×3/10-06第6-7轮）完全一致：**共存无互斥卸载**（co_resident=true，RSS 稳定）。证据：`../env_precheck_round8_20261006/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线空间与omp-harness进程。

---

# 复测 · 2026-10-07 07:52–08:05 CEST（R27环境预检·第9轮，环境管理员）

绑定核验：revision 46，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted）；PADDLE key 复核仍不存在（文件/进程 0 命中）；备份仍在。

实测序列（经产品 API；探针#1排队425.5s获切相，时序正常无memory_guard误拒）：

| 时刻 | 动作 | oMLX RSS | 耗时 |
|---|---|---|---|
| 07:53–08:00 | OCR 视觉探针 #1 → **passed** | ~33.9GB | 425.5 s（含排队/切相/冷加载） |
| 08:04 | 翻译探针（dawncr0w，{"status":"ok"}）→ **passed** | 33,921,824 KB | 284 ms |
| 08:04 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,921,824 KB | 102 ms |

结论与历轮一致：共存无互斥卸载（co_resident=true，RSS 稳定）。证据：`../env_precheck_round9_20261007/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线空间。

---

# 复测 · 2026-10-07 10:39–10:52 CEST（R27环境预检·第10轮，环境管理员）

绑定核验：revision 49，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted）；PADDLE key 复核仍不存在（文件/进程 0 命中）；备份仍在。

实测序列（经产品 API；探针#1排队412.5s获切相，时序正常无memory_guard误拒）：

| 时刻 | 动作 | oMLX RSS | 耗时 |
|---|---|---|---|
| 10:40–10:47 | OCR 视觉探针 #1 → **passed** | ~33.9GB | 412.5 s（含排队/切相/冷加载） |
| 10:51 | 翻译探针（dawncr0w，{"status":"ok"}）→ **passed** | 33,924,496 KB | 309 ms |
| 10:52 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,924,496 KB | 107 ms |

结论与历轮一致：共存无互斥卸载（co_resident=true，RSS 稳定）。证据：`../env_precheck_round10_20261007/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线空间。

---

# 复测 · 2026-10-07 18:42–18:56 CEST（R27环境预检·第11轮，环境管理员）

绑定核验：revision 52，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted）；PADDLE key 复核仍不存在（文件/进程 0 命中）；备份仍在。

实测序列（经产品 API；探针#1排队428.2s获切相，时序正常无memory_guard误拒）：

| 时刻 | 动作 | oMLX RSS | 耗时 |
|---|---|---|---|
| 18:43–18:50 | OCR 视觉探针 #1 → **passed** | ~33.9GB | 428.2 s（含排队/切相/冷加载） |
| 18:55 | 翻译探针（dawncr0w，{"status":"ok"}）→ **passed** | 33,919,824 KB | 268 ms |
| 18:55 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,919,824 KB | 97 ms |

结论与历轮一致：共存无互斥卸载（co_resident=true，RSS 稳定）。证据：`../env_precheck_round11_20261007/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线空间。

---

# 复测 · 2026-10-07 21:22–21:34 CEST（R27环境预检·第12轮，环境管理员）

绑定核验：revision 52，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted）；PADDLE key 复核仍不存在（文件/进程 0 命中）；备份仍在。

实测序列（经产品 API；首次探针因证据目录未建丢了响应文件但请求 200/112.9s 通过——排队112.9s（较近几轮短，mtplx驻留未满即获切相），补建目录后热态重跑取证）：

| 时刻 | 动作 | oMLX RSS | 耗时 |
|---|---|---|---|
| 21:23 | OCR 视觉探针 #1（首次，证据文件未落盘）→ HTTP 200 | — | 112.9 s（含排队/切相/冷加载） |
| 21:25 | OCR 探针 #1 重跑取证 → **passed** | ~33.9GB | 136 ms（热态） |
| 21:26 | 翻译探针（dawncr0w，{"status":"ok"}）→ **passed** | 33,916,528 KB | 315 ms |
| 21:26 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,916,528 KB | 110 ms |

结论与历轮一致：共存无互斥卸载（co_resident=true，RSS 稳定）。证据：`../env_precheck_round12_20261007/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线空间。

---

# 复测 · 2026-10-08 08:03–08:05 CEST（新纪元LOOP·环境预检·第1轮，环境管理员）

背景：运行中后端5301（10-07 18:14起）落后于源码树（HEAD 9339a0c2 于10-08 07:42提交），重启5301复验指纹=api-b88acb53b5aff176（=vite /runtime-build.json 期望，ready=true）。绑定核验：重启前后均 revision 59→60，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted，探针落库后 role_revision=60）；PADDLE key 复核仍不存在（ai-runtime.env 0命中、进程环境0命中）；新鲜备份 `ai_role_bindings.json.pre-ocr-rebind-20261008` 已建。

实测序列（全部经产品 API；oMLX pid 2264）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 08:03 | OCR 视觉探针 #1 → **passed**（读码 CMS VISION 7429，HTTP 200 强口径） | 66,752→33,914,912（加载GLM-OCR-bf16） | 9,987 ms（页缓存热加载，较r12的112.9s更快） |
| 08:04 | 翻译探针（dawncr0w Hy-MT2-30B，structured {"status":"ok"}）→ **passed** | 33,916,336（翻译模型载入同进程） | 321 ms |
| 08:04 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,916,496 | **143 ms** |

结论与历轮一致：GLM-OCR-bf16 与翻译模型 dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX 同驻 oMLX 8001 单进程，共存无互斥卸载（co_resident=true，翻译加载后 OCR 热复测 143ms 即证；RSS 稳定微增）。编排器全程经产品 API 仲裁（arbiter=omlx）。证据：`../env_precheck_newera_r1_20261008/`。

如实说明：探针 #1 因调用命令误写同窗内连发两次（首次9,987ms做功、第二次热态复用），保存的证据文件为首次响应；多出的一次调用为只读探针，无副作用。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线空间（ego空间147/157保留）。

---

# 复测 · 2026-10-08 16:36–16:37 CEST（新纪元LOOP·环境预检·第1轮恢复执行，环境管理员）

背景：新纪元r1预检于08:00–08:10完成后工作流中断存档（commit 85afb67f），本ask为恢复执行、逐项重验。后端5301仍为08:00重启的 pid 43270（指纹 api-b88acb53b5aff176 与 vite 期望 MATCH）；ocr 绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（revision 63），备份 `.pre-ocr-rebind-20261008` 在位；PADDLE key 仍不存在（历轮已穷尽排查）。

实测序列（全部经产品 API；oMLX pid 2264）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 16:36 | OCR 视觉探针 #1 → **passed**（visual_probe.passed=true，HTTP 200） | 451,200 → 2,653,952（加载中） | 3,228 ms |
| 16:36 | 翻译探针（dawncr0w Hy-MT2-30B，structured {"status":"ok"}）→ **passed** | 33,958,592（两模型同驻） | 6,746 ms |
| 16:37 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,959,376（稳定微增） | **126 ms** |

结论与历轮一致：GLM-OCR-bf16 与翻译模型 dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX 同驻 oMLX 8001 单进程，共存无互斥卸载（co_resident=true，翻译加载后 OCR 热复测 126ms 即证；RSS 稳定）。证据：`../env_precheck_newera_r1_resume_20261008/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；并行线 ego 空间保留（本ask关闭的仅为本线遗留空间161）。

---

# 复测 · 2026-10-09 04:50–04:51 CEST（新纪元LOOP·环境预检·第2轮，环境管理员）

背景：后端5301已于当日01:45重启（pid 44173，指纹 api-70177dabe5ffaf176 两侧MATCH——vite亦于01:46带显式env重启，pid 44285）；bindings.json 当日04:30有更新（role_revision 63→65），ocr 绑定仍为 `ocr_local_omlx/GLM-OCR-bf16`（specialized_whitelisted，ready=true）；备份 `.pre-ocr-rebind-20261008` 在位。oMLX pid 2264（隔夜后模型未驻留，RSS 464,672KB 起步）。

实测序列（全部经产品 API）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 04:50 | OCR 视觉探针 #1 → **passed**（HTTP 200） | 464,672 → 33,926,336（冷加载GLM-OCR-bf16后双模型驻留态） | 9,877 ms |
| 04:50 | 翻译探针（dawncr0w，{"status":"ok"}）→ **passed** | 33,926,448 | 322 ms（翻译模型自昨夜仍驻留，热响应） |
| 04:50 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,926,608 | **138 ms** |

结论与历轮一致：双模型同驻共存无互斥卸载（co_resident=true）。证据：`../env_precheck_newera_r2_20261009/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；并行线 ego 空间保留。

---

# 复测 · 2026-10-09 19:53–20:01 CEST（新纪元LOOP·环境预检·第3轮，环境管理员）

背景：后端5301/vite均为当日新进程（指纹 api-291fee25254cca4f 两侧MATCH，HEAD 2ca9ba8c）；ocr 绑定仍为 `ocr_local_omlx/GLM-OCR-bf16`（specialized_whitelisted，role_revision=68）；备份 `.pre-ocr-rebind-20261008` 在位。oMLX pid 2264（RSS 472,576KB 冷态起步）；编排器初始 arbiter=mtplx（MTPLX驻留空闲）。

**异常如实记录**：19:54 OCR 探针 #1 客户端300s超时（HTTP=000）——仲裁器 mtplx→omlx 切相排队约6分钟未放行（期间 users 0/0、mtplx inflight=0，队列悬挂 {phase:translation, server:omlx}）；19:58 复查队列已自行放行（arbiter=omlx、omlx resident=true），未动用运维帽强制释放。oMLX 8001 全程直连健康（/v1/models 正常），属编排器切相迟滞而非 oMLX 故障。该"切相最长达6分钟"现象与历轮（秒级）不同，如实上报供实现师侧留意（可能与今日 HEAD 2ca9ba8c 的 E1/E2 根因修复批同源或无关，未下结论）。

实测序列（全部经产品 API）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 20:00 | OCR 视觉探针 #1（重试）→ **passed**（HTTP 200） | →33,917,776（模型已驻留） | 145 ms |
| 20:01 | 翻译探针（dawncr0w，{"status":"ok"}）→ **passed** | — | 314 ms |
| 20:01 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,919,472 | **109 ms** |

结论：双模型同驻共存无互斥卸载（co_resident=true），与历轮一致。证据：`../env_precheck_newera_r3_20261009/`。

红线自检：全部流量经产品 API；未手工启停模型服务器、未动用 release/admin unload（队列自行放行）；未改产品代码；并行线 ego 空间（147/157/184/186/188）未动。

---

# 复测 · 2026-10-10 02:44–02:52 CEST（新纪元LOOP·环境预检·第4轮，环境管理员）

背景：后端5301/vite当日又换新进程对（指纹 api-b7be2365d992b0aa 两侧MATCH，HEAD 仍 2ca9ba8c）；ocr 绑定仍为 `ocr_local_omlx/GLM-OCR-bf16`（specialized_whitelisted，role_revision=72）；备份在位。oMLX pid 2264（RSS 462,224KB 冷态）；初始 arbiter=mtplx、omlx 未驻留、队列空。

**切相迟滞复现（第3轮已上报，本轮确证）**：OCR 探针 #1 服务端耗时 354,587ms（≈5.9分钟，客户端590s窗口内完成未超时）——与第3轮"~6分钟自行放行"一致，mtplx→omlx 切相迟滞为**可复现现象**（对比第1/2轮秒级~10s）。oMLX 8001 直连全程健康；未动用运维帽（探针最终完成）。持续上报供实现师侧核查。

实测序列（全部经产品 API）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 02:45–02:51 | OCR 视觉探针 #1 → **passed**（含切相等待） | 462,224 → 33,921,920 | 354,587 ms（其中切相≈5.9min） |
| 02:51 | 翻译探针（dawncr0w，{"status":"ok"}）→ **passed** | — | 263 ms |
| 02:51 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,923,872 | **124 ms** |

结论：双模型同驻共存无互斥卸载（co_resident=true），与历轮一致。证据：`../env_precheck_newera_r4_20261010/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；并行线 ego 空间未动。

---

# 复测 · 2026-10-11 12:29–12:34 CST（新纪元LOOP·环境预检·第2轮，环境管理员）

背景：后端5301/vite 5186均为当日09:28重启（pid 24818/24907），指纹 api-f2b9c4d4635834d3 两侧一致；ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（role_revision=75），备份 `.pre-ocr-rebind-20261008` 在位。本轮关键前置：探测开始时仲裁器=mtplx（驻留，pid 55611）——验证mtplx驻留下OCR切相无阻断（r2曾发生8002占用阻断，修复后首次在真实驻留场景复验）。

实测序列（全部经产品 API；oMLX pid 25352）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 12:29 | OCR 视觉探针 #1 → **passed**（HTTP 200；含 mtplx→omlx 切相+GLM-OCR-bf16 加载，无 refused/block） | → 33,839,600 | 258,350 ms |
| 12:33 | 翻译探针（dawncr0w Hy-MT2-30B，structured {"status":"ok"}）→ **passed** | 33,840,960 | 273 ms |
| 12:33 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,841,024（稳定） | **128 ms** |

结论：①mtplx 驻留下 OCR 调用经编排器正常切相承接（258s 为切相+冷加载全成本，无占用阻断）——修复行为在真实驻留场景确认；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 单进程共存无互斥卸载（co_resident=true，翻译加载后 OCR 热复测 128ms 即证）；③探针后仲裁=omlx、mtplx 按最小驻留正常卸载（设计内轮换）。证据：`../env_precheck_newera_r2_20261011/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（2/4/6 保留）。

---

# 复测 · 2026-10-11 19:21–19:24 CST（新纪元LOOP·环境预检·第3轮，环境管理员）

背景：源码下午有更新，后端5301/vite 5186于当日18:41成对重启（pid 61011/61097），指纹 api-851543e34ca11483 两侧一致；ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（role_revision=78），备份 `.pre-ocr-rebind-20261008` 在位。探测开始时仲裁器=mtplx 驻留（真实并行场景再次复验）。

实测序列（全部经产品 API；oMLX pid 25352）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 19:21 | OCR 视觉探针 #1 → **passed**（HTTP 200；mtplx→omlx 切相+GLM-OCR-bf16 加载，无阻断） | 64,496 → 33,853,808 | 142,347 ms |
| 19:23 | 翻译探针（dawncr0w，structured {"status":"ok"}）→ **passed** | 33,855,312 | 319 ms |
| 19:24 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,855,552（稳定） | **114 ms** |

结论与历轮一致：①mtplx 驻留下 OCR 切相无阻断（142s 切相+冷加载全成本）；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 共存无互斥卸载（co_resident=true，热复测 114ms 即证）；③探针后仲裁=omlx、mtplx 按最小驻留正常卸载。证据：`../env_precheck_newera_r3_20261011/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（2/11/13/14 保留）。

---

# 复测 · 2026-10-12 00:03–00:06 CST（新纪元LOOP·环境预检·第4轮，环境管理员）

背景：HEAD=e6dec9bd（20261011 checkpoint），后端5301/vite 5186 成对重启（pid 34439/34440），指纹 api-849e9293abf90c1f 两侧一致；ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（role_revision=81），备份 `.pre-ocr-rebind-20261008` 在位。探测开始时仲裁器=mtplx 驻留（真实并行场景）。

实测序列（全部经产品 API；oMLX pid 25352）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 00:03 | OCR 视觉探针 #1 → **passed**（HTTP 200；mtplx→omlx 切相+GLM-OCR-bf16 加载，无阻断） | 57,600 → 33,881,712 | 165,236 ms |
| 00:05 | 翻译探针（dawncr0w，structured {"status":"ok"}）→ **passed** | 33,883,696 | 280 ms |
| 00:06 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,883,904（稳定） | **102 ms** |

结论与历轮一致：①mtplx 驻留下 OCR 切相无阻断；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 共存无互斥卸载（co_resident=true，热复测 102ms 即证）；③探针后仲裁=omlx、mtplx 按最小驻留正常卸载。证据：`../env_precheck_newera_r4_20261012/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（2/11/20/21/23 保留）。

---

# 复测 · 2026-10-12 01:36–01:45 CST（新纪元LOOP·环境预检·第5轮，环境管理员）

背景：HEAD=e6dec9bd，后端5301/vite 5186 又成对重启（pid 71299/71300），指纹 api-ef5970b7761b7b28 两侧一致；ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（role_revision=85），备份在位。本轮多线共享特征显著：并行线 01:24-01:34 完成了 mtplx↔omlx 两个方向切相（等478s/573s获批），01:34:03 切回 triage@mtplx 并卸载 GLM-OCR-bf16/dawncr0w。

实测序列（全部经产品 API；oMLX pid 25352）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 01:36 | OCR 探针 #1 首发入队（translation@omlx position 1）——编排器切相窗口等待中，客户端 300s 超时断开（请求本体留队） | — | >300s（排队） |
| 01:43 | OCR 探针 #1 重发 → **passed**（HTTP 200；切相窗口结束获批+GLM-OCR-bf16 加载一气呵成） | → 33,882,640 | 19,815 ms |
| 01:44 | 翻译探针（dawncr0w，structured {"status":"ok"}）→ **passed** | 33,884,352 | 282 ms |
| 01:45 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,884,720（稳定） | **109 ms** |

结论：①多线共享下 OCR 调用按编排器队列+最小驻留窗口排队承接（本轮实际等待 ~7.3 分钟窗口，与日志中 478s/573s 历史窗口一致，非卡死非阻断）；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 共存无互斥卸载（co_resident=true，热复测 109ms 即证）；③探针后仲裁=omlx、queue 清空、mtplx 按最小驻留正常卸载。如实记录：首发请求因客户端 curl 超时断开但请求本体留队，由重发请求承接完成——对"正式运作时人工负担量"无影响（产品内调用不设 300s 人为超时），但多线高峰时段 OCR 冷启动等待可达数分钟，供测试轮排程参考。证据：`../env_precheck_newera_r5_20261012/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（2/11/20/21/23 保留）。

---

# 复测 · 2026-10-12 04:18–04:27 CST（新纪元LOOP·环境预检·第6轮，环境管理员）

背景：HEAD=e6dec9bd，后端5301/vite 5186 成对重启（pid 18527/18528，前端 buildId 更新为 web-2cc9ef28ddc819de），指纹 api-ef5970b7761b7b28 两侧一致；ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（role_revision=90），备份在位。探测开始时仲裁器=mtplx 驻留、队列空。

实测序列（全部经产品 API；oMLX pid 25352；本轮吸取第5轮教训直接用 590s 客户端超时）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 04:18 | OCR 视觉探针 #1 → **passed**（HTTP 200；mtplx→omlx 切相窗口等待+GLM-OCR-bf16 加载全程一个请求内完成） | 104,976 → 33,893,744 | 478,324 ms |
| 04:26 | 翻译探针（dawncr0w，structured {"status":"ok"}）→ **passed** | 33,895,568 | 290 ms |
| 04:26 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,895,792（稳定） | **112 ms** |

结论与历轮一致：①mtplx 驻留下 OCR 切相在 ~8 分钟窗口内获批（478s 与第5轮实测 7.3 分钟窗口吻合），无阻断无卡死；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 共存无互斥卸载（co_resident=true，热复测 112ms 即证）；③探针后仲裁=omlx、queue 空、mtplx 按最小驻留正常卸载。证据：`../env_precheck_newera_r6_20261012/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（2/11/21/23 保留）。

---

# 复测 · 2026-10-12 09:57–10:05 CST（新纪元LOOP·环境预检·第7轮，环境管理员）

背景：HEAD=d899d198（20261012 checkpoint，R6-writer-node无损暂停），后端5301/vite 5186 成对重启（pid 86027/86028），指纹 api-ef5970b7761b7b28 两侧一致（前端 buildId 更新 web-a41250cfb49f9ab7）；ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（role_revision=93），备份在位。探测开始时仲裁器=mtplx 驻留、队列空。

实测序列（全部经产品 API；oMLX pid 25352；590s 客户端超时）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 09:57 | OCR 视觉探针 #1 → **passed**（HTTP 200；mtplx→omlx 切相窗口等待+加载单请求完成） | 428,400 → 33,895,808 | 420,751 ms |
| 10:04 | 翻译探针（dawncr0w，structured {"status":"ok"}）→ **passed** | 33,897,056 | 287 ms |
| 10:05 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,897,264（稳定） | **98 ms** |

结论与历轮一致：①mtplx 驻留下 OCR 切相 ~7 分钟窗口获批（420s，连续三轮 478s/440s/421s 量级稳定），无阻断无卡死；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 共存无互斥卸载（co_resident=true，热复测 98ms 即证）；③探针后仲裁=omlx、queue 空、mtplx 按最小驻留正常卸载。证据：`../env_precheck_newera_r7_20261012/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（2/11/23 保留）。

---

# 复测 · 2026-10-12 12:21–12:30 CST（新纪元LOOP·环境预检·第8轮，环境管理员）

背景：HEAD=d899d198，后端5301/vite 5186 成对重启（pid 25189/25190），后端指纹更新 api-dc177cd2d247b5fc 两侧一致；ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（role_revision=97），备份在位。探测开始时仲裁器=mtplx 驻留、队列空。

实测序列（全部经产品 API；oMLX pid 25352；590s 客户端超时）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 12:21 | OCR 视觉探针 #1 → **passed**（HTTP 200；mtplx→omlx 切相窗口等待+加载单请求完成） | 67,760 → 33,890,448 | 433,380 ms |
| 12:28 | 翻译探针（dawncr0w，structured {"status":"ok"}）→ **passed** | 33,892,944 | 261 ms |
| 12:29 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,893,328（稳定） | **102 ms** |

结论与历轮一致：①mtplx 驻留下 OCR 切相 ~7 分钟窗口获批（433s，连续四轮 478/440/421/433s 量级稳定），无阻断无卡死；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 共存无互斥卸载（co_resident=true，热复测 102ms 即证）；③探针后仲裁=omlx、queue 空、mtplx 按最小驻留正常卸载。证据：`../env_precheck_newera_r8_20261012/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（23/31/34 保留）。

---

# 复测 · 2026-10-12 13:29–13:38 CST（新纪元LOOP·环境预检·第9轮，环境管理员）

背景：HEAD=d899d198，后端5301/vite 5186 成对重启（pid 46210/46211），后端指纹更新 api-fcd3772c173b7eb7 两侧一致；ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（role_revision=101），备份在位。探测开始时仲裁器=mtplx 驻留、队列空。

实测序列（全部经产品 API；oMLX pid 25352；590s 客户端超时）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 13:29 | OCR 视觉探针 #1 → **passed**（HTTP 200；mtplx→omlx 切相窗口等待+加载单请求完成） | 155,264 → 33,893,120 | 440,672 ms |
| 13:37 | 翻译探针（dawncr0w，structured {"status":"ok"}）→ **passed** | 33,894,688 | 256 ms |
| 13:37 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,894,976（稳定） | **93 ms** |

结论与历轮一致：①mtplx 驻留下 OCR 切相 ~7.3 分钟窗口获批（441s，连续五轮 478/440/421/433/441s 量级稳定），无阻断无卡死；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 共存无互斥卸载（co_resident=true，热复测 93ms 即证）；③探针后仲裁=omlx、queue 空、mtplx 按最小驻留正常卸载。证据：`../env_precheck_newera_r9_20261012/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（23/31 保留）。

---

# 复测 · 2026-10-12 14:28–14:36 CST（新纪元LOOP·环境预检·第10轮，环境管理员）

背景：HEAD=d899d198，5301/vite 延续第9轮进程（pid 46210/46211 未重启），指纹 api-fcd3772c173b7eb7 两侧一致；ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（role_revision=104），备份在位。探测开始时仲裁器=mtplx 驻留、队列空。

实测序列（全部经产品 API；oMLX pid 25352；590s 客户端超时）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 14:28 | OCR 视觉探针 #1 → **passed**（HTTP 200；mtplx→omlx 切相窗口等待+加载单请求完成） | 68,160 → 33,889,104 | 442,788 ms |
| 14:35 | 翻译探针（dawncr0w，structured {"status":"ok"}）→ **passed** | 33,890,640 | 255 ms |
| 14:35 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,891,040（稳定） | **95 ms** |

结论与历轮一致：①mtplx 驻留下 OCR 切相 ~7.4 分钟窗口获批（443s，连续六轮 478/440/421/433/441/443s 量级稳定），无阻断无卡死；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 共存无互斥卸载（co_resident=true，热复测 95ms 即证）；③探针后仲裁=omlx、queue 空、mtplx 按最小驻留正常卸载。证据：`../env_precheck_newera_r10_20261012/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（23/31 保留）。

---

# 复测 · 2026-10-12 16:36–16:44 CST（新纪元LOOP·环境预检·第11轮，环境管理员）

背景：HEAD=d899d198，5301/vite 延续第9轮进程（pid 46210/46211 未重启），指纹 api-fcd3772c173b7eb7 两侧一致；ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（role_revision=107），备份在位。探测开始时仲裁器=mtplx 驻留、队列空。

实测序列（全部经产品 API；oMLX pid 25352；590s 客户端超时）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 16:36 | OCR 视觉探针 #1 → **passed**（HTTP 200；mtplx→omlx 切相窗口等待+加载单请求完成） | 55,952 → 33,888,672 | 459,786 ms |
| 16:44 | 翻译探针（dawncr0w，structured {"status":"ok"}）→ **passed** | 33,890,192 | 249 ms |
| 16:44 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,890,448（稳定） | **89 ms** |

结论与历轮一致：①mtplx 驻留下 OCR 切相 ~7.7 分钟窗口获批（460s，连续七轮 478/440/421/433/441/443/460s 量级稳定），无阻断无卡死；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 共存无互斥卸载（co_resident=true，热复测 89ms 即证）；③探针后仲裁=omlx、queue 空、mtplx 按最小驻留正常卸载。证据：`../env_precheck_newera_r11_20261012/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（23 保留）。

---

# 复测 · 2026-10-12 20:24–20:32 CST（新纪元LOOP·环境预检·第12轮，环境管理员）

背景：HEAD=ffa09237（R6全轮+R7大半证据快照），5301/vite 延续第9轮进程（pid 46210/46211 未重启），指纹 api-fcd3772c173b7eb7 两侧一致；ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（role_revision=110），备份在位。探测开始时仲裁器=mtplx 驻留、队列空。

实测序列（全部经产品 API；oMLX pid 25352；590s 客户端超时）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 20:24 | OCR 视觉探针 #1 → **passed**（HTTP 200；mtplx→omlx 切相窗口等待+加载单请求完成） | 68,432 → 33,900,032 | 457,788 ms |
| 20:32 | 翻译探针（dawncr0w，structured {"status":"ok"}）→ **passed** | 33,891,440 | 338 ms |
| 20:32 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,891,696（稳定） | **123 ms** |

结论与历轮一致：①mtplx 驻留下 OCR 切相 ~7.6 分钟窗口获批（458s，连续八轮 478/440/421/433/441/443/460/458s 量级稳定），无阻断无卡死；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 共存无互斥卸载（co_resident=true，热复测 123ms 即证）；③探针后仲裁=omlx、queue 空、mtplx 按最小驻留正常卸载。证据：`../env_precheck_newera_r12_20261012/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（23[已委托用户]/42/43/44/45/46 保留）。

---

# 复测 · 2026-10-13 01:47–01:51 CST（新纪元LOOP·环境预检·第11轮，环境管理员）

背景：HEAD=ffa09237（R6全轮+R7大半证据快照），后端5301/vite 5186 成对重启（pid 81592/81593），后端指纹更新 api-cf7735154a90b641 两侧一致；ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（role_revision=114），备份在位。探测开始时仲裁器=mtplx 驻留、队列空。

实测序列（全部经产品 API；oMLX pid 25352；590s 客户端超时）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 01:47 | OCR 视觉探针 #1 → **passed**（HTTP 200；mtplx→omlx 切相窗口等待+加载单请求完成） | 66,480 → 33,888,352 | 168,749 ms |
| 01:50 | 翻译探针（dawncr0w，structured {"status":"ok"}）→ **passed** | 33,890,656 | 266 ms |
| 01:50 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,891,008（稳定） | **97 ms** |

结论与历轮一致：①mtplx 驻留下 OCR 切相本轮 169s 获批（较前几轮 420-478s 更快，窗口非固定值而是随活动状态浮动，均在设计内），无阻断无卡死；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 共存无互斥卸载（co_resident=true，热复测 97ms 即证）；③探针后仲裁=omlx、queue 空、mtplx 按最小驻留正常卸载。证据：`../env_precheck_newera_r11_20261013/`。

红线自检：全部流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（42 为入排线已移交用户态，保留）。

---

# 复测 · 2026-10-13 02:55–02:56 CST（新纪元LOOP·环境预检·第12轮，环境管理员）

背景：HEAD=ffa09237；预检发现指纹漂移（后端 81592 自报 api-cf7735154a90b641 落后于源码树期望 api-2d4246c7ddcf6513——实现师在后端启动后又有更新），经历轮判例与产品指引执行 5301 重启（round27 脚本，新 pid 96580），重启后指纹 MATCH。ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库（role_revision=118，重启后加载生效），备份在位。预检时仲裁器=mtplx 驻留、队列空。

实测序列（全部经产品 API；oMLX pid 25352；590s 客户端超时）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 02:55 | OCR 视觉探针 #1 → **passed**（HTTP 200；页缓存热加载） | 98,016 → 33,889,792 | 9,426 ms |
| 02:55 | 翻译探针（dawncr0w，structured {"status":"ok"}）→ **passed** | 33,891,968 | 267 ms |
| 02:56 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,892,240（稳定） | **93 ms** |

结论与历轮一致：①本轮切相窗口极短（9.4s，GLM-OCR-bf16 页缓存热载，窗口浮动特性再次确认）；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 共存无互斥卸载（co_resident=true，热复测 93ms 即证）；③探针后仲裁=omlx、queue 空、mtplx 按最小驻留正常卸载。证据：`../env_precheck_newera_r12_20261013/`。

红线自检：5301 重启经历轮判例授权路径（round27 脚本、TERM 温和退出、重启前 durable 非终态=0 且编排器 users 0/0 队列空确认无任务打断）；全部探针流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（42 用户态保留）。

---

# 复测 · 2026-10-13 08:05–08:06 CST（新纪元LOOP·环境预检·第13轮，环境管理员）

背景：前端 5186（vite pid 81593，env VITE_API_PROXY_TARGET=5301 ✓）与后端 5301（pid 96580，r12 重启后延续）指纹自检即 MATCH（api-2d4246c7ddcf6513 双侧一致），本轮无需重启。ocr绑定 `ocr_local_omlx/GLM-OCR-bf16` 在库未变（role_revision=122，API 实测 roles[ocr] available+ready、current_runnable=true），备份在位。预检时仲裁器=mtplx 驻留、队列空。

实测序列（全部经产品 API；oMLX pid 25352；590s 客户端超时）：

| 时刻 | 动作 | oMLX RSS (KB) | 耗时 |
|---|---|---|---|
| 08:05 | OCR 视觉探针 #1 → **passed**（HTTP 200；页缓存热加载） | 403,392 → 33,870,160 | 8,009 ms |
| 08:05 | 翻译探针（dawncr0w，structured {"status":"ok"}）→ **passed** | 33,876,800 | 264 ms |
| 08:06 | OCR 视觉探针 #2（翻译后热复测）→ **passed** | 33,876,896（稳定） | **123 ms** |

结论与历轮一致：①切相窗口 8.0s（页缓存热载，浮动特性再现）；②GLM-OCR-bf16 与翻译模型同驻 oMLX 8001 共存无互斥卸载（co_resident=true，热复测 123ms 即证）；③探针后仲裁=omlx、users 0/0、queue 空、mtplx 按最小驻留正常卸载（reason=process_not_running，设计内）。证据：`../env_precheck_newera_r13_20261013/`。

红线自检：本轮无服务重启；全部探针流量经产品 API；未手工启停模型服务器；未改产品代码；未动并行线 ego 空间（42 用户态保留、54 医学监查线保留）。
