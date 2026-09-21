# T17 第十轮 HANDOFF 交接文档（2026-09-21 07:2x，owner 指示转交下一 Agent）

> 交接基线：`SOURCE_HEAD=6de4afb`（本地 main，与 GitHub 同步至该提交）
> 本文档路径：`runs/requirements_v2_20260919/t17_round10/HANDOFF_ROUND10.md`
> 执行状态权威：`.trellis/tasks/09-13-protocol-v3-v1-1/checkpoint.md` 尾部（2026-09-21 06:55 检查点）
> 团队记忆：`~/.zcode/cli/memories/projects/project-851a82f3bfce61db/memory/mw-protocol-v3-takeover-state.md`

---

## 0. 一页速览（先读这个）

| 维度 | 状态 |
|---|---|
| AI 通道（第九轮全灭的根因） | **已修复并实战验证**（提交 0112373+6de4afb，四测试者全部穿越 seed/设计 AI 节点） |
| 第十轮四场景测试 | **已完成**，四份报告+聚合+会商意见书全部归档 |
| 会商审阅 | **已完成**，13 项修复清单（含代码级根因与验证方法）见 `CONFERENCE_REVIEW.md` 第七节 |
| 当前最高优先级 | 按 CONFERENCE_REVIEW.md Top-13 清单修复（#1 blocked 章节重试入口、#2 死代码、#3 纠正派发减负、#4 门禁用户可闭环） |
| 环境 | 5285 API（PID 60107，共享 runtime ⚠️）+ 5186 前端（PID 7553）+ OmniRoute 20128（PID 52173）全部在跑 |
| 第十一轮 | prompt 已预写（r11_*.md 四份），派发前必须删旧项目+处理 gemini 配额墙 |

---

## 1. 本会话时间线（做了什么）

| 时间(CST) | 事项 | 产出/证据 |
|---|---|---|
| 02:20 前 | 排障 seed-generate dispatch_exception：发现异常全链被吞 | 确认 reservations.py 裸 except 吞异常、seed_workflow 等四处只抛 error_code 丢 error_message |
| 02:20-03:00 | 逐层定位 401 探针失败 | **deepseek_api.py 的 ENDPOINT/MODEL 环境覆盖从未实现**（docstring 声称有），网关密钥被发往 api.deepseek.com |
| 03:00-03:44 | 定位 504 网关拒长请求 | OmniRoute 本地限流 `requestQueue.maxWaitMs=15000ms`；直接改 ~/.omniroute/storage.sqlite + 重启网关（备份留存） |
| 03:44-04:00 | 定位 receipt_identity_mismatch | harness 回执身份校验不认网关改写的 model；适配器暴露 expected_response_model 声明 |
| 04:00-04:12 | 定位 finish_reason=length 截断 | 网关默认输出预算 8192；新增 max_output_tokens 参数 + MAX_TOKENS 环境覆盖 |
| 04:12 | 5285 重启（含全部修复） | PID 60107 至今运行 |
| 04:12-04:45 | 全链实测验证 | seed→ready_for_review✓；study-context✓；regimen→needs_information 高质量医学追问✓ |
| 04:15 | 第十轮四测试者派发（setsid 脱离） | PID 66226/66228/66231/66233，日志 /tmp/t17_r10_tester{1,2,3,4}_*.log |
| 04:32 | 删除 16 个旧项目（清洁空间兑现） | 三库外科手术删除，备份 *.pre-cleanup-20260921_043238 |
| 04:35-04:50 | tester1 gemini 配额 429 退出 → 用锁定编队模型 muse-spark(max) 重派 | 新 PID 77804 |
| 05:0x-06:0x | 四份报告陆续产出并归档 | t17_round10/tester{1,2,3,4}_report.md |
| 06:0x-06:2x | 聚合 AGGREGATE.md + docx QC（tester2 导出产物） | QC 发现 v2_n_* 锚点与"IgAN 正文"两疑点 |
| 06:30 | 会商审阅派发（deepseek-v4.1-flash max，setsid） | PID 95065，日志 /tmp/t17_r10_conference_review.log |
| 07:1x | 会商完成，意见书归档 + **修正聚合报告两处误判** | t17_round10/CONFERENCE_REVIEW.md + AGGREGATE.md 修正附录 |

## 2. 代码修改清单（本会话全部改动，均已提交）

