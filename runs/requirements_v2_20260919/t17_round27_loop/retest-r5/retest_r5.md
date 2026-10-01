# retest-r5 · R27 LOOP 第6轮修复批复测报告（2026-09-30 晚，复测协调员）

- 被测对象：本仓库工作区（HEAD=**a7ce3d8**「deep-dive 0930 — triple-root-cause MTPLX/triage failures」+ 未提交修订批 **50文件/13222行**；修订批最后源码修改 **18:28:22**）
- 前端：http://127.0.0.1:5186（代理→5301）；后端：127.0.0.1:5301
- 测试者：复测协调员本人，浏览器黑盒操作（Camoufox 真实点击/输入/选择）。工具限制的等价披露（与历轮一致）：①原生 `<select>` 以 DOM change 等价选择；②文件选择器以页内 File+DataTransfer 等价注入（字节与真实选择一致，sha256 见§二.2）；③文本选区以 Range API 等价构造；④1512×814 视口测量使用本协调员自写的只读 CDP 探针（仅前端视图导航+测量+截图，不调任何写接口；Camoufox 无视口设置能力）。共享 Camoufox 实例本轮三次回收协调员标签页，均以服务端状态/重新打开续跑并如实披露。
- 本轮新建项目（只新建、未碰真实用户项目；本轮主链）：
  - **MW-II-E7206B37**（R5RT-CHB-601 · 慢性乙型肝炎（HBeAg阳性慢性HBV感染，功能性治愈）· II期 · 从零开始）——触发新 P1 死局（§五.1）
  - **MW-II-1EA309D8**（R5RT-PBC-602 · 原发性胆汁性胆管炎 · II期 · 从零开始）——主链，全流水线推进
  - 入口B材料：R5RT-NAR_发作性睡病_H3反向激动剂_II期_方案摘要V1.docx（sha256 `3863e4dc2ee96416…`，本协调员自撰合成摘要，导入未建成项目——如实记录）
- 账本来源：r5 轮测试者新立缺陷（r5-D B2/B3/分诊卡死/英文报错/连点与内部名观察、r5-revroute 修订路由404 P0、r5-C 安全性章节模板级 P0）+ retest-r4 遗留（入口B云端401、导出NameError P1、连点重复建项 P1、属主记录死pid P0残留、ollama云profile P1）

---

## 一、重启与指纹（①）——本协调员重启两服务并验证 ✅

本轮有代码修订（16:06 提交 a7ce3d8 + 未提交批至 18:28:22）。

