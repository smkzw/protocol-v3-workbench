# 环境预检第1轮 · OCR 通道现场复测(2026-09-29 13:1x)

## 范围
仅环境侧复核,不改产品代码,不改绑定(绑定已于今晨 10:32 由环境侧改绑完成:
ocr → ocr_local_omlx / GLM-OCR-bf16,revision 10;备份 ai_role_bindings.json.pre-ocr-rebind-20260928 同目录在位)。

## 本轮实测
- 命令:POST http://127.0.0.1:5301/api/ai-gateway/roles/ocr/probe-visual
  body {"profile_id":"ocr_local_omlx","model":"GLM-OCR-bf16"}
- 结果:HTTP 200,visual_probe.passed = true,耗时 277.7 s(见 probe_visual_response_envrecheck1.json)。

## 为什么这次要 277 秒(共存/仲裁行为补充观察)
- 发起探针时 model-lifecycle 状态:arbiter.current=mtplx,MTPLX(8002) inflight=1
  (经 ps 10 秒采样确认是真实推理:cputime 63:30→63:37,5301→8002 有活跃 TCP 连接),
  仲裁队列中有 1 条 phase=translation, server=omlx 的 dispatch 在排队。
- 编排器按"最小驻留+排队"设计等 MTPLX 长任务结束才切回 oMLX;OCR 探针与该翻译
  任务同队等待,轮到后含 GLM-OCR-bf16 冷加载(~10 s)共 277 s 完成。
- 对测试者的含义:语料准入(OCR)或翻译如果撞上综合AI(MTPLX)长任务,等待几分钟
  属预期排队行为,不是卡死;判卡死应以编排器状态(/api/model-lifecycle/status)与
  durable 库为准,而不是以单一请求耗时为准。
- 共存结论维持今晨 mem_probe.md:OCR(GLM-OCR-bf16)与翻译(dawncr0w)同驻 oMLX
  8001,无互斥卸载;本轮新增:与 MTPLX 上的综合AI长任务并发时,由仲裁器排队切换,
  全自动、无需人工干预。

## 红线自检
- 未手动启停任何模型服务器;全部流量经产品 API。
- 未触碰 live 8910 / 医学监查 / 共享 runtime;5301 由 round27 脚本管理,本轮未重启
  (今晨 11:14 重启晚于改绑,绑定经重启后仍在位,本轮健康检查与探针均已验证)。

## 第2轮复测(2026-09-29 20:35)
- POST /api/ai-gateway/roles/ocr/probe-visual → HTTP 200,visual_probe.passed=true,13.3 s(见 probe_visual_response_envrecheck2.json;oMLX驻留无需冷加载,且当时 MTPLX 已按最小驻留释放、队列空,故无排队)。
- 绑定在位:ocr=ocr_local_omlx/GLM-OCR-bf16,revision已随当日任务路由调整升到13(改绑本身于9-29晨完成,备份.pre-ocr-rebind-20260928仍在)。产品代码零改动。

## 第3轮复测(2026-09-30 03:12-03:40)——OCR本地通道被仲裁器 fail-closed 拒止,按主会话裁定记账

### 事实链
1. 环境:HEAD前进至399e7dc(MTPLX start_timeout 120s→900s);5301(23:47:27)与vite(23:47:50)均晚于提交,前后端运行在HEAD上。
2. 本轮OCR探针:POST /api/ai-gateway/roles/ocr/probe-visual → 一次 HTTP 502(107.8s,detail "OCR 视觉能力验证失败:CompositePipelineUnavailableError",见 probe_visual_response_envrecheck3_502.json),一次200s客户端超时(服务端仍在队列,queue_timeout=1800s)。
3. 根因(actions.log,runtime/t17_round21_model_scheduler/actions.log 03:15:07):
   - 排队107.7s拿到切换授权后,lifecycle_refusal:**"refusing to stop a server we do not own: {'owned': False, 'pid': 18233, 'reason': 'process_not_running'}"**,retry×2同拒→fallback triage@mtplx。
   - 实际监听8002的是**25486**(9/29 20:53:51由修复前旧5301经launch_detached启动,PPID=1——399e7dc之前120s超时叠实例的后遗症);5301于23:47重启丢失所有权记忆,identity快照仍指向已死18233(快照失配)。
   - 防双载硬约束要求"停MTPLX才能起oMLX"→停无主进程被所有权护栏正确拒绝→oMLX请求结构性不可用;retest-r2的translation(03:03)同样被拒,经云端fallback(产品合法路径)继续。
4. 判定:所有权护栏fail-closed工作正常(拦下的是危险动作,不是故障);但暴露两个产品缺口(编排器identity快照不随实际监听进程刷新;外部启动服务器无收编端点——内部adopt方法model_lifecycle_orchestrator.py:1070存在但无HTTP入口)。已裁定列入下一轮修订:(i)adopt-by-identity受保护端点(五项前置校核);(ii)identity快照从实际监听进程刷新。

