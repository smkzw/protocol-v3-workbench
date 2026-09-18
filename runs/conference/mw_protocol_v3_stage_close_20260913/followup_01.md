# 会议跟进：mw_protocol_v3_stage_close_20260913 - followup_01

## 输出

### 0. 冻结与变更核验

- `artifact_manifest_followup_01.json`：29/29 SHA-256 实测匹配、0 缺失。与原 manifest 逐项对比，**恰好且仅有两个文件变化**：`api/manuscript_drafts.py`、`ManuscriptWorkspace.jsx`；其余 27 项哈希与原审一致，原报告全部证据继续有效。本轮仍全程只读，未运行测试/服务/浏览器。

### 1. 总裁定

**该阶段源码可以按"未测试施工检查点"保全**（冻结哈希、Trellis 记录、运行时/Word/视觉验收全部挂起），但有 **1 个残留 P1**：owner 对 P1-1 的修复在后端与前端两侧各自正确，合起来却是**死分支**——typed-409 恢复路径经过本产品唯一的 API 客户端时判定字段被剥离，永远不触发。是否暂停前修（需要动 client 冻结契约）是 Codex 的决策点；不修则必须把它记为下一阶段第一项并在暂停说明中披露。

### 2. 逐项修复独立核验（源码级）

| Owner 裁定 | 实现 | 核验结果 |
|---|---|---|
| P1-1 拒绝自动新 operation，typed 409 读当前稿+归档被拒 intent+显式另存 | 后端 `manuscript_drafts.py:41-44` 新增 `detail.code='manuscript_document_revision_changed'` 专属 409；前端 `ManuscriptWorkspace.jsx:159-176` 捕获后 re-prepare→读当前文档→归档 `key:save:<opId>`→`remember({saveIntent:null, savedDocumentId, saveConflict:true})`→提示文案；`270-271` 显式"另存为新版本"按钮走全新 operation | **分支不可达（残留 P1，见 §3）**。分支内部逻辑本身正确：另存路径经 `saveCompleteDraft` 以 `saveIntent:null` 重新 prepare 铸新 `operation_id`，服务端 revision 链正确续接；不覆盖竞争稿的语义与裁定一致 |
| P1-2 新研究显式新稿入口+旧身份归档 | `begin(newVersion)`（`181` 行守卫 `packet && newVersion!==true`）；`263-264` 当 `plan.study_sha256 !== packet.studySha` 显示"按当前研究准备新稿，保留原记录"；`remember:43-47` 先写 `key:history:<studySha,runId,opId>` 再前进；`194` 行重置 job/savedDocument/sourceState | **源码级 PASS**。旧 packet 归档后才替换；`finishSources` 的 409 有专属 catch（`95`）不再进入无限轮询；丢 ACK 后 resume→404→按原 intent 重启 run 可恢复。残留 P3 见 §4 |
| P2 blocked 状态与未完成章节名 | `261-262`：blocked 显示"本次写作已停止，已生成章节仍可阅读"+未完成章节标题列表 | **源码级 PASS**。blocked 时 job 已填充（polling 在非 running 时 setJob 后停止），可读章节可选；blocked 不设 error、不显示死 resume 按钮（can_resume=False）。标题过滤保留 `not_started` 属实 |
| P2 study_binding_status 横幅 | `269`：`study_binding_status !== 'current'` 显示告警 | **源码级 PASS**。`'missing'` 不可达（后端 404），`document` 空值不可达（router 404），`268` 行 `.revision` 读取安全 |
| P2 源准备显式 retry（原 key+持久 retryDecisionId） | `retrySources:227-245`：先读状态，`can_retry` 时复用或铸造 `retryDecisionId` 并 `remember` 持久化**先于** POST；`272-273` 按 `sourceState.can_retry` 显示按钮 | **源码级 PASS**。POST 中断后重按复用同一 id（后端 `start_retry` 幂等校验一致）；重试耗尽后按钮自然消失（can_retry False），banner 260 显示"资料准备已停止" |
| 成功保存/刷新/重复点击 | `157-158`：保存成功后保留 saveIntent（后续点击走 recover 回执重放，幂等）+`savedDocumentId:null`；刷新按钮 `276` 常驻，驱动 plan/polling/document 三 effect 重取 | **源码级 PASS**。flight 守卫防双击；unmount abort 全路径有 `!aborted` 守卫，finally 无条件复位 flight |

Effect/闭包排查：packet 全部经 `remember` 单点推进，effect deps 含 `packet` 整体，旧 timer 正确清理；`saveCompleteDraft` 内 `...packet` 取点击时闭包，与 polling 写入的状态（job/sourceState 独立 state）无覆盖冲突；abort 后无越界 setState。

### 3. 残留 P1（唯一阻断级）

