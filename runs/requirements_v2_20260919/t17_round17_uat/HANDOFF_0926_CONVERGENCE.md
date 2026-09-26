# HANDOFF — 0926 收敛冲刺（无损暂停点）

## 强制接续指令（每个后续 Agent 开工前必须先读完本节）

你接手的是 smkzw/protocol-v3-workbench 医学写作子系统的收尾冲刺。本批完成了"26 项翻译失败根因修复+收敛"、"164 忠度拦截复检工具"、"K3 大批次三层排查与门缺陷定性"、"T16/T17 桌面 Office 全链验证"四件事。工作目录 = 本仓库根。禁止 reset/clean、删除历史、伪造状态；禁止操作用户前台桌面（桌面 Office 类验证已获用户授权由 agent 用 computer use 自行完成，无需再请用户动手）；MTPLX/oMLX 两台本地模型服务器内存互斥（~30GB each / 128GB 机器），不得同时加载，未经用户授权不得启停。汇报一律用非工程化语言（做了什么/没做什么/踩了哪些坑/下一步）。

## 一、SOURCE_COMMIT 与 RUNTIME_IDENTITY

- SOURCE_COMMIT：`7215ca5`（工作流批：根因修复+复检特性，六文件耦合集）→ `6936214`（T16 桌面 Office 证据）→ 本 handoff 提交为最新。上批基线 9771a64。
- RUNTIME_IDENTITY：后端 uvicorn 5301（运行 7215ca5 代码，工作流收敛轮重启已加载）；前端 vite 5186；MTPLX@8002（用户 0925 重启，探针 200）；oMLX@8001（翻译模型 dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX 驻留，探针 0.5s）。重启配方与 `HANDOFF_0924V2_BATCH1.md` §一完全一致（env 五件套 + PYTHONPATH + --strictPort + build id 双端核对），不再重复。
- live 库定位（勿再找错）：durable=isolated_runtime/medical_writing_durable_jobs.sqlite3；批项=isolated_runtime/writing_reference.sqlite3 的 writing_reference_translation_batch_items；项目注册=isolated_runtime/user_projects.sqlite3。

## 二、CHANGESET（全部已 push）

**`7215ca5` fix(protocol-v3): retry-generation read-side validation root cause + fidelity offline re-evaluation**（六文件，缺一即崩 HEAD——models.py 是 extra="forbid"）：

1. 26 项根因修复族：
   - allocator parentless 分支弃用非法形状 `{gen,'',''}`，改合法 `{gen, parent='synthetic_recovery_{gen}', source=item自身}`（writing_reference_translation_batch.py allocator 段）；
   - `_validate_retry_parent` 对 `synthetic_recovery_` 前缀父跳过真实父查库校验，其余冻结 lineage/失败态/代次递进校验原样保留（writing_reference_upper_layer_execution.py）；
   - 新增 `_repair_invalid_retry_lineage_payloads` 数据修复：JSON1 只读圈行→仅改 parent/source/updated_at 三字段→model_validate 全量复验→乐观锁写入→逐行审计 `translation_batch_item_retry_lineage_repaired`（26 行全部修复，230 项 0 不变量违规）；
   - **方案前提纠错**：integration_owner 弃用 retry lineage 透传（5a2b5a1 遗留的代码与注释矛盾，不清则修复后 26 项会死在"lineage 仅限文档规划"校验）；
   - 测试断言同步（tests/test_writing_reference_translation_batch.py synthetic 合法形状）。
2. 忠度离线复检特性（§5 量化工具）：
   - models.py 新增 blocked_aligned_output(_sha256) 字段（"0926 offline re-evaluation lineage"）；
   - main.py 新增 `POST .../translation-batches/{id}/fidelity-reeval` 端点；
   - repository 幂等指针前移（仅 replay 指向 failed run 时，附审计）；
   - 6 个新单测（含两个 repository 指针测试）。

**`6936214`**：T16/T17 桌面 Office 往返证据包（office_roundtrip_20260925/，见 §三）。

**本 handoff 提交**：App.jsx 补 `const _MEDICAL_WRITING_DIAGNOSTIC_RE`（上批白屏教训的修复，一直漏在库外）+ 本文档 + Trellis checkpoint。

**保留物**：`[MW-ENTRY-DIAG]` 旁路诊断两处仍在 writing_reference_translation_batch.py（translation_batch.py:1010-1025 retry 包装、:4696+ claim 入口）——按用户"保留过程证据"要求留待 K3 修复批确认收敛后删除。

## 三、验收台账（四状态分离）