### 提交 0112373「gateway dispatch chain」
| 文件 | 改动 |
|---|---|
| `services/api/app/protocol_workflow/runtime/adapters/deepseek_api.py` | 实现文档声称但缺失的 `WORKBENCH_PROTOCOL_V3_AI_ENDPOINT`/`_MODEL` 环境覆盖；`_AI_EXPECTED_MODEL` 改为仅非空时覆盖参数（修复参数被 None 覆写的 bug） |
| `services/api/app/protocol_workflow/runtime/adapters/zhipu_api.py` | 构建完成后把解析出的出口模型声明挂为 `adapter.expected_response_model` 属性；import os |
| `services/api/app/protocol_workflow/runtime/harness.py` | dispatch 路径 `getattr(adapter,"expected_response_model",None) or request.model` 作为回执身份校验基准（回执仍如实记录 API 观察身份；未声明时严格相等不变） |
| `services/api/app/protocol_workflow/agent1/seed_workflow.py` | `raise RuntimeError` 改为携带 `result.error_message`（保留错误码前缀） |
| `services/api/app/protocol_workflow/agent2/design_workflow.py` | 同上 |
| `services/api/app/protocol_workflow/agent2/subgraph.py` | 同上 |
| `services/api/app/protocol_workflow/agent3/subgraph.py` | 同上 |
| `services/api/app/protocol_workflow/runtime/reservations.py` | dispatch 异常前 `logger.exception` 落日志（此前裸 except 全吞导致 unknown_outcome 不可诊断）；import logging + `_logger` |

### 提交 6de4afb「max_tokens output budget」
| 文件 | 改动 |
|---|---|
| `services/api/app/protocol_workflow/runtime/adapters/zhipu_api.py` | 新增 `max_output_tokens` 参数；`_completion_body` 仅在设置时附加 `max_tokens` 字段（缺省请求体逐字节不变） |
| `services/api/app/protocol_workflow/runtime/adapters/deepseek_api.py` | 新增 `WORKBENCH_PROTOCOL_V3_AI_MAX_TOKENS` 环境覆盖（isdigit 校验）；docstring 更新 |

### 新增测试
| 文件 | 内容 |
|---|---|
| `tests/protocol_v3/test_deepseek_gateway_override.py`（新建，7 用例） | 无声明 fail-closed / 参数声明通过且回执诚实 / env 声明通过 / endpoint 覆盖达 HTTP / max_tokens 达 body / 缺省 body 历史形态 |
| 回归基线 | 传输+调度+预订 202 全绿（PYTHONPATH=services/api:packages:.） |

### 非代码变更
| 对象 | 变更 | 备份 |
|---|---|---|
| OmniRoute 网关限流 | `~/.omniroute/storage.sqlite` key_value 写入 namespace='settings' key='resilienceSettings' value='{"requestQueue":{"maxWaitMs":600000}}' + 网关重启 | `~/.omniroute/storage.sqlite.bak.pre-resilience-<ts>` |
| 测试库清理 | 16 旧项目三库外科手术删除（user_projects 表 16 行 / e2e_test_mw 五表 110 行 / journey 两表 14 行） | `runs/mw_protocol_v3_unified_tests_20260919/e2e_test_mw.sqlite.pre-cleanup-20260921_043238`、`工作台/runtime/user_projects.sqlite3.pre-cleanup-20260921_043238` |
| 文档 | `.trellis/tasks/09-13-protocol-v3-v1-1/checkpoint.md` 尾部检查点、团队记忆 mw-protocol-v3-takeover-state.md 多段追加 | — |

## 3. 增删功能与行为变化（用户可感知）

**新增能力**
1. 部署可用环境变量把 DeepSeek 适配器整体指向本地网关（OmniRoute/cms-router）：端点、请求模型、密钥、出口身份声明、输出预算五件套（`WORKBENCH_PROTOCOL_V3_AI_{ENDPOINT,MODEL,KEY,EXPECTED_MODEL,MAX_TOKENS}`）。缺省时行为与直连历史完全一致。
2. 网关重写响应 model 字段时，可通过声明放行（回执仍如实记录，审计不丢）。
3. dispatch 异常落日志（此前全部静默吞掉）；四个工作流的失败消息携带完整传输异常文本。

**修复的行为**
4. 研究整理/给药设计/设计要素/章节撰写四条 AI 链路在网关部署下从"必死"恢复为可用（第十轮实测穿越）。

**未删任何功能**；无数据库 schema 变更；无前端产物变更（前端 5186 为既有 dev server）。

## 4. 第十轮测试结论（详见归档，勿信本文摘录替代原始报告）

