# 环境预检第2轮 · OCR 通道复测未闭合(2026-10-01 06:00-06:50)

## 结论先行
OCR 本地通道(ocr_local_omlx / GLM-OCR-bf16@8001)**配置侧清偿在位,但本轮实测未通过**。
7 次视觉探针 0 成功;失败模式=gate 正常放行后,8001 收到推理请求但无任何算力活动
(cputime 60 秒仅 +1.7s、RSS 998→785MB 无加载迹象),请求挂至 socket 超时;偶发
(第 6 次)6 秒快速 502,异常被包装为 CompositePipelineUnavailableError
(main.py:1799-1803 把一切底层异常翻译成该类型,内层类型不可见)。

## 配置侧(在位,与 9/29 清偿一致)
- 绑定:ocr → ocr_local_omlx / GLM-OCR-bf16, enabled, specialized_whitelisted, revision 15
  (9/29 12:21 与 9/30 10:49 的后续角色调整未回退 ocr)。
- 备份:ai_role_bindings.json.pre-ocr-rebind-20260928 在位。
- 5301(新 PID 47262,06:16:46 我复启)env 三项仍指向本轮 isolated_runtime
  (WORKBENCH_RUNTIME_DIR / AI_ROLE_SETTINGS_PATH / PROTOCOL_V3_WORKFLOW_DB);
  /api/health 与经 5186 代理的指纹一致(asset_sha256 774ed064…,9 项目)。

## 本轮实测时间线
- 5301 背景:集成人 05:55 重启(50b50da 新代码,--log-level warning,
  日志 backend_5301_restart_after_r4_fixes.log);旧实例 46279 于 01:03 关闭。
- 探针#1(06:00,120s)超时;#2(300s)超时;#3(180s)超时 —— 期间 arbiter
  current=omlx、users={omlx:1}、8001 零连接(handler 未到 HTTP 层)。
- 06:15-06:16 环境侧重启 5301(SIGTERM 50s 未退→SIGKILL;sqlite 数据完好;
  durable 冷恢复正常接续)。**重启未消除故障** → 非残留状态,是确定性阻塞。
- 探针#4(重启后,300s)仍超时。
- 探针#5 + 4 秒采样:request 06:26:06 granted、5301→8001 ESTABLISHED 出现,
  170 秒内 state 停在 granted、无 release → gate/仲裁层正常,**挂点在 8001 侧不响应**。
- 探针#6 + 2 秒采样:6 秒 502 CompositePipelineUnavailableError(快速失败形态)。
- 探针#7(06:35,arbiter 已完全空闲 current=None):200s 超时,8001 cputime +1.7s、
  RSS 反降(998→785MB)→ **8001 收到 GLM-OCR-bf16 推理请求但完全不干活**。

## 关键反证(划定回归窗口)
- retest_r5.md:53 记载 9/30 19:28 OCR 在 oMLX 通道**端到端健康**
  (「OCR 第 26 页完成(全文共 127 页)」页级推进),当时 oMLX server(PID 82672,
  9/30 00:26 启动)与现在同一进程;5301 则是旧实例(代码 ≤a7ce3d8)。
- 夜间变更:01:03 提交 50b50da(仅改 ai_task_runner.py 的 MTPLX 模型身份匹配,
  自述 scope 不含 omlx/ocr)+5301 重启换新代码。ai_provider_settings.json 的
  改动发生在 9/30 16:06(a7ce3d8),早于 r5 健康证据,可排除。
- 8001 侧观察:health 正常、/v1/models 12 模型含 GLM-OCR-bf16、无鉴权
  (空 POST 422 而非 401)、engine_pool loaded_count=0。但推理请求零活动。
- 8002(MTPLX)夜间启用了 key 鉴权(health 现要求 API key);8001 未启用。

## 次生观察(移交实现师/主会话)
- durable 任务 mwjob_d23a6af183208ff7591e71fb(proj_user_17ec55df8a73,
  section_ai_candidate)自 05:56 起停在「调用综合AI」step 3/5,租约持续续期
  (worker 活着),5301 有一条 198.18.0.x:443(用户 TUN 代理 fake-ip)外部连接
  ——云端 fallback 长时间无响应,retest_r26.md:19 预言的「fallback 空耗」
  今晨表现为代理黑洞挂链。该任务不阻塞 OCR 探针路径,但会占住综合AI预算。
- 判定 OCR 通道恢复的验收动作:重发 POST /api/ai-gateway/roles/ocr/probe-visual
  (body {"profile_id":"ocr_local_omlx","model":"GLM-OCR-bf16"}),
  HTTP 200 且 visual_probe.passed=true。
- 职权边界:模型服务器(8001)处置归编排器/集成人;5301 侧自查归实现师(红线4)。
  环境管理员本轮未动模型服务器、未改任何绑定/设置文件。

## 其余预检项(全过)
①指纹一致(经5186=直连5301,8910对照=0项目);②隔离干净(无遗留tab/headless,
ego lite 主程序=用户自有保留);③无可清理项(r1~r5/retest-r1~5/evidence/两份
restart日志全为证据,9/30 已有 cleanup_manifest 口径);④durable 无卡死
(194 completed/116 failed 终态,1 条 running=活租约续期中);
⑥冒烟过(新建项目对话框开/关未提交,截图在案)。