| 动作 | 证据 |
|---|---|
| 后端5301重启 | 原进程 22379（16:00:53 启动）**陈旧**：`main.py`(18:12)/`repository.py`(18:09)/`research_pipeline.py`(18:28)/contracts `models.py`(17:38) 均晚于其启动。18:40:48 经 `start_5301_round27.sh` 重启（pid 46279）。预检如实警告 5 个云端 key 未导出（与实现方 16:00 进程同状态；MTPLX/ollama-cloud 凭据按 a7ce3d8 已入 `ai_provider_secrets.json`，key 名核对：`independent_ai__mtplx_qwen38_local`、`independent_ai__ollama_cloud_dsv41` 两把在位——本轮模型调用实测见§二） |
| vite重启 | 原进程 43583（18:20:07 启动）早于 `styles.css` 18:24:28 修改，页面实测出现 advisory 横幅「前端开发服务早于当前后端代码（vite启动时 api-53f0721cdb197d5e，当前源码树 api-a78d24d4fd37c5ad）」→ 18:46 由本协调员以显式 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301 --host 127.0.0.1 --port 5186 --strictPort` 重启（pid 46742，`ps eww` 实测 env），刷新后横幅消失 |
| 指纹一致性 | 重启后三方一致：直连 5301 = 经 5186 代理 = vite 逐请求现算期望，均为 **`api-a78d24d4fd37c5ad`**，`ready=true` ✅ |
| 附注 | `frontend/dist/runtime-build.json` 仍为 14:43 的 `api-6e3c03577653f0b7`（生产构建产物未随批更新）；dev 模式走 vite 逐请求现算，不影响本判定，如实记录 |

## 二、fixed_pending_verify 逐项（②）

### 1. r5-revroute P0（修订路由404，a7ce3d8#2 base_url 缺 /v1）——路由层关闭 ✅ + 新P1 ⚠️

- 浏览器路径：M8（MW-II-00990781，有工作稿版本1）写作平台 → 随机化节 → 选中文本 40 字（「随机、双盲、安慰剂对照、多中心、平行组设计。符合入选标准的受试者按1:1比例随机」）→ 修订意图=改写 → 提交AI修订（19:00 前后）。
- durable 只读核对（`medical_writing_durable_jobs.sqlite3`，`mwjob_7edf5f0ef6f34c44306a52e4`）：**provider=`ollama-cloud`、model=`deepseek-v4.1-flash`、无 error_summary、无执行层策略拒绝**——r3 的白名单三连拒、r5 的 `HTTP 404`（POST 打到 `/chat/completions`）均未复现；网关到云的 TCP 连接实测在途（backend→198.18.0.9:443 ESTABLISHED，本机代理出口）。**路由身份与外呼路径 = owner 决策的 ollama 云 deepseek-v4.1-flash，404 路由缺陷关闭。**
- ⚠️ **新 P1（不关闭端到端）**：修订调用**超长未返**——第 1 次云尝试无输出直至超时，梯内自动重试至 attempt 2（租约持续续期，19:52 仍在跑，累计 >50 分钟零产出）。对照 r5 同任务 46 秒即 404 速拒：现在请求被云端接受但极慢/疑似流挂起。修订端到端产出本轮未获得；ollama.com 云端点响应能力/模型负载需集成人核定（与 retest-r4 已立「ollama云profile」项同源深化：key 与 model id 已核定生效，现为服务端性能/可用性问题）。

### 2. retest-r4 P1（入口B解析云端401/404）——路由修复实证 ✅ + 端到端未完成 ❌（新形态）

- 浏览器路径：新建项目 → 导入方案摘要 → 注入摘要 docx（sha256 `3863e4dc…`）→ 导入并提取（19:06:46）。
- 只读核对：`medical_writing_synopsis_imports` 新记录 `mwintake_0c814c…` **pending 推进至 ai_synthesis**（对比同表当日 07:46/02:53 两条 failed——云端 401 速死不复现）；route_snapshot = **provider=mtplx、model=mtplx-flash-next-optimized-speed、base_url=http://127.0.0.1:8002/v1**（owner 决策：摘要结构化→本地 MTPLX ✓）；等待面板中文如实显示「正在处理 1/1 个内容块 · 模型处理中或排队等待空位 · 已运行 N 分钟 · 模型正被1个任务占用」+ 取消口（截图 shots/06）。
- 终态（19:36:47）：**failed —「chunk 0 validation failed: AI provider retry ladder budget exhausted after 2 attempt(s) within 1800s (last TimeoutError)」**。两层结论：
  1. **预算与诚实失败机制按设计工作**（ENV-02 修复实证）：无界等待变为 1800s 有界预算→显式失败；UI 诚实中文呈现「方案摘要解析失败。已完成的解析进度仍会保留，您可以继续处理。」+ **继续处理 / 重新选择 双恢复口**——retest-r1 种子⑥的「取消态死路」在失败态已不存在（重新选择实测可用）。
  2. **端到端解析仍未完成（新 P1）**：根因转移到 **MTPLX 长生成超时**（2×~15min 窗口内未完成单块合成）。对照：同期 PBC 竞品分诊在 MTPLX 正常完成（§二.5）——短批调用正常、单次长生成不行，指向 MTPLX flash 模型对长合成任务的性能/循环问题，非路由问题。
- 判定：路由层（401/404）关闭；**入口B端到端不判通过**。

### 3. r5-D B2（1512×814 框架表单消失、下滚不动）——通过 ✅

- 只读探针（`retest_r5_viewport_probe.mjs`，1512×814，本协调员自建 PBC 项目 MW-II-1EA309D8；输出 `probe_framing_1512x814.json` + shots/05）：journey 壳 clientHeight=**612px**（r5-D 现场为塌缩）、**4 组框架表标签（项目与产品/研究目的/竞品范围/总体设计）全部在场且可见**、21 个表单控件可见、`grid-template-rows: 640px 0px`（r1 修复布局延续）、页面可滚动（docScrollHeight 824 > 814）、表单区在视口内（top=159, bottom=771）。
- 附带观察：草稿保存后 details 高级面板记忆折叠态，点击 summary 可正常展开（wasOpen=false→nowOpen=true）——非 r5-D 所指的表单塌缩，不立案。

### 4. r5-D B3（框架页 F5 掉回总看板；二刷 5186 拒连）——通过 ✅

- 整页刷新（navigate 等价 F5）后仍停留在「研究方案智能设计与写作」写作视图，项目自动回选（MW-II-E7206B37 实测）；未复现掉回总看板。5186 本轮持续可连（vite 重启窗口除外，重启即恢复）。

### 5. r5-D（AI分诊点30分钟无反馈 + 完成第一步被流水线冻死）——通过 ✅（正常路径端到端）

- PBC 主链浏览器实测：完成框架填写 → 提交后流水线自动启动 →「已锁定 **107 项候选研究**」→ **AI分诊在 MTPLX 完成**（durable job `mwjob_dc5f79be…` completed, provider=mtplx）→ 抽屉「竞品分诊已完成 已完成 9/9 · 100%」→ 本协调员点「确认并锁定全部107项」（19:28）→ 流水线进入下载+OCR，**oMLX 通道页级真实进度**：「正在处理 NCT05014672 / Prot_000.pdf；OCR 第 26 页完成（全文共 127 页）；已完成 4/5 个需识别页面 · 子步骤 72%」（截图 shots/07 同款横幅文本）。
- 冻结期交互为**中文说明+双出路**：「研究流水线正在AI竞品分诊；为保持检索/分诊快照冻结，暂不能保存研究框架。可等待流水线结束后重试，或在竞品处理抽屉取消本次流水线。」——不再是静默冻死。r5-D 的「分诊30分钟无反馈」在正常适应症路径上未复现。

### 6. r5-D（取消流水线/手标竞品等英文 NetworkError 报错）——通过 ✅（实测面）

- 本轮实测触达的错误面均为中文：冻结说明、解析失败、导出失败（NameError 条目亦为中文包装）、版本门 advisory 均中文。未穷尽全部错误面，如实记录。

### 7. retest-r4 P1（DOCX导出组装 NameError `_context`）——**未修 ❌（维持）**

- M8 写作平台点「预览 Word」：红条原样「**Word 导出失败：DOCX 导出失败（阶段：组装章节）: NameError: name '_context' is not defined**」（截图 shots/04）；durable job `mwjob_de4b4e20a6f514c5aa8d0b95` failed 记录在案。与 retest-r4（15:16）同错误同阶段。**维持 P1 待修。**

### 8. r5-C P0（安全性章节模板级塌陷 + 导出门放行占位符）——无法端到端验证 ❌（维持立案）

- 修复批确有对应代码落位：`repository.py` 新增 `_is_safety_regulatory_section`/`_gap_placeholder_block(s)`/`_is_soa_section`/`_soa_skeleton_blocks`；`main.py` 含「NEW-3/15/18/43 内容族②：overrides 先行计算并传入装配器，安全性缺口…」。**但导出组装被 §二.7 的 NameError 阻断，本轮无法产生新导出件验证安全性章节实文与导出门**——内容族②③的导出件检验随之被阻，维持立案。

### 9. retest-r4 P0残留（仲裁器属主记录死 pid，跨重启持久）——**未清偿 ❌（维持）**

- `/api/model-lifecycle/status` 实测：mtplx `healthy=true, resident=true, inflight=1`（真实服务中，对比 retest-r4 时进程消失——**MTPLX 已复活并完成真实分诊负载**），但 `identity: owned=False, pid=18233, reason=process_not_running` **依旧**。实时后果：仲裁队列出现 `translation→omlx dispatch` 等待（入口B失败释放 MTPLX 后才切相成功）。属主记录清偿属编排器属主职权，本协调员未触碰。**维持 P0 残留。**

### 10. r3-D P1（连点重复建项）——本轮未复现 ✅（历史重复仍在库）

- CHB 建项时连点「创建并进入写作」：第二次点击时按钮已消失/禁用（UI 防重生效），项目仅建成 1 条（下拉核对）。库内 MSC-201 约 30 条历史重复仍在（retest-r4 已立案的存量，不重复立案、不清理——清库红线）。

### 附：种子⑥「版本门无原因说明」——本轮获真实浏览器实证 ✅

- vite 陈旧期间页面实测显示 advisory 横幅（**中文、带原因与双指纹、带处置指引**：「前端开发服务早于当前后端代码（vite启动时 api-53f0…，当前源码树 api-a78d…）——请重启vite后刷新页面」），重启后消失——r1 时无法复现漂移场景的该项，本轮自然漂移条件下浏览器闭环。

## 三、回归抽查（③）

1. **建项**：CHB（MW-II-E7206B37）+ PBC（MW-II-1EA309D8）两次三字段建项均一次成功、无重复，列表/头部联动正常 → **重过 ✅**
2. **导出**：**未达成 ❌**——被 §二.7 NameError 阻断于组装阶段（缺陷本身，非回归遗漏）。

## 四、并发仲裁压测（④）——双载=0 ✅（故障态口径）

- `retest_r26_drill.py`（300s 窗口）19:10:41–19:30 实跑，exit=0；**执行在真实负载下**（MTPLX 正被入口B摘要合成占用，比空载严苛）。产物：`concurrency_drill_summary.json` / `concurrency_drill_events.jsonl`（本轮实跑）。
- **双载判定：61 个驻留样本 co_resident=0 → 全程无同时驻留 ✅**。仲裁器无错误；8001/8002 进程始终为编排器原进程（8001 pid 82672 / 8002 pid 63756），未被触碰。
- 如实记录两条局限：①两相各仅 1 次探测且双双 900s 客户端排队超时——真实占用 + 属主记录卡切相下的同相排队代价（P2-B 同族），非双载；②**压测仪器缺陷（新 P2）**：drill 探针无鉴权，`mtplx_up=False` 全程为 401 假象（与 64841c2 修复的编排器裸探针同族——drill 脚本需带 key 改造）。结论口径：**故障态下无双载成立；健康态压测未获得**（同 retest-r4 口径）。

## 五、本轮新发现（记录，不修复）

1. **P1 · CT.gov 检索 400 项目级死局（CHB 项目 MW-II-E7206B37 现场实证）**：含全角标点的中英混排适应症串（「慢性乙型肝炎（HBeAg阳性慢性HBV感染，功能性治愈）」）作 query.cond 时 CT.gov API 返回**确定性 400**（后端日志 9 处 `HTTP Error 400` + competitor-search 500×4 带 traceback）；UI 侧仅显示「正在读取最新检索计划并重试自动调研...」无限循环，**不报错、不收敛**；冻结态下表单字段与「ClinicalTrials.gov疾病检索词」字段均不可编辑，「执行公开检索」弹出的下游失效确认框确认后仍以同串重试=无逃生门。自救探针（只读 curl）：简单中文 cond=200、英文 cond=200、纯中文+括号=200、中文+拉丁混排长串=400（复现脚本输出在案）。产品侧应有：检索词净化/检索计划编辑入口、确定性外部错误的诚实呈现。
2. **P1 · ollama.com 云修订调用超长未返**（§二.1）：attempt 1 超时零产出、attempt 2 梯内重试中；路由身份正确。
3. **P1 · MTPLX 长生成超时**（§二.2）：短批调用（分诊）正常、单次长合成 2 窗口超时。
4. **P2 · drill 探针无鉴权假读 mtplx_down**（§四.②）。
5. **P3 · r5-D 遗留观察仍在场**：「design模块待AI基于语料生成」内部名直出；流水线状态旁「重试」按钮；建项弹窗无独立项目名称栏（系统自动 MW 编号，设计争议）。

## 六、最终判定

- **验证通过并关闭（6 项）**：r5-D B2 视口塌缩、r5-D B3 刷新回看板、r5-D AI分诊无反馈（正常路径端到端：检索107→MTPLX分诊完成→锁定→OCR页级推进）、r5-D 英文报错（实测面）、r5-revroute 修订路由404（路由层：正确身份+无404+云网关在途）、r3-D 连点重复建项（本轮未复现）。
- **附带关闭（1 项）**：种子⑥版本门无原因说明——advisory 横幅本轮自然漂移条件下浏览器实证（中文+双指纹+处置指引）。
- **未闭合**：导出 NameError P1（原样复现）；入口B端到端（新形态=MTPLX 长生成超时；路由与预算层已修并验证）；r5-C 安全性章节模板级 P0（被导出阻断无法验证）；属主记录死 pid P0 残留；新立 CT.gov 死局 P1、ollama 云慢 P1、MTPLX 长生成 P1。
- 回归抽查：建项重过 ✅；导出未达成（被 NameError 阻断）。
- 压测：无双载 ✅（61 样本 co_resident=0，故障态口径）。
- **allPass = false**——修复批确实清偿了 r5 轮的界面族缺陷（视口/刷新/分诊反馈/中文报错）与修订路由 404，语料准入链（OCR/翻译/分诊）在 PBC 项目端到端健康；但「导出组装 NameError」「MTPLX/ollama 云长任务性能」「属主记录残留」「CT.gov 检索死局」仍使主链后半段（写作→导出）与入口B无法收口。

## 七、收尾确认

- Camoufox 任务空间标签页已全部关闭（`camofox_list_tabs` 核为空；共享实例三次回收标签页，均以服务端状态续跑并已披露）。
- 临时文件服务器 127.0.0.1:5411 已停止；`serve5.log` 已删；测试材料 docx 保留于本目录（历轮先例）。
- 保留证据：本报告、`shots/`（6 张截图）、`probe_framing_1512x814.json`（只读探针测量）、`retest_r5_viewport_probe.mjs`（只读探针源码）、`concurrency_drill_summary.json`/`concurrency_drill_events.jsonl`（压测原始数据）、测试材料 `R5RT-NAR_…方案摘要V1.docx`（sha256 报告内引用）。
- 现运行 5301 为本协调员 18:40:48 重启（pid 46279，指纹 api-a78d24d4fd37c5）；vite 为 18:46 重启（pid 46742，显式 env 实测在案）——属①职责内的正确重启，属主可随时接管。
- 未触碰：live 8910、医学监查、共享 runtime、任何模型服务器进程（8001/8002 为编排器原进程）、他人项目（M8 仅按 r5-revroute 先例做只读+单次修订验证；OAB 未动）、immutable 行；未清库未删历史；路由/密钥文件零改动（仅读）。
- cleaned = true

---

（报告完。另注：本 ask 原文指定证据路径 `retest_r1.md`，该文件为 2026-09-29 retest-r1 轮既有完整报告（不删历史红线），本轮按 retest-r2/r3/r4 既例写入 `retest-r5/retest_r5.md`。）