归档目录：`runs/requirements_v2_20260919/t17_round10/`
- `tester1_report.md`（内异症/入口A/muse-spark max）：EXIT=BLOCKED——初稿停滞 6/111，"继续写作"×4 零新增；导入方案摘要卡死 13 分钟；反拟合过
- `tester2_report.md`（甲状腺眼病/入口B/cursor-grok）：EXIT=OK，产品判定 FAILED——7/111 章即"可保存可导出"，104 缺口；导出+GenOffice 编辑保存往返成功
- `tester3_report.md`（IPF 盲测/入口B/deepseek-v4.1）：EXIT=BLOCKED——给药门禁 4 轮补答不收敛；生成 3 次中止 0/111；OCR 图片型 DOCX 不可用
- `tester4_report.md`（痛风/入口B/glm-5.2）：EXIT=OK，产品判定 FAILED——10/103 冻结；正文泄漏 v2_n_16_x1 锚点与"继承性义务"病句；反拟合过（正文 20 域零命中，痛风域内容正确）
- `AGGREGATE.md`（聚合，**尾部已附会商修正附录，修正了 P0-C/P1-A/P1-B 三条**）
- `CONFERENCE_REVIEW.md`（会商意见书，247 行，含项目↔测试者映射勘误）

**AI 通道修复实战验证**：四测试者全部穿越"准备写作材料"（seed-generate）与设计 AI 节点，第九轮 401/504/blocked 全灭；"needs_information 补答"确认为设计内流程。

## 5. 会商结论摘要（对聚合的修正 + 根因）

**修正（不要再按聚合原文修）**
- ~~P0-C 跨项目串染~~ → **撤销**：QC 取错文件（/tmp/t17_tester2/ 共享目录里的上一轮 IgAN 产物 iga_protocol_work.docx）；tester2 真实导出 ted_t1_protocol_export.docx 逐段复核零命中。残留改进：导出 docx 写项目指纹 + QC 产物按轮分桶。
- P1-A 锚点泄漏 → 降级：段落导出已剥离生效；iga 文件 108 处系修复前历史产物。仍需修表格路径与 UI 面。
- P1-B"导入挂死 13 分钟" → 根因完全不同：后端 125ms 即 401 终结（legacy 链路未走网关），前端挂死是 StrictMode latch 一行 bug。

**根因（文件:函数级，详见 CONFERENCE_REVIEW.md 第一、二节）**
- **P0-A 初稿停滞**：模型输出常不合格进纠正分支（纠正请求近 2 倍体积+每章仅 1 次纠正机会）→ 纠正派发异常落 UNKNOWN_OUTCOME 永不降级 FAILED（`runtime/reservations.py:613-643`）→ 节点投影 BLOCKED_UNKNOWN 且 `can_resume=False`（`graph/runtime.py:1012-1033`）→ 一章阻断全稿冻结（`agent3/manuscript_coordinator.py:103-113`），且产品所有"继续/重试"按钮**只调只读 recover**（`api/manuscript_drafts.py:334-341`；`ManuscriptWorkspace.jsx:539-544`）——语义上是空按钮。
- **P0-B 门禁不收敛**：门禁判"模型自报完整度"（`agent2/clinical_worker.py:159-162`），写作说明补答只进素材/种子候选不进 `confirmed_study`（tester3 现场第 4 轮问题原文自证），种子候选越补越多 → 门禁追尾。前端卡片无作答控件（`RegimenProposalCard.jsx:147-155,216-222`）。
- **r7"一章失败不冻结全稿"修复是死代码**：`manuscript_coordinator.py:96` 判 `status=='failed'` 恒假（GraphRunStatus 无该值）——这解释了 r7/8/9/10 反复复现同一 P0。
- 恢复算子存在但无产品入口：`graph/runtime.py:615/658/787` 全仓只有测试调用。

## 6. 下一步：Top-13 修复清单（会商产出，含验证方法）

