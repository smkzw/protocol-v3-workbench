已根据磁盘上的 DOCX 文件独立重新计算了 OOXML 指纹——确认与回执及 `decision.md` 完全一致。这是非循环的：它直接读取保存的 DOCX 包，剔除波动属性（rsid/paraId/textId）和 core.xml，并对剩余部分进行哈希处理。

我现在已经有完整的证据了。让我对 D017 的阻塞进行最后检查——确认它是被 `WR_BOOKMARK_EVIDENCE` 阻塞的（没有稳定的业务书签目标），并核实它确实是骨架文档（skeleton-document）的阻塞，而非生产者（producer）的 bug。让我再确认一下是否存在可以测试的 `stage_reimport` 问题，即在 `edited==source` 的边界情况发生时（无编辑场景）的情况。

证据收集工作已完成。让我来汇总报告。

---

# 会议参与者输出：mw_protocol_v3_phase0_task08_acceptance_20260810 - general_pi_qwen38

## 边界检查

- 已读取初始读取集（`AGENTS.md`、会议上下文、Codex 主会场计划）。未读取 Grok 报告。无文件修改。无 Word/服务/浏览器调用。无医疗监控访问。无安全/对抗性/权限/路径/symlink/TOCTOU/破坏性测试。
- 执行的工具调用：`read`（源数据包）、`python3 -m pytest pocs/protocol_v3/word_receipt/tests -q`（67 个通过，耗时 0.25 秒），以及无副作用的收据/OOXML/谱系重新计算（仅通过 `pathlib`/`hashlib` 读取，无写入）。
- 保持在分配的只读范围内。有效的路由 `cms-smk/cms-model` 被视为权威。

## 独立工作成果

**结论：`READY`**，用于任务 0.8 P0-WORD 技术生产者验收。

AppleScript 桥接生产者通过真实 Word 16.111.3 的运行，满足了冻结的收据契约、不可变回导谱系、失败阻断以及逐页证据要求。Lineage 身份、幂等重放、后处理恢复和源文件保存都是有据可查的，而非单纯的主张。

### 1. 契约是严格的且无漏洞的
`contract.py` 验证了 36 个顶级字段以及嵌套的环境/书签/引用/页面/OOXML/谱系子结构。关键不变量已进行机器检查：`verification_engine == microsoft_word`、无修复打开、所有故事范围的字段更新且无错误、字段数量在更新/保存/重新打开后得以保留、独立的工件身份、页面清单重新计算（`compute_page_evidence_manifest`）、将 OOXML 指纹绑定到已保存的 DOCX、具有 4 个不同工件身份的不可变 4 阶段谱系，以及从精确的源/修订/生产者身份派生的确定性幂等性。LibreOffice/HTML/仅下载路径被 `WR_NOT_MICROSOFT_WORD` 显式拒绝。测试套件（33 个契约测试 + 34 个生产者测试 = 67 个）测试了每个门控的负路径。

### 2. 两份最终收据通过完整验证 + 磁盘哈希交叉检查
| 运行 | 收据 ID | 页面 | 字段 | 模式 | 磁盘哈希 | 页面图像 | 谱系 |
|---|---|---|---|---|---|---|---|
| `CMS-UC-301-e692a28e51ed` | `mwwr_v1_a8a815cb…e692a28e51ed` | 27 | 126→126, err=0 | `no_external_edit` | input/saved/PDF 全部匹配 | 27/27 存在，哈希匹配 | 源=输入（无编辑时正确） |
| `CMS-UC-301-wording-roundtrip-r2-18dc202605c6` | `mwwr_v1_234418ce…18dc202605c6` | 27 | 126→126, err=0 | `edit_reimport_export` | input/saved/PDF 全部匹配 | 27/27 存在，哈希匹配 | 4 个不同身份，重导出绑定至输入 |

两份收据均独立重新验证：`validate_receipt()` 通过；磁盘上的 `input.docx`/`word-saved.docx`/`word-export.pdf` SHA-256 哈希值与收据字段完全匹配；`page_evidence_manifest_sha256` 重新计算结果匹配；每页 PNG 哈希值匹配。`decision.md` 中的所有源哈希值与磁盘完全一致（CMS 原始 `cd5d483a…`，TP-MA-07 `a28e95d7…`，D017 `bae34f09…`，r2 重导入 `d9309158…`）。

### 3. 不可变谱系已被证实，而非断言
r2 谱系（`edit_reimport_export`）：源（`bdf8b982…` = r1 的 Word 导出）、编辑后（`d9309158…`）、重导入（`d9309158…`）、重导出（`d9309158…`）——字节相同但身份不同（通过 `word-external-edit-…`、`word-reimport-…`、`word-input-…` 前缀区分），满足 4 个身份不同时存在的规则。`roundtrip_lineage.py` 使用 `atomic_write_json_once`/`_atomic_copy_once`（创建一次，拒绝覆盖）。`prepare_roundtrip` 将 r1 保存的 DOCX 绑定到暂存的 `source-export.docx`（哈希匹配已确认）。`stage_reimport` 拒绝未更改的编辑（`WR_EXTERNAL_EDIT_MISSING`），要求非空的合并修订版本，并验证谱系。