| 项 | 状态 | 证据 |
|---|---|---|
| 26 项根因修复+收敛 | **PASSED** | entry_diag.md 真实栈；复核员证实 breaker=a0cc222（0925 15:54，1 分钟后非法 payload 入库）；修复后 230 项 0 不变量违规；批次 26 failed→**5 failed+1 running**，ready 38→**57**（19 项转 ready、1 项转拦截，残余为 provider 瞬断 urlerror 族）；最后一项后台消化中 |
| T16/T17 桌面 Office 全链 | **PASSED** | office_roundtrip_20260925/t16_office_roundtrip_result.json：UI 预览 Word 下载 sha=d6cf304d 与导出产物字节一致→computer use 真实 GUI 编辑（第10页正文加标记"T17桌面编辑0925"）→保存 sha=399a5dc7→关闭无脏提示→重开标记保留→XML 合法/zip 完整/w15:docId+书目 customXml 存活。**产品边界澄清：方案文档无 re-ingest 特性（设计如此），闭环=Office 往返身份保留；upload/ingest 属竞品文献链** |
| K3 三层排查+门缺陷定性 | **PASSED（诊断）** | k3_gate_diag.md：①项目注册行已从 user_projects 备份原值 INSERT 恢复；②journey 行 mwjourney_f234ada236f028ce9849 已按同源原则从备份恢复（纯新增）；③快照权限门死锁=产品缺陷：`search_plan=None` 是旅程模型合法早期状态（建项 framing 未就绪即 None，模型层明示可选），门在 Path B 与门后无条件两处一票否决→574 项自创建即失败。修复设计就绪=k3_gate_fix_design.md（方案A：确认的发现篮投影即权威，search_plan 存在时行为不变） |
| 忠度离线复检工具 | **PASSED（实现）** | 端点+6 单测绿；幂等指针推进审计在案 |
| 164 复检量化 | **FAILED（实质未闭合）** | 复检 165 项：admitted=0/data_missing=165/rejected=0——127 项集成行 chunk_ids 为空+38 项不完整，**0 项到达确定性检查器**。"仍拦截165"是数据缺口的保守拒绝而非重判确认，§5 三大族修复对历史数据尚未获得量化验证 |
| pytest 全量门 | **PARTIAL** | 工作流门报 exit=2+failed=0=假绿（收集错误不被解析识别）；复核员子集实测 3 failed 且 git archive HEAD 对照同样 3 failed=存量引入；全量第 4 个存量失败未确认。**门解析盲区待修** |
| 任务记录/复盘/handoff | **PASSED** | Trellis checkpoint 尾部 0926 节 + 本文档 §五复盘 |

## 四、当前硬阻断（按阻塞性排序）

1. **K3 快照权限门**（574 项被拦，durable 2 job 已 3/3 耗尽）——修复设计就绪，未实施。
2. **164 复检数据缺口**——离线复检工具就绪但无米下锅：需查 chunk_ids 为空的根因（集成行早于 chunk 存储引入？能否从 stage runs/翻译记录重建对齐单元），否则 §5 量化证据无法产出。
3. **pytest 门解析盲区**——exit=2/3（收集/用法错误）必须判失败；建议改 --json-report 或 junit 解析。

## 五、复盘（本批踩坑与教训）

1. **怀疑方向≠根因，先抓栈再定案**。adapter/路由怀疑（handoff 上一批的正式怀疑）被一条真实栈一票证伪——真凶是当天的 retry-generation 改动。入口探针投资极小、收益决定性。
2. **独立复核不可省**。复核员抓到两个必进台账的错误：工作流终态快照过期（批次在复核期间继续消化，42/21 → 实际 57/6）和 pytest 门假绿。没有换人复核，这两条就带病入库。
3. **长流程的台账以"最后一次独立实测"为准**，不以任何轮次快照为准。
4. **一次清理事故的长尾会跨天放大**：0924 凌晨的 cleanup 导致项目注册行→journey 行→快照门三层逐日暴露。恢复纪律=逐层验证+只增不改+同源原则（从同一事件的备份恢复）。
5. **升级机制有效**：脚本漏回写第5阶段文件清单，台账提交员按"指令矛盾必须升级而非绕过"拦住，避免了一次"提交树即崩"的半提交（contracts extra="forbid"）。
6. **提交前必须核对"HEAD 树会不会崩"**：跨文件字段依赖（构造点→契约模型）意味着点名清单≠完整耦合集。
7. **确定性门要解析结构化输出**：`-q` 人读格式+收集错误退出码=假绿之源；后续门一律 junit/json 解析+exitCode!=0 即失败。
8. **新恢复尝试语义实战 3 轮全部有效**（每轮新幂等键→新 durable job→全新尝试），是重试预算耗尽后的唯一合规重放路径；项级 attempt 已到 72 仍未碰硬顶。

## 六、NEXT_GATE（顺序）

1. **K3 门修复**：按 k3_gate_fix_design.md 方案A 实施（门改+回归测试：search_plan=None+确认投影匹配→通过且范围来自冻结 prep 批次；search_plan 存在→行为不变；无投影→仍拒绝）→ 全量测试门（结构化解析）→ 重启 5301（build id 双端核对）→ 重放 574 项（新恢复尝试语义，不扩 max_attempts；项级硬顶若挡路带证据升级）→ 收敛监控（预计数小时，durable 后台自行推进）。
2. **164 复检数据恢复**：查 127 项 chunk_ids 为空的成因→能重建则重跑复检出真实量化比例；不能重建则评估小规模再生成成本。这是 §5 验收的最后实洞。
3. **最后一项+残余监控**：目标批最后 1 项消化完成后，T01 四态应为 58/165/5/2（或更好）；若 provider 瞬断再拦，新幂等键补轮即可。
4. **pytest 门修复**（§四.3）。
5. **T18 操作负担口径**（真实鼠标计数脚本+12px/14px computed 字号断言）。
6. **R16 集中验收**：S01-S07（K3 收敛后真实 600 项级数据）、D01-D04、T01-T03、U01-U04（截图已入库可复用）、E01-E04。

## 七、红线（不变+新增）

不变：不触碰 live 8910/医学监查/共享 runtime；不删历史 immutable 行；一切提交同步 GitHub；测试全程 UI 黑盒；不经授权不启停用户模型服务器；桌面 Office 类验证由 agent 用 computer use 自行完成（用户已授权，勿再请用户动手）；不得用扩张重试预算替代根因修复；DB 只增不改历史（恢复缺失行=按备份原值 INSERT，属新增）。

新增：pytest 门必须识别收集错误为失败（结构化解析）；提交前核对 HEAD 树完整性（耦合集）；台账数字以最后一次独立实测为准；模块级全局对象必写 const/let（白屏教训，App.jsx 漏网一行本批补上）。