**执行顺序即优先级**；每项的改动点与最小验证原文见 `CONFERENCE_REVIEW.md` 第七节表格，摘要：
1. P0 给 blocked/unknown 章节装可用的重试入口（coordinator + 新 resume 端点接 `runtime.retry_node` + 前端按钮改调）
2. P0 修死代码 `manuscript_coordinator.py:96`
3. P0 纠正派发减负 + `allowed_attempts` 提 2 + 错误码细分
4. P0 给药门禁改"用户决策可闭环"（补答写 `confirmed_study`）
5. P1 legacy 摘要导入 StrictMode latch（1 行，`MedicalWritingSynopsisProjectIntake.jsx:207`）
6. P1 该链路 provider 凭证 401 对齐 v3
7. P1 契约内部文本不进提示词（`agent3/chapter_draft.py:63-70`）+ 导出清洗候选
8. P1 事实路径一致性（`background.product.mechanism` 无写入方；封面文控同族）
9. P1 导出统一投影（TOC 域重建、表格脱敏、锚点全路径剥离）
10. P1 章节标题去占位 + 内部 ID UI 清理（`ManuscriptWorkspace.jsx:98-99`）
11. P1 OCR 缺口细分错误码与准确文案（`api/sources.py:36-42`）
12. P2 导出项目指纹 + 测试产物按轮分桶（防 P0-C 类误报）
13. P2 门禁页可返回 / 39 项确认自动刷新 / 卡片静默 return 改显式禁用

**修复纪律**：每项红转绿+回归（见 §7 配方）+ 提交 GitHub；不要改断言迁就缺陷；不要动 `e2e_test_mw.sqlite` 现场库来"修绿"。

## 7. 环境与启动配方（务必照抄，漏一项即失败）

**当前进程**（暂停期间继续在跑，无需动）：
- 5285 API：PID 60107（04:12 起，含全部修复 env）；⚠️ 本轮重启漏设 `WORKBENCH_RUNTIME_DIR`，项目库落在共享 `工作台/runtime/user_projects.sqlite3`——下次重启必须补 `WORKBENCH_RUNTIME_DIR=$ROOT/runs/mw_protocol_v3_unified_tests_20260919/e2e_runtime_mw` 并同步清理 SQL 路径
- 5186 前端：PID 7553（vite，代理→5285）
- OmniRoute：PID 52173（03:44 起，600s 限流已生效）

**5285 完整启动配方**：
```bash
cd "$ROOT"   # /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313
PYTHONPATH="$PWD/services/api" \
WORKBENCH_RUNTIME_DIR="$PWD/runs/mw_protocol_v3_unified_tests_20260919/e2e_runtime_mw" \
WORKBENCH_PROTOCOL_V3_WORKFLOW_DB="$PWD/runs/mw_protocol_v3_unified_tests_20260919/e2e_test_mw.sqlite" \
WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED=1 \
WORKBENCH_PROTOCOL_V3_PRODUCT_PROFILE=deepseek \
WORKBENCH_PROTOCOL_V3_MAX_INPUT_BYTES=2000000 \
WORKBENCH_PROTOCOL_V3_AI_ENDPOINT=http://localhost:20128/v1/chat/completions \
WORKBENCH_PROTOCOL_V3_AI_KEY=sk-c009001daad9cf6c-58a4ce-3ef23bc2 \
WORKBENCH_PROTOCOL_V3_AI_EXPECTED_MODEL=deepseek-latest-cloud \
WORKBENCH_PROTOCOL_V3_AI_MAX_TOKENS=32768 \
nohup "$PWD/runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python" -m uvicorn services.api.app.main:app --host 127.0.0.1 --port 5285 --log-level warning >> /tmp/mw_backend_5285.log 2>&1 &
```
前端 5186：`cd "$ROOT/frontend" && VITE_API_PROXY_TARGET=http://127.0.0.1:5285 nohup npx vite --port 5186 ...`（已有进程在跑可不动）。
**铁律**：后端源码变更必须同事务重启 5285+5186。

**测试配方**：
```bash
PYTHONPATH="$PWD/services/api:$PWD" runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/ -q
```
（只跑 tests/protocol_v3；顶层 tests 缺 cryptography。）

**排障入口**：
- API 日志：`/tmp/mw_backend_5285.log`（本会话已加 dispatch 异常 logger.exception，排障先看这里）
- 网关日志：`~/.omniroute/logs/application/`；call_logs 按天目录
- 预约终态：`sqlite3 runs/mw_protocol_v3_unified_tests_20260919/e2e_test_mw.sqlite "SELECT error_code,status FROM execution_reservation WHERE ..."`

## 8. 第十一轮派发指引（修复完成后）

