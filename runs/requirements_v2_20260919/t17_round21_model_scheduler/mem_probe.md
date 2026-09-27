# 内存基线实测（t17_round21 模型员侦察）

日期：2026-09-27 ｜ 机器：M5 Max / 128GB 统一内存 ｜ 全部数字为当日实测，非估算。
审计流水：同目录 `actions.log`（9条）。

## 关键教训
- `ps` RSS 完全不可信：omlx-server 加载29.83GB模型时 RSS 仅350MB。
- **唯一可信口径**：oMLX 用 `phys_footprint`（`footprint <pid>`）与引擎自报（`/admin/api/activity` 的 actual_size）；MTPLX 同样用 `phys_footprint`。

## oMLX @8001（v0.7.0rc1，uptime 37h+）
| 状态 | phys_footprint | 引擎自报 |
|---|---|---|
| 0模型驻留（基线） | 221 MB | model_memory_used 0B |
| 翻译模型驻留 | 30 GB | actual 29.83 GB（est 31.25GB） |
| unload后 | 226 MB | 0B |

- 冷加载：**3.93s**（31.25GB，chat请求内 `model_load_duration:3.93`）；卸载：**0.47s**（POST /admin/api/models/{id}/unload）。
- 历史峰值 `phys_footprint_peak: 31GB`（本进程只载过~30GB级模型）。
- 引擎内存守卫（`/admin/api/activity`）：上限 **100.73GB**，soft **90.8GB** / hard **95.8GB**，当前 level=ok。
  `~/.omlx/settings.json`：tier=balanced、soft/hard 阈值比 0.85/0.95、prefill_safe_zone_ratio 0.8（文件里 custom_ceiling_gb=60 与 live 值不一致，live 为准）。
- **每模型空闲TTL已内建**：加载后 `ttl_remaining_seconds≈1788s`（默认1800s自动卸载），`idle_seconds` 持续上报，`ttl_seconds` 可按模型在 admin settings 覆盖。
- 目录12模型均未驻留；MarkItDown 常驻(0B级helper)。

## MTPLX @8002（v2.12.0，native MTP turbo）
- 服务端启动到 `/v1/models` 200：**~21s**（nohup CLI 冷启）；后台warmup 3.7s（81.8 tok/s）。
- Flash-Next-Speed 模型驻留：**phys_footprint 80GB（peak 81GB）**，盘上107GB（mmap分页）。
- 加载后系统空闲 21%（≈27GB）；`allow_swap=False`。
- **quickstart 默认验证模型 `Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed` 未缓存**，必须显式 `--model ~/.mtplx/models/...`。另一缓存模型 27B-Quality 盘上28GB（未测驻留）。

## 策略含义（阈值候选，待实现师进配置文件）
- 翻译29.83GB + 分诊80GB ≈ 110GB > 128GB−工作台占用 → **两模型互斥共存不可行**（与 model_phase_scheduler.py:3 docstring 一致，首次拿到实数）。
- oMLX 同名分诊模型 est 112.49GB > oMLX上限100.73GB → 分诊模型永远不得经oMLX加载。
- oMLX 空闲卸载可依赖内建TTL(~30min)或显式unload API；MTPLX 无per-model TTL信号，卸载=停daemon（`mtplx stop --port 8002`）。
- 卸载前在途检查：oMLX 用 `/admin/api/activity`（total_active/waiting_requests + 每模型 active_requests）；MTPLX 侧未见等价计数端点（其 /health 无队列字段），需保守策略或轮询连接。
