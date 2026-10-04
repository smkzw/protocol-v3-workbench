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