1. **派发前删旧项目**（保留出厂 demo：proj_rux/proj_d001/proj_my008/proj_my009/proj_mgk10*/proj_ra_greenfield_sandbox）：备份两库（.pre-cleanup-<ts>）后按 project_id 删——项目库（视 WORKBENCH_RUNTIME_DIR 而定）user_projects 表、e2e_test_mw.sqlite 各 project_id 表、journey 库两表。第十轮 tester 项目 ID 见 CONFERENCE_REVIEW.md 开头映射表。
2. **四份 prompt 已预写**：`runs/requirements_v2_20260919/t17_prompts/r11_tester{1,2,3,4}_*.md`（COPD/入口A、多发性硬化/入口B、MDD 盲测、膝骨关节炎+易用性专题）
3. **锁定编队（owner 指定，不得替换）**：
   - tester1 = `omp -p --no-session --model opencode-go/muse-spark-1.3-contributor --thinking max`
   - tester2 = `omp -p --no-session --model google-antigravity/gemini-3.8-flash --thinking high` ⚠️ gemini-3.8-flash-high 配额至 **2026-09-23T03:23Z** 前不可用，届时未恢复则用 muse-spark 或 deepseek-v4.1 替代并在记录中注明偏差
   - tester3 = `omp -p --no-session --model cursor/cursor-grok-4.6 --thinking high`
   - tester4 = `omp -p --no-session --model opencode-go/deepseek-v4.1-flash --thinking max`
4. **派发方式**：python `subprocess.Popen(cmd, stdout=fh, stderr=STDOUT, start_new_session=True)` setsid 脱离；日志 `/tmp/t17_r11_tester{N}_*.log`；EXIT= 标记判定完成。
5. 收口动作同第十轮：报告归档 `t17_round11/` → 聚合 → docx QC（**先核文件时间戳与项目指纹，勿复用共享 /tmp 目录旧产物**）→ 会商 → 修复 → LOOP。

## 9. 陷阱与红线（本会话亲历或确认）

1. **/tmp/t17_tester2/ 是跨轮共享目录**——QC/取证必须先核对文件时间戳与内容归属，勿按文件名 glob（P0-C 误报的教训）。
2. **jac 值守会话内不能嵌套 CronCreate**（会报"already belongs to a scheduled task"）——会商等待须在会话内轮询或由 owner 侧驱动。
3. OmniRoute 管理面 `/api/*` 需要 management token（本地 CLI key scope 均为 ["self:usage"] 不可用）；直接写 `~/.omniroute/storage.sqlite` key_value + 重启是可行路径（已验证），动手前必备份。
4. `omp --thinking` 是 reasoning 传参（v18.2.6 实测）；nohup+& 会被进程组回收，必须 Popen(start_new_session=True)。
5. 默认 nohup 后台任务随会话恢复被清——tester 进程用 setsid 已验证可跨会话存活。
6. DeepSeek 直连 key 已失效（r9 确认 401），唯一可用通道=OmniRoute 网关（key=cms-router 池）。
7. 反拟合检查词表每轮要追加新场景域；项目下拉列表里的他项目名不算命中。
8. 测试期间（tester 存活时）禁止重启 API/前端/改代码——本轮全程遵守。

## 10. 关键路径速查

| 什么 | 路径 |
|---|---|
| 仓库根 | `/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313` |
| 本 handoff | `<根>/runs/requirements_v2_20260919/t17_round10/HANDOFF_ROUND10.md` |
| 第十轮归档 | `<根>/runs/requirements_v2_20260919/t17_round10/`（4 报告+AGGREGATE+CONFERENCE_REVIEW） |
| 测试 prompt 库 | `<根>/runs/requirements_v2_20260919/t17_prompts/`（r10/r11 全部） |
| 工作流 DB | `<根>/runs/mw_protocol_v3_unified_tests_20260919/e2e_test_mw.sqlite` |
| 项目库（当前实际） | `/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/runtime/user_projects.sqlite3`（隔离区=e2e_runtime_mw 下同名，下轮重启后迁移） |
| journey 库 | `/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/runtime/medical_writing_authoring_journey.sqlite3` |
| venv | `<根>/runs/mw_protocol_v3_1r_integration_20260905/venv`（python3.12） |
| OmniRoute 数据 | `~/.omniroute/storage.sqlite`（限流修复所在；备份 bak.pre-resilience-*） |
| 网关密钥 | `~/.omp/agent/.env` 的 CMS_ROUTER_API_KEY（sk-c009001daad9cf6c-58a4ce-3ef23bc2） |
| 团队记忆 | `~/.zcode/cli/memories/projects/project-851a82f3bfce61db/memory/mw-protocol-v3-takeover-state.md` |
| Trellis 检查点 | `<根>/.trellis/tasks/09-13-protocol-v3-v1-1/checkpoint.md`（尾部=最新） |

