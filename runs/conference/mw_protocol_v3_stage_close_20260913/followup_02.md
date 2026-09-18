# 会议后续跟进：mw_protocol_v3_stage_close_20260913 - followup_02

## 输出

### 0. 冻结核验与审阅范围

- `artifact_manifest_followup_02.json`：29/29 SHA-256 实测匹配。相对 followup_01 **恰好两个文件变化**：`protocolWorkspaceApi.mjs`、`ManuscriptWorkspace.jsx`；其余 27 项（含后端 `manuscript_drafts.py` typed-409）与上轮一致。本轮只读，未运行任何测试/服务/浏览器（遵用户禁止阶段测试指令）。

### 1. P1-R1 处置：已解决（源码级）

完整链路三方闭合，逐一核验：

1. **后端**（未变，上轮已核）：`manuscript_drafts.py:41-44` 对 `manuscript_document_revision_changed` 返回 409 + `detail.code`。
2. **客户端**（`protocolWorkspaceApi.mjs:86-96`）：`recoveryKind` 仅在 `status===409 && path.endsWith('/manuscript-draft/save') && rawDetail?.code === 'manuscript_document_revision_changed'` 三条件同时满足时取 `'document_revision_changed'`，否则 null。**精确字符串等值**——无正则、无通配、无任意机器码透传、无文案匹配。路由门精确：全部方法中只有 `saveManuscriptDraft`（137-139 行）产生以 `/manuscript-draft/save` 结尾的路径；`/save/prepare`、`/save/recover`、chapter/manuscript-sources 等均不可能命中（encodeURIComponent 使 study/node id 无法伪造该后缀）。
3. **消费方**（`ManuscriptWorkspace.jsx:170`）：`reason?.status === 409 && reason?.recoveryKind === 'document_revision_changed'` → 恢复分支（读当前稿→归档被拒 intent→清 saveIntent→saveConflict 态→另存按钮）。

四字段公共契约完好：`detail` 规范化块（73-81 行）逐字节未变；`recoveryKind` 是错误对象上与 `detail` 分离的内部属性，且仅在真值时赋值（25 行），所有其他路由/状态的错误形状与旧行为完全一致。非识别类 409（如 `manuscript_save_intent_changed`、`manuscript_request_changed`）走 183 行仅 setError，**不做通用 409 重置**——`manuscript_document_study_changed` 不会被误导向"另存新版本"路径。头部契约注释（15-16 行）同步记载该封闭内部类型。

### 2. 其余改动核验

- **planRefresh（39、64、102 行）**：`finishSources` 捕获 409 后仅 bump `planRefresh`，其只进入 plan effect 依赖（64 行），不进入 sources 轮询 effect 依赖（122 行）。核验结论：**owner 对我上轮 P3-a 建议的否决是正确的**——bump 共享 `refresh` 会使 sources 轮询 effect 重跑，source 仍 completed → 再次 dispatch → 再 409，构成无限循环；当前设计一次 409 → 一次 plan 重取 → 新稿按钮（272 行）可见，且 409 catch 后 `return`（107 行）不再排 timer，轮询停止，无重复。原 P3-a 撤销，替代实现正确。
- **源编译 409 的语义**：原请求（packet.intent/studySha/sourceRunId）保持不变，仅新增显式"按当前研究准备新稿，保留原记录"入口（272-273 行，`begin(true)`），与裁定一致。
- **remember 配额包裹（44-55 行）**：全部 setItem+setPacket 入 try，失败抛中文错误"暂存操作记录失败，已有内容仍保留……"；所有调用点（77、159、167、203、246 行）均在各自 async try/catch 内，中文消息经 `readableError` 的中文字符过滤原样显示。**上轮 P3-b 范围更正**：经复核，`remember` 的调用点在上轮版本中本就在 try/catch 内，我当时"unhandled rejection"的断言对 remember 言过其实；唯一真实缺口是上轮 168 行 catch 块内的裸 `setItem`（catch 块内异常不被同层 try 捕获）。本轮该写入已被 171-182 行的内层 try 包裹并由 `recoveryError` catch 兜底——该缺口结构性修复。P3-b 关闭。
- **source-completed 文案（269 行）**：三分支区分 completed/停止/进行中。修正了上轮"源已完成但整稿 dispatch 失败时仍显示'正在准备资料'"的错误文案；dispatch 进行中显示"资料已准备，完整初稿尚未开始"在 start 成功前属实。

### 3. 新引入问题排查（effect/闭包/abort/竞争/重试/刷新/unknown）

逐项过查未发现新 P1/P2：409 恢复分支内层 prepare/getSemanticDocument 的再失败由 `recoveryError` 捕获且 abort 守卫完整（175、182 行）；成功保存路径 saveIntent 保留→重复点击/刷新走回执重放幂等（161-167 行）；`remember` 在 409 分支先归档旧 packet 再前进，`key:save:<opId>` 无重复写（178 行 next.saveIntent 为 null 跳过 50 行）；retrySources 中 remember 配额失败时 POST 未发出、packet 未前进，下次点击铸新 id 为干净首次注册，无 `chapter_source_retry_identity_mismatch` 风险；配额失败于 `key:save:` 已写但主 key 未写的部分写场景下，重载读到旧 packet，状态一致，孤儿归档仅 forensic。

**残留 P3（不阻断，非新引入）**：
- P3-i（新，轻微）：272-273 行新稿按钮在 `!plan.all_applicable_inputs_ready` 时禁用，但提示文案（266 行）仅在 `!packet` 时渲染——有 packet 的用户看到禁用按钮却无解释。最小修复：按钮旁补一条禁用原因文案。
- P3-c/P3-②（沿用，owner 已明确归下一阶段）：history 归档只写不读与保留策略、`key:<runId>` 死写、内部不变量错误落 422 文案——与计划"整稿恢复与版本"行一致，本轮不重复主张。

### 4. 暂停就绪裁定

**可以按未测试施工检查点收口**：P1-R1 源码级解决且无新 P1/P2；全部已知 P3 已记录并归属下一阶段；冻结哈希与 Trellis 记录构成可恢复检查点。保全前提（须在暂停说明中明示）：**运行时行为、UI 实显、医学内容、Word 导出、视觉验收全部未验 (UNVERIFIED)**——包括 409 恢复分支的真实 HTTP 触发、另存新版本的 revision 链续接、retry 幂等重入、planRefresh 循环防护的实际表现；这些按计划留待完整构建后统一测试与 ego(lite) 验收，源码正确性不冒充任何运行通过。