### 4. 幂等重放是确定性的
`compute_idempotency_key` → `compute_receipt_id` 链已针对两份收据重新计算，并与存储的密钥完全匹配。`produce_candidate` 在 `receipt.json` 存在时返回 `replayed`（带有 `assert_receipt_current`）；在存在候选文件时返回 `awaiting_visual_qc`。往返暂存在已准备/已暂存的工件完整时返回 `replayed`。

### 5. 后处理恢复已证实（D017）
D017（`D017-synopsis-import-70376ada005a`）：Word 成功完成（exit 0, 219→219 字段, TOC 1），但后处理被阻塞——没有 `receipt.json`，没有 `receipt_candidate.json`。恢复路径已通过 `003-postprocess-resumed.json`（`postprocess_resumed_without_word_replay`）被证实，该路径重用了现有的 `002-word-invocation.json`（源事件哈希已记录），而无需重新调用 Word。阻塞是书签证据失败（骨架文档只有由 TOC 更新生成的隐藏书签，没有稳定的业务书签目标）。这正确实现了失败阻断，且没有重放副作用。

### 6. TP-MA-07 视觉阻断是真实的
TP-MA-07（`TP-MA-07-dc6dfe33f78d`）：候选文件存在（62 页，302→302 字段，错误 0），但所有页面均为 `pending_visual_qc`，因此 `validate_receipt` 正确失败，报错 `WR_PAGE_QC`。没有 `receipt.json`。第 2 页页脚截断是一个真实的布局缺陷，生产者通过人工视觉审查门控拒绝掩盖它（`finalize_visual_qc` 要求所有页面通过）。

### 7. 源文件保存 + 用户文档隔离
r1 保存的 DOCX（`bdf8b982…`）被保留为往返源；r2 的 input/saved/PDF 哈希值与 r1 完全不同（没有任何内容被覆盖）。生产者对比了运行前后的 `inventory.documents`（3 个用户文档：名称+路径+保存状态）——全部一致，确认仅操作了任务拥有的副本。

### 8. 页面证据依赖已绑定
`page_evidence_producer` = `pypdfium2`，版本从 `importlib.metadata` 解析，许可证 `Apache-2.0 OR BSD-3-Clause`，`data_egress: none`，`license_status: verified_compatible`。页面渲染器字符串是 `microsoft_word_pdf`（PDF 是 Word 导出的，pypdfium2 仅进行栅格化）。页面证据清单将有序页面绑定到确切的 PDF 哈希值。

## 证据与假设

**直接观察到的证据：**
- 67/67 个测试通过（`pytest -q`，0.25 秒）。
- 两份 CMS 收据：`validate_receipt()` 通过；3 个工件哈希（input/saved/PDF）与磁盘匹配；页面清单重新计算匹配；OOXML 指纹独立重新计算匹配（r2: `2c82db48…` = decision.md）。
- 谱系：4 个不同身份已确认；r2 源 = r1 保存的 DOCX 已确认；暂存 `source-export.docx` = r1 保存的哈希。
- D017：Word 完成，没有收据/候选文件，通过恢复路径且无重放。
- TP-MA-07：带有待定视觉质检（visual QC）的候选文件，正确无法通过 `WR_PAGE_QC`。
- 幂等密钥针对两份收据重新派生，与存储值匹配。
- 用户文档库存：3 个文档，前后一致。
- 所有 `decision.md` 中的源哈希值与磁盘匹配。

**推论（非直接观察）：**
- Word 脚本枚举了故事类型 {1,2,3,4,5,12-17} + 每个部分的页眉/页脚索引 {1,2,3}（第一/偶数/主要）。这是 Mac 上 Word 16.111 已记录的完整覆盖范围，但我无法确认它是否捕获了 text-frame/annotation/revision 故事，因为没有此类样本。决策.md 的残留部分对此进行了正确的界定。
- `before` 字段计数是在 TOC 重建后采集的（目录更新可能会增加/删除生成的字段）。这是一个合理的决定——契约检测的是跨保存/重新打开路径的字段身份保留，而不是 TOC 引起的增量。

**假设：**
- Codex 已针对原始外部样本文件验证了源哈希值（上下文第 34-35 行）。我验证了哈希值是否与 `decision.md` 和磁盘上的任务副本匹配，但我没有原始外部文件。
- 27 页的视觉审查由 Codex 执行（上下文第 76 行，计划检查清单第 50 行）。我没有重做像素级的视觉审查——我的验证是页面图像哈希的完整性和清单绑定。

## 风险、差距与验证需求