**P1-R1 typed-409 判定字段在传输层被剥离，修复分支不可达，P1-1 原症状（版本竞争后 saveIntent 毒化循环）实际仍存在**
- 证据链：后端 `manuscript_drafts.py:42` 在 detail 中返回 `code:'manuscript_document_revision_changed'`；前端 `ManuscriptWorkspace.jsx:161` 判定 `reason?.detail?.code === '...'`；但 `protocolWorkspaceApi.mjs:66-79`（哈希未变，本产品唯一客户端）对非 ok 响应**只保留** `message/responsible_area/can_retry/next_step` 四个字段，`code` 明文列入丢弃类（"machine codes"）。`rg` 全 feature 确认：`detail.code` 读取仅 `ManuscriptWorkspace.jsx:161` 一处，client 无任何 code 透传。
- 触发：两标签页保存竞争或文档 revision 被并发推进后，败者点击保存 → 409 → `detail.code` 为 undefined → 落入 `setError(readableError)` → 错误文案有改善（"已有更新的文档版本，本次初稿没有覆盖它。"），但 saveIntent 不清除、`saveConflict`/另存按钮/当前稿读取永不出现 → 按钮仍是"核对并完成原稿保存"→ recover 404 → save 409 循环，与原 P1-1 相同。
- 影响：修复的设计意图（读当前稿、归档、显式另存）在产品路径上完全未生效；同时后端 detail 出现第五个字段而唯一预期消费者看不见它，双侧不自洽。
- 最小修复（决策点，涉及冻结的四字段公共契约，须 Codex 裁定）：
  - **方案 A（推荐）**：`protocolWorkspaceApi.mjs` 规范化增加一个封闭枚举 `code` 透传（如仅允许 `/^[a-z][a-z0-9_]*$/` 且非审计类键），契约注释同步修订；其余丢弃规则不变。
  - 方案 B：前端按 `status===409` + 现有 `next_step` 文案匹配——脆弱（文案改动即断），不推荐。
  - 方案 C：任意 409 一律清 intent 转冲突态——会把 `manuscript_document_study_changed`（研究已变，另存必然再失败）误导向"另存新版本"，语义错误，不可取。

### 4. 残留 P2/P3（记录，不阻断保全）

- **P3-a** 新稿按钮可见性依赖 plan 新鲜度：`finishSources` 捕获 `manuscript_request_changed` 409 后只 setError 不 bump refresh（`95-96`），若 plan 是变更前取的，"按当前研究准备新稿"按钮要等用户手动点"更新研究与文档状态"才出现。最小修复：该 catch 内追加 `setRefresh(v=>v+1)`。
- **P3-b** `remember`（`43-52`）与 409 归档 `setItem`（`168`）无配额异常保护：localStorage 满时异常逃逸为未处理 promise 拒绝，无用户反馈（对照 `StudyContextWorkspace.execute:43-44` 有 try/catch 先例）。
- **P3-c** `key:history:*` 归档与 `key:<runId>` 副本只写不读：forensic 价值可接受，但跨多 run 无限增长，下一阶段生命周期任务应加淘汰规则；`key:<runId>` 死写沿用原报告 P3-①。
- **P3-d** `begin(true)` 后旧已保存文档（同 study 同 document_id 的前一 revision）在 UI 无阅读入口（服务端链上仍在），版本历史阅读属下一阶段"整稿恢复与版本"行，现仅记录。
- 原 P3-②③④（内部不变量错误落 422 文案、真实 CAS 竞争 500 与 409 文案复用、`crypto.randomUUID` secure context）状态不变，未在本批处理范围内。

### 5. 下一阶段计划复核

`plans/mw_protocol_v3_next_stage_20260913.md` 已落实本会商三项建议并有正确边界：确认依赖**复用 canonical/legacy 别名解析但不得把章节 readset 当医学确认范围**（Q2 答复与我的建议一致且更严格）；表格编辑**共用 typed codec/schema 与 hash 计算**；Word 分母**从已绑定完整 ChapterContract 派生、不用 block 上的 contract ID 冒充**。实施明细表给出确切文件/行为/验收三列，"整稿恢复与版本"行的验证义务（restart、并发恢复、断网失回执、保存中断、后继版本）正好覆盖 P1-R1 与 P3-a 的运行期验证。计划无顺序倒置。唯一补遗建议：把 **P1-R1（client code 透传或替代判定机制）** 显式加入该行或单列，避免下一阶段开工时遗漏它是"已完成修复"的错觉。

### 6. 测试/未验证边界声明

- 本轮全部结论为只读源码级核验：未运行任何测试、未起服务、未浏览器、未真实模型调用。源码修复正确 ≠ 运行通过。
- UNVERIFIED：409 冲突路径实际 HTTP 行为（含 `code` 字段在线上的真实形状）、另存新版本的 revision 链续接、retry 幂等重入、blocked 文案实显、E09 视觉终验、IME/编辑、Word。这些按计划留待完整构建后统一测试。
- 对 Codex 的唯一有界问题：P1-R1 选方案 A（client 透传封闭枚举 `code`）还是暂停前仅记录？若仅记录，请在暂停说明中向用户披露"多标签页保存竞争后需手动刷新并以新操作另存"当前不可达，症状表现为重复提示同一错误。