### 裁定与记账口径(主会话2026-09-30 03:4x)
- 25486**不动**:正在服务在途full_draft(durable mwjob_9d216429… running,心跳/租约持续滚动),在途任务依赖的模型不得卸载;任务完结也不主动杀,留下一轮按身份收编。
- OCR本地通道本轮**不算清偿**:L3保持open、标注environment-blocked;绑定(ocr_local_omlx/GLM-OCR-bf16,revision 14)、模型在列(8001 /v1/models 12个含GLM-OCR-bf16)、第1/2轮实测通过(277.8s/13.3s)均在位——配置侧清偿有效,闭环验证顺延到护栏补齐后的下一轮,届时走真正干净的仲裁路径。
- 云端fallback是产品设计合法通道,retest-r2翻译经它继续,不是绕过。

### 红线自检
- 未手动启停任何模型服务器;全部流量经产品API。
- 未触碰live 8910/医学监查/共享runtime;零文件删除。

## 第4轮复测(2026-09-30 10:49)——OCR本地通道闭环验证达成,L3环境侧清偿完成
- 夜间演变:full_draft完成(durable零running/queued),孤儿25486已退出;5301今晨10:08重启(新PID 63003),其10:14拉起新MTPLX(PID 63756,为63003子进程);仲裁器current=omlx、oMLX驻留、队列空。
- 本轮实测:POST /api/ai-gateway/roles/ocr/probe-visual → HTTP 200,visual_probe.passed=true,3.5s(GLM-OCR-bf16/provider=omlx,见 probe_visual_response_envrecheck4_passed.json)。第1/2/4轮三次通过(277.8s排队态/13.3s驻留态/3.5s驻留态),第3轮拒止根因(孤儿MTPLX驻留+identity失配)已随进程更替消解。
- 记账:L3(OCR key环境复现缺口)环境侧清偿完成——本地oMLX通道闭环可用,无需PADDLE_OCR_API_KEY;Paddle云端profile保持原状(缺key不可用,未删除未改动)。
- 遗留观察(不阻塞):编排器identity快照仍记18233(process_not_running),与实际进程(63756)失配——两个产品缺口(adopt-by-identity端点、identity刷新)已由主会话排入下一轮修订;当前arbiter=omlx无切换需求,不影响本轮。
- 环境重启记录:5301(10:08)与vite(retest_r26_vite.log 09:51)今晨均有重启,四端健康与指纹一致性已在重启后复测通过。

## 第5轮复测(2026-09-30 15:39)——identity缺口拒止复现(已知,按第3轮裁定口径记账)
- HEAD前进至64841c2(13:28,编排器探针认证修复:裸/health被401误读离线致2h+重启循环)+612ee3b(测试产物清理纪律,655MB,DB行未动);5301(15:27)与vite(14:43)均晚于提交,指纹一致复测通过。
- 绑定在位:ocr=ocr_local_omlx/GLM-OCR-bf16 revision 15,备份在。durable零在跑(completed=176/failed=99)。
- 本轮实测:POST probe-visual → HTTP 502(136.1s)。actions.log 15:42:27与第3轮同根因:排队136s拿到授权后"refusing to stop a server we do not own: pid 18233(process_not_running)"×2→fallback triage@mtplx。64841c2修的是健康探针认证,identity快照刷新/收编(修订项i/ii)尚未落地——MTPLX(63756,无主驻留)存在期间切oMLX仍被拒。
- 记账口径不变:OCR本地通道配置在位、第4轮黄金窗口3.5s通过为L3闭环证据(ocrFixed=true按配置+闭环口径);本轮502为已知identity缺口复现,非新缺陷,修订项已在主会话下一轮队列。出现条件已知:仅当MTPLX驻留期发起oMLX请求;arbiter已在omlx时无此问题。

## 第6轮复测(2026-09-30 19:51-19:58)——identity缺口拒止第3次复现(口径不变,附新事实)
- 前置:HEAD前进至a7ce3d8(16:06,修MTPLX网关401凭证/ollama-cloud 404/探针认证;**identity快照刷新与adopt端点(第3轮裁定修订项i/ii)不在本提交**)。5301(PID 46279,18:40:48)晚于提交,lsof证实其打开isolated_runtime三库与本日志,指纹一致。
- 绑定在位:ocr=ocr_local_omlx/GLM-OCR-bf16 revision 15,enabled,specialized_whitelisted,备份.pre-ocr-rebind-20260928在。
- 本轮实测:POST probe-visual → HTTP 502(426.1s,CompositePipelineUnavailableError,见 probe_visual_response_envrecheck6_502.json)。actions.log 19:58:07与第3/5轮逐字同根因:queue_grant after wait 425.95s→lifecycle_refusal×2 "refusing to stop a server we do not own: pid 18233(process_not_running)"→requeue(重试预算仍在滚,同队translation任务继续重试)。
- 记账口径不变(第4轮已闭环):L3环境侧清偿以配置在位+第4轮3.5s黄金窗口通过为准;本轮502=已知identity缺口在"MTPLX驻留期发起oMLX请求"条件下的第3次复现,非新缺陷,修订项在主会话下一轮队列。对测试者的现实含义:**本轮测试若MTPLX正驻留(综合AI在跑),语料准入OCR/参考翻译会先排队~7分钟再吃502回落云端fallback或报错;测试者遇此应记录现场并继续用云端fallback路径,不判产品缺陷**。
- 另:本轮预检时durable有3条running(租约至19:57Z+8=本地,proj_user_2642f55142f1研究流水线翻译阶段80%、proj_user_97189da36a75 AI候选校验60%),属r5/retest-r5活动期在跑任务,非卡死(租约未过期、有阶段进度)。