### 最高影响的观察（非阻断，有界残留）
**Word 原生字段计数 ≠ Python OOXML 字段计数。** Word 报告了 126 个字段（通过故事范围枚举）；`inspect_docx_ooxml` 在同一个保存的 DOCX 中提取了 59 个复杂字段。这种发散是方法论上的（Word 通过带有重复访问的故事范围 API 进行计数；Python 读取原始的 OOXML `fldChar`/`fldSimple` 元素，其中一些可能位于它以不同方式处理的故事部分中）。这**不是**契约违规：契约仅检查 Word 原生的 `before==after`（126==126，内部一致）。Python OOXML 检查用于书签/交叉引用证据提取，而非字段计数。然而，这两个系统在不同的证据路径中衡量不同的东西。建议：将其记录为已知边界，并在未来的语料库中出现字段计数差异时，添加一个交叉一致性检查（即使是一个简单的记录了差异的断言），以防止静默分歧。

### 其他观察（均为有界，未升级为残留）
1. **D017 `source_snapshot_sha256` 语义。** 对于 `no_external_edit` 模式，`source_snapshot_sha256 == input_docx_sha256`（同一哈希）。对于 `edit_reimport_export`，源快照是重导出的交付物哈希。这在内部是一致的，但“源快照”在编辑往返中的含义不同。作为 Phase 0 的语义是合理的；建议在术语表中澄清。

2. **OOXML 规范化器 C14N 回退。** `_normalized_part_bytes` 回退到非规范化的 `etree.tostring`（用于相对命名空间 URI / 裸 GUID 模式）。测试 `test_normalized_ooxml_handles_word_relative_namespace_custom_xml` 涵盖了这一点。回退仍然是确定性的（剔除波动属性，`pretty_print=False`），但它不像 C14N 那样是字节规范的。对于当前语料库（已验证）来说风险很低；如果未来的文档具有来自不同工具的相对命名空间 URI，则风险会增加。

3. **库存比较粒度。** 生产者比较 `documents` 列表（名称+路径+保存状态），但捕获了完整的库存（包括 `captured_at`）。一个被修改但未保存状态的用户文档，如果具有相同的名称/路径，将无法被检测到。对于 Phase 0（仅任务副本，无用户保存），这是可以接受的。

### 质疑的假设
- **假设：“至少一个生产者满足契约。”** 经证实：是的，AppleScript 桥接（在 Word 16.111.3 上）针对 CMS-UC-301 产生了两份有效且不同的最终收据（初始 + 编辑往返），具有完全解析的谱系、书签和交叉引用。
- **假设：“TP 第 2 页截断和 D017 书签缺失是故意的阻断，而非生产者范围的失败。”** 经证实：是的。TP-MA-07 的候选文件功能完备（字段已解析，无错误）；只有视觉质检（visual QC）将其保留在 `pending_visual_qc` 状态。D017 的 Word 执行成功；阻塞是骨架文档上没有稳定业务书签目标，生产者正确返回了 `WR_BOOKMARK_EVIDENCE`，而不是生成虚假证据。
- **假设：“源文件已保存。”** 经证实：r1 导出未被覆盖；r2 使用了不同的身份和哈希值；往返暂存通过原子一次写入（atomic-once-writes）复制（而非移动）了 r1 的已保存 DOCX。

### 向 Codex 提出的有界问题
1. **字段计数方法论差异（126 Word vs 59 OOXML）是否旨在供两个不同的证据路径使用？** 我的评估：是的，无害。如果 Codex 希望加强这一点，在未来的样本上添加一个记录已知偏差的交叉检查断言。这不会阻断 P0-WORD。

2. **我应该独立重新确认页面图像视觉审查，还是信任 Codex 的 27 页审查？** 我的立场：我将页面证据的完整性（哈希值，清单）作为我的范围，并推迟给 Codex 进行像素级审查。如果 Codex 需要独立的视觉确认，我可以使用 `inspect_image` 检查页面 PNG，但上下文第 76 行说明 Codex 拥有渲染视觉验收。

## 推荐的下一步

将 **P0-WORD 标记为技术通过 (READY)**。AppleScript 桥接生产者在目标 Word 16.111.3 上通过真实证据（不仅仅是断言）证明了功能闭环、失败阻断、不可变往返谱系和逐页证据。

在 P0-WORD 处置前解决以下事项：
- 记录 Word 原生与 OOXML 字段计数的差异，作为残留的已知边界（不阻断）。
- 确认 Codex 的 27 页视觉审查涵盖 r1 和 r2（计划检查清单第 50 行仅标注了“CMS 往返 27 页”）。

正确界定的残留（未升级为阻断）：
- 跨平台分发、签名、Office 插件 UX、产品 API 连接：Phase 6-7（决策.md 第 88 行）。
- Text-frame/annotation/revision 故事覆盖范围：需要扩展代表性语料库并重新验证（决策.md 第 89-90 行）。
- 术语质量（“药品监督管理部门”修改）：Codex 直接处理中文句子（上下文第 17 行），不是生产者验收项目。

未向 Codex 提出阻塞性问题。标记为 READY 的安全临时路径已完全得到现有证据的支持；上述两个确认点不会改变结论。
