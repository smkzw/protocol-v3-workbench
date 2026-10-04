# 模型对比测试记录：oMLX Qwen3.8-flash vs MTPLX Flash-Next-Speed（初稿生成适用性）

- 日期：2026-10-04 04:20–04:48（本地 CEST，UTC+2）
- 执行者：模型对比测试员（动态工作流子代理）
- 任务：同一批章节 prompt 下，比较 A=oMLX(8001) `Qwen3.8-flash`（Jundot--Qwen3.8-Flash-Next-oQ4e-mtp，磁盘约 104GB，ssd_offload）与 B=MTPLX(8002) `mtplx-flash-next-optimized-speed`（35.9GB 驻留）谁更适合初稿生成。
- 结论速览：**推荐维持 MTPLX（B）**。A 方均值 144.3 秒/章 vs B 方最近 3 章均值 162.9 秒/章（B 全卷均值 228.2 秒/章），速度小幅占优，但 A 方 3 章全部把输入 payload 原样回显、未产出任何 full_draft.sections，产出不可用；loadFeasible=true。

## 1. B 方基线（引用既有 durable 数据，不重跑）

- 数据源：durable job `mwjob_21832950eafb5fcc14dc638e`（proj_user_97c9c19afb20，HFrEF 自检初稿，21 个 chunk 全部 completed）。
  - `medical_writing_durable_jobs.sqlite3`：created_at=2026-10-03T17:47:16.891Z，updated_at=2026-10-03T19:07:09.176Z → 全程 4792.3s ÷ 21 chunk = **228.2 秒/章**（与任务书引用的 ~233 秒/章一致）。
  - 最近 3 个完成章（chunk 0019/0020/0021）的模型调用窗口，取 ai_task_runs.jsonl 中相邻 airun 起始差（串行管线，含落盘开销）：
    - chunk19 `airun_20261003185900_446ea365`：18:59:00.5Z → 19:03:42.1Z = **281.5s**
    - chunk20 `airun_20261003190342_55f2835b`：19:03:42.1Z → 19:05:09.1Z = **87.1s**
    - chunk21 `airun_20261003190509_ca6c79d2`：19:05:09.1Z → 19:07:09.2Z（作业完成）= **120.1s**
    - **B 方最近 3 章均值 = 162.9 秒/章**（chunk 文件落盘 mtime 与上述窗口交叉吻合）。
- B 方请求设定（照抄依据）：`ai_provider_settings.json` active_profile=independent_ai__mtplx_qwen38_local（base_url 8002、reasoning_effort xhigh、thinking enabled）+ `services/api/app/ai_gateway.py:1284-1301`（temperature=0、response_format=json_object）+ `services/api/app/medical_writing_full_draft.py:75`（max_tokens=65,536）。
- 现场：测试开始时 8002 已处于停止状态（curl 连接拒绝；MTPLX Diagnostics 最后一条为 app_termination），无需执行 `mtplx stop`；B 基线全部来自既有 durable 数据，未重跑。

## 2. A 方加载与同题测试

- 加载：04:31:58–04:32:32 之间完成 `POST /v1/models/Jundot--Qwen3.8-Flash-Next-oQ4e-mtp/load`，"Already loaded" 确认；`/v1/models/status` 显示 actual_size=74.57GB 驻留（与任务书 RAM 估 ~72GB 吻合），加载 <1 分钟（ssd_offload 生效）。**loadFeasible=true**。
- Prompt 构造：用 B 方 durable payload（sqlite payload_json 的 descriptor：target_sections + 冻结 source_manifest 含 text_preview 原文）+ ai_task_runs.jsonl 的 task_context/forbidden_source_ids，调用仓库真实代码 `MedicalWritingFullDraftService._instruction` 与 `PromptRegistry.build`（services/api/app）生成与 B 同题的 system+user 消息；temperature=0、max_tokens=65536、response_format=json_object、thinking enabled、reasoning_effort xhigh（照抄 B 方）。
- 三章题目（B 实际用过的最后 3 个章节包）：
  - chunk19：监查 / 稽查和核查 / 方案偏离 / 关键角色和研究管理
  - chunk20：研究和研究中心的关闭 / 质量控制与保证 / 附录 / 避孕的规定与方法
  - chunk21：实验室检查项目 / 安全信息报告途径 / 项目特异附录
