# R27 环境预检与清洁 · 第2轮证据（2026-10-03 11:0x CST，环境管理员，本ask内实跑）

## ① 四端健康
- 后端 5301：pid 80298（2026-10-03 10:59:23 起）`GET /api/health`→`status=ok`（runtime_store integrity ok、FK违规0、schema 16）；`/api/runtime-readiness`→`ready=true` 无缺失能力。
- 前端 5186：HTTP 200；vite pid 80352，进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`；经 5186 代理读 `/api/health`=ok 与直连一致。
- 构建指纹：5186 `/runtime-build.json` 期望 `api-10e0e7d71a1e4394` == 后端自报 `api-10e0e7d71a1e4394`（较第1轮的 api-ccfb725… 已随新代码变更，两侧一致即通过）。按 HANDOFF_0930_PAUSE.md 教训2（实现师交付后须重启+指纹核对），本轮后端/前端已于 10:59–11:00 重启且指纹一致，满足该硬门。HEAD=`2dfd8f2`（2026-10-02 00:41，≥f72fa95）。
- 编排器：`GET /api/model-lifecycle/status`→`status=ok`；omlx healthy（非驻留）、mtplx healthy+resident（owned pid 70309）、队列空 inflight=0。arbiter=null——后端 3 分钟前刚重启、仲裁状态首次AI活动前未初始化，端点自报 status=ok，非异常。

## ② 测试者环境隔离
- ego-browser：仅剩 1 个**用户自有**空间（id 3 R11C 医学监查子系统验收，ownership=user）→按红线保留；agent 空间 0 个（第1轮测试者收尾清理到位，无需关闭）。
- headless 残留：唯一 headless 进程为共享 Camoufox MCP 实例（pid 80100，父进程 842=camofox-browser/server.js，用户基础设施）——`camofox_list_tabs`→`tabs: []` 零测试残留标签。其余 chrome 类进程均用户自备应用。无测试遗留进程可杀。
- 【如实上报·非本岗四端、未触碰】live 8910 当前无监听者（lsof/netstat/ps 三重复核），5177/5178/5195 亦无监听；第1轮现场它们均在。按红线"不碰 live 8910"，本管理员只记录不处置，请主会话酌情知会其属主。

## ③ 上轮缓存清理
- t17_round27_loop 扫描（*.tmp/.DS_Store/__pycache__/tmp* + 第1轮收尾 18:35 后新文件）：新文件仅 4 个——backend_5301_round27_restart.log（运行中后端实时日志）、backend_5301_restart_after_r8_fixes.log、vite_5186_restart_20261003.log、HANDOFF_0930_PAUSE.md（交接档），均为证据/日志，**零删除**（守不清历史红线）。

## ④ durable 无卡死任务
- `sqlite3 isolated_runtime/medical_writing_durable_jobs.sqlite3`（运行中5301实际 WORKBENCH_RUNTIME_DIR）→ completed=241 / failed=137 / cancelled=1 / **非终态=0**（较第1轮 completed 217→241，系第1轮测试正常增量）。

## ⑤ OCR 环境侧清偿（第2轮复核）
- key 缺失复核：`grep -ci PADDLE ~/.config/cms-medical-workbench/ai-runtime.env` → 0（PADDLE_OCR_API_KEY 仍不存在，维持主会话裁决路线）。
- 绑定：`ai_role_bindings.json` revision 18，ocr 角色=`ocr_local_omlx/GLM-OCR-bf16` enabled、capability=specialized_whitelisted；备份 `.pre-ocr-rebind-20260928` 仍在。
- 实测：`POST /api/ai-gateway/roles/ocr/probe-visual`（经运行中 5301 产品 API）→ HTTP 200 / 8.72 s，roles[ocr] available+ready。耗时较长系 HEAD 2dfd8f2 记录的 idle-recycle：GLM-OCR-bf16 空闲被回收后按需冷加载——编排器按需加载路径实测有效。证据：`ocr_probe_visual_r2.json`。
- 无需重启 5301（绑定随 10:59 重启已生效）。oMLX 共存结论见 `../ocr_rebind_20260929/mem_probe.md`（09-29/10-01 两节）。

## ⑥ 新场景冒烟（第2轮）
- ego-browser 真实浏览器（space 9，用后即关）：打开 5186 →『新建项目』→ 对话框『新建医学写作项目』打开，建项方式/试验药物/适应症/研究分期四要素俱全 → 不提交关闭 → 项目数 UI 与 API 均仍 87，零新建。
- 证据：`smoke_r2_home_snapshot.txt`、`smoke_r2_dialog_open_snapshot.txt`、`smoke_r2_dialog_closed_snapshot.txt`（关闭后快照中对话框 0 命中）。

## 红线自检
未碰 live 8910（仅只读探测并上报）/医学监查/共享runtime；模型服务器只经编排器（探针走产品API）；未清库未删历史；本轮未关闭任何他人浏览器空间。
