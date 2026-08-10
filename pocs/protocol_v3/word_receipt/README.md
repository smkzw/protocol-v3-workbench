# Protocol v3 Word 原生验收回执 PoC 合同

状态：`Task 0.7 — contract only`
范围：离线、无副作用的机器判定合同；**不是 Word producer，也不是 Protocol 发布验收**。

## 为什么先冻结回执合同

用户真正需要的不是“文件可以下载”，而是一个在 Microsoft Word 中可直接继续
编辑、目录和交叉引用正确、分页稳定、保存重开后不损坏、能导出一致 PDF 的可提交
定稿。HTML 预览、LibreOffice 打开或仅生成 DOCX 都不能证明这些结果。

因此 Task 0.7 先定义 producer 无关的完成条件。后续 AppleScript、Office Add-in 或
其他 bridge 只能用真实证据满足这份合同，不能修改合同来迁就实现。

## 完成条件

`contract.py` 只有在下列证据全部成立时才接受回执：

1. **身份精确**：绑定 source snapshot、输入 DOCX、SemanticDocumentRevision、
   模板 revision 和 producer implementation hash；任一变化都会产生 typed stale reason。
2. **确为 Microsoft Word**：只接受 `microsoft_word`；工作流必须包含无修复打开、
   所有 story range 的域更新、目录、重新分页、书签、交叉引用、另存、重开和 PDF。
3. **Word 对象可用**：域数量更新前后相同、更新错误为零，至少一个目录、一个真实
   书签和一个 `REF`/`PAGEREF` 交叉引用通过目标核对。
4. **交付可复核**：保存后的 DOCX、Word PDF、连续页面证据和 normalized OOXML
   fingerprint 都有独立 hash；页面必须来自被核验的 Word PDF，而不是网页预览。
5. **环境可解释**：记录 Word、OS、架构、语言和字体清单；缺字或字体替代不能标记
   原生验收通过。
6. **不可变往返**：输入、Word 保存文件和 PDF 使用不同 artifact identity。发生外部
   Word 编辑时，source、edited、reimported、re-exported 四个 artifact identity 必须
   全部不同，且回执绑定新的 merged semantic revision。任何源文件都不得被覆盖。
7. **可重放而不重复**：idempotency key 由 exact source/revision/producer identity
   计算，receipt id 再由该 key 唯一派生。

面向用户时，上述内部字段不应作为程序员标签直接显示。产品 UI 只需给出原生中文
结论，例如“Word 原生核验已完成”“目录与交叉引用已复核”“外部修改已合并为新版本”；
只有阻断项才展开解释。

## 历史证据不能升级

只读复核的
`workbench/evidence/mw_docx_release_gate_20260727/run_word_native_gate.py` 能证明当时
调用过 Word 打开、更新部分对象、保存和导出 PDF，但其 trace 不包含以下完整证据：

- 无修复打开的机器结果；
- all-story-range 域更新和错误计数；
- 关闭后重开；
- 书签目标和 REF/PAGEREF 解析；
- PDF 每页证据及其生产依赖身份；
- normalized OOXML fingerprint；
- edit → reimport → export 不可变 lineage。

因此 `fixtures.json` 将该 trace 保留为确定性负例。历史 review 仍是有价值的过程证据，
但不能被推断为新 `P0-WORD` 合同通过。

## Microsoft 原生能力依据

以下均为本任务决策使用的 Microsoft 官方资料（访问于 2026-08-10）：

- [Word JavaScript 对象模型](https://learn.microsoft.com/en-us/office/dev/add-ins/word/word-add-ins-core-concepts)：Word API 可操作 document、range、table、list、format 及文档级对象。
- [Word Add-ins](https://learn.microsoft.com/en-us/office/dev/add-ins/word/)：Add-in 可跨 Word Web、Windows、Mac 和 iPad；这是 Task 0.8 的候选依据，不是选型结论。
- [在 Word Add-in 中使用 OOXML](https://learn.microsoft.com/en-us/office/dev/add-ins/word/create-better-add-ins-for-word-with-office-open-xml)：原生 OOXML 能覆盖超出普通文本/HTML 的 Word 结构；官方同时建议只在 API 不足时使用 OOXML。
- [持久化 Office Add-in 状态与设置](https://learn.microsoft.com/en-us/office/dev/add-ins/develop/persisting-add-in-state-and-settings)：custom XML 可随 DOCX 保存，为 hidden lineage 候选提供机制；仍须通过真实 Word 往返验证其不会被清理或改写。
- [Word VBA Fields.Update](https://learn.microsoft.com/en-us/office/vba/api/word.fields.update) 与 [Field.Update](https://learn.microsoft.com/en-us/office/vba/api/word.field.update)：域更新能返回错误位置或逐域结果；`Fields` collection 的 story-range 边界是本合同要求 `all_story_ranges` 的原因。
- [Document.Repaginate](https://learn.microsoft.com/en-us/office/vba/api/word.document.repaginate)：Word 可显式重新分页。
- [Bookmarks.Exists](https://learn.microsoft.com/en-us/office/vba/api/word.bookmarks.exists)：可机器核对书签存在性；本合同进一步要求目标一致。
- [Document.SaveAs2](https://learn.microsoft.com/en-us/office/vba/api/word.saveas2)：Word 可另存为新文件；官方说明同名会无提示覆盖，因此产品合同强制不可变的新 artifact identity。
- [Document.ExportAsFixedFormat](https://learn.microsoft.com/en-us/office/vba/api/word.document.exportasfixedformat)：Word 可导出 PDF/XPS 并携带书签和文档结构选项。

这些资料证明候选机制存在，不证明任何 producer 已满足合同。真正选型属于 Task 0.8，
必须在目标 macOS、目标 Word 版本和代表性 Protocol 上实测。

## 页面证据依赖边界

本任务不选择 PDF 页面渲染库。回执要求记录 exact name/version/license/data-egress；
外部依赖只有在许可证与商业使用义务独立核验后才能进入生产候选。历史脚本曾使用的
PyMuPDF 不因“曾经能运行”自动成为产品依赖。`fixtures.json` 使用内部、非生产的
测试证据身份，仅用于验证合同形状。

## 文件与验证

- `contract.py`：严格 schema、typed failure、staleness、idempotency 和 lineage。
- `fixtures.json`：一个完整正例、current identity 和一个历史 trace 负例。
- `tests/test_receipt_contract.py`：缺字段、非 Word、Word 对象、页面、OOXML、
  immutable round-trip、staleness 和历史 trace 回归。

运行：

```bash
python3 -m pytest pocs/protocol_v3/word_receipt/tests -q
```

## Task 0.8 接缝

下一任务只比较 producer，不改变本合同：

1. 先对目标 Word 和候选 bridge 做只读 inventory；
2. 只操作任务副本，绝不覆盖源；
3. 相同 key 重放不得重复编辑；unknown outcome 必须先核对 artifact/receipt；
4. 在 TP-MA-07、D017 骨架、CMS-UC-301 完整方案和复杂 Word 对象 corpus 上生成
   真实 receipt；
5. 只有至少一个 producer 完整通过才可标 `P0-WORD`。否则保持
   `NO_RELEASE_WORD_BLOCKED`，不以人工口头确认降级。