- 耗时（04:35:01–04:42:52，串行，本机 curl 直连，oMLX usage 计时）：

| 章节 | A 方耗时 | A 输出 | B 方窗口 | B 输出 |
|---|---|---|---|---|
| chunk19 | 164.0s（6170 out tok，41.0 tok/s） | 37,229 字符但为 payload 回显 | 281.5s | 4 节全部结构化（partial/source_gap） |
| chunk20 | 124.6s（5227 out tok，43.5 tok/s） | 32,085 字符 payload 回显 | 87.1s | 4 节全部 source_gap（无编造） |
| chunk21 | 144.3s（5977 out tok，42.8 tok/s） | 35,812 字符 payload 回显 | 120.1s | 3 节结构化，实验室检查 354 字含源数字 |

- **A 方均值 = 144.3 秒/章**。

## 3. 质量评估（医学写作视角，并排）

- 结构完整性：B 每章按契约返回 content_status/proposal_text/rationale/gap_items，可直接进入审阅流（虽保守、多为 partial/source_gap）；A 三章全部只把输入 payload 原样回显（顶层 13 键=payload 键，无 full_draft.sections、无 findings/evidence_spans），初稿产出为零。
- 事实纪律：B 严格执行来源纪律——缺项目文件时明确 source_gap 不编内容（如"安全信息报告途径"整章留空并列缺口）；A 无从评估正文纪律，因为根本没产出正文（回显本身即违反输出契约）。
- 数字保真：B 在"实验室检查项目"把来源数值原样带入（12周/14周/1天/3天 等访视窗），未自行改写；A 无正文可比。

## 4. 现场恢复（已完成）

- 04:43 `POST /v1/models/Jundot--Qwen3.8-Flash-Next-oQ4e-mtp/unload` → 200；`/v1/models/status` 复核仅剩 MarkItDown（与测试前基线一致）。
- 04:44 `mtplx serve --model /Users/smkzw/.mtplx/models/Youssofal--Qwen3.8-Flash-Next-MTPLX-Optimized-Speed --port 8002 --mtp --yes`（第一次不带 --model 误起 27B Quality 模型并报 not cached，已停掉重来）。
- 验证：`GET http://127.0.0.1:8002/v1/models` → **HTTP 200**，`id=mtplx-flash-next-optimized-speed`；`/health` ok；warmup 完成（约 34 tok/s）。

## 5. 判定与限制

- **verdict：推荐 MTPLX Flash-Next-Speed（B）继续承担初稿生成。** 理由一句话：A 方仅快约 11%（对最近 3 章口径）但 3/3 章产出不可用，速度优势无法补偿契约失败。
- 限制与如实说明：
  1. B 方单章耗时为串行管线 airun 起始差近似（含少量落盘开销），非纯模型推理计时；全卷口径 228.2 秒/章为硬数据。
  2. A 方回显失败发生在 thinking enabled + xhigh + json_object 的 B 方原设定下；未做 thinking 关闭的追加诊断（需再次顶替 MTPLX 破坏互斥与现场，预算内不值得）。若后续想救 A 方，可先测 thinking disabled 变体。
  3. A 方本机输出 tokens（5.2k–6.2k）显著低于 65,536 上限，说明不是预算截断，而是模型行为本身。
- 复现材料：/tmp/bench_a_req_19|20|21.json（请求）、/tmp/bench_a_out_19|20|21.json（原始响应）、/tmp/b_payload.json（B 方 durable payload）。
