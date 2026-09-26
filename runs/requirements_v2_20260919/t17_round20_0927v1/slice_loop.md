# 切片闭环证明 — 0927V1 round20（闭环证明员）

日期：2026-09-27（北京时间）· 执行者：闭环证明员（独立子代理）
审阅基线：5b4c8c11692fc3118eb21bfe80877f5ce9d76c65（开工时实测 `git rev-parse HEAD` = 该值，无漂移；工作树存在他人在改的实现文件，本任务未触碰）。
被证切片：**写作工作稿链** —— 从可恢复起点走通 编辑→保存→服务端确认与版本hash→重开→下载保留，并用真实浏览器（ego-browser）复核 卡片/恢复/编辑/下载。
REPLAY口径遵守：全程打真实 5301 后端与真实 5186 前端，产品写入与权限校验零 mock；未使用任何外部模型（本链不需要模型）。

---

## 一、结论（一段话）

切片可用。在项目 proj_user_97189da36a75（合成药M8·多发性硬化II期，MW-II-00990781）上，从已保存工作稿起点（方案概要节 revision=1）出发：HTTP 路径编辑保存 revision 1→2（0.198 秒，过期 revision 负例被 409 真实拒绝），重开读回的服务端内容 SHA-256 与提交内容逐字节一致；UI 路径真实键入"UI编辑0927V1"并点保存，卡片推进 revision 2→3；浏览器"重新加载"后两个标记均在编辑器中；真实点击"预览 Word"下载文件与 API 直下载**字节完全一致**（SHA-256 = 59f35cb7dbf44aa1…），且等于服务端回执头 `X-Medical-Writing-Docx-Sha256`，DOCX 内含两个编辑标记——下载保留成立。需要真实模型的 AI 步骤（AI修订/生成全文初稿）如实 BLOCKED，未影响本链。

## 二、起点 fixture（可恢复起点）

- 项目：`proj_user_97189da36a75`（合成药M8 · 复发缓解型多发性硬化 · II期 · MW-II-00990781）。
- 文档：`mwdoc_greenfield_proj_user_97189da36a75_1a5fada092706d6c`（111 节，version=草案，status=greenfield_candidate，见 `slice_loop_evidence/final_headers.txt` 同会话 GET document-session 记录于交接正文）。
- 已保存工作稿（非空 revision≥1）共 51 节（只读查询隔离库副本所得，`/tmp/slice_loop_0927v1/dbcopy/`，原库未写）。
- 本链选定正文节：`mwsec_greenfield_proj_user_97189da36a75_64f059a1079a8aca`（方案概要，模板 cms_synopsis，起点 revision=1，`active_authoritative`、`editable`），起点快照存 `slice_loop_evidence/wc_body_before.json`。
- 起点即上轮真实产物：方案首页节工作稿内含上轮标记【核验标记0924V1】（revision=1，保存于 09-24），证明该起点来自真实业务路径且跨轮可恢复。

## 三、闭环逐步证据（命令与结果均为当场实跑）

### HTTP 段（真实 5301，脚本 `slice_loop_evidence/http_loop_body.py`，结果 `http_loop_body_result.json`）

| 步 | 动作 | 结果 |
|---|---|---|
| S0 | GET working-copies/{方案概要} | PASS：revision=1，active_authoritative，2 块（heading+段落） |
| S1 | 负例：expected_revision=0 保存 | PASS：HTTP 409 `"stale medical writing working copy revision: expected=0, actual=1"`——并发/权限校验真实，非 mock |
| S2 | 编辑：段落 text 追加【切片闭环0927V1】 | 有效：该段落块无 rich_text 字段（纯 text 块），仅改 text 即完整合法编辑。脚本内 rt_ok 断言误报 FAIL（要求改一个块上不存在的字段），S4/S5 实证编辑正确落库 |
| S3 | POST 保存 expected_revision=1 | PASS：200，回执 revision=2，updated_at=2026-09-26T23:05:41Z，耗时 **0.198s**（`save_body_receipt.json`） |
| S4 | 重开 GET（服务端确认+版本hash） | PASS：revision=2；服务端 content_blocks 规范化 SHA-256 = `0f6dd5a43cb55cc6…` 与提交内容**一致** |
| S5 | 下载 document.docx?mode=draft_preview | PASS：200（11.3s 渲染 111 节，71,696 字节）；回执头 `X-Medical-Writing-Docx-Sha256=be4c526a0a2a8e41…` == 实际文件 SHA-256；DOCX `word/document.xml` 含【切片闭环0927V1】 |
| S6 | 再次下载 | PASS：字节稳定 SHA-256=be4c526a…（下载保留稳定） |

### 浏览器段（ego-browser，space 80，截图在 `slice_loop_shots/`）

| 检查 | 动作与结果 |
|---|---|
| 卡片 | 选择项目→进入"医学写作"：文档工作副本卡片显示**版本 2｜已保存**（HTTP 段保存的 revision 2 即时在 UI 可见）；编辑器渲染方案首页标题含【切片闭环0927V1】【核验标记0924V1】→ `01_ui_card_rev2.png` |
| 编辑 | 目录（111 节，"方案概要·编辑中"）→ 打开方案概要 → 光标置段尾真实键入 `UI编辑0927V1` → 点"保存工作副本" → 卡片推进**版本 3｜已保存** → `02_ui_edit_saved.png` |
| 重开 | 点"重新加载" → 编辑器段尾完整保留 `…描述性统计。【切片闭环0927V1】UI编辑0927V1` |
| 恢复 | 点"版本与恢复"：面板"作者确认与版本恢复"显示 当前工作版本 版本 3、状态 编辑中、全文冻结进度 0/111、待作者确认、隔离历史、冻结历史 0 条 → `03_ui_versions_restore.png` |
| 下载 | 真实点击"预览 Word"→浏览器下载 `MW-II-00990781-DRAFT_草案_草稿预览.docx`（SHA-256=`59f35cb7dbf44aa1…`），unzip 实测**同时含**【切片闭环0927V1】与 UI编辑0927V1 → `slice_loop_shots/ui_download_preview.docx` |

### 三向一致性（版本 hash 闭环收口）

```
API 直下载 final_download.docx   SHA-256 = 59f35cb7dbf44aa1c3f35f2c95048792b4fca54b1a6ca26b8d56627091dff0f1
UI 浏览器下载同文件               SHA-256 = 59f35cb7dbf44aa1c3f35f2c95048792b4fca54b1a6ca26b8d56627091dff0f1
回执头 X-Medical-Writing-Docx-Sha256     = 59f35cb7dbf44aa1c3f35f2c95048792b4fca54b1a6ca26b8d56627091dff0f1
```
（`slice_loop_evidence/final_headers.txt`、`final_download.docx`；`slice_loop_shots/ui_download_preview.docx`）

## 四、如实报告：边界、异常与不冒充

1. **首环选节误差（已解释，非产品缺陷）**：第一环在方案首页节（`…d9c1cd375c30f809`，front_matter 脚手架）保存 revision 2（`http_loop_result.json`、`save_receipt.json`）。该节属导出器 `_PRE_INDEX_TEMPLATE_NODE_IDS`（`medical_writing_document_exporter.py:1516-1522`），封面由项目元数据生成、工作稿正文不渲染进 DOCX——设计如此。该编辑已真实落库（revision 2 可重开读回），只是不进正文。故换正文节方案概要重走并全绿。
2. **S2 脚本断言误报**：`http_loop_body_result.json` 中 S2 记 FAIL 是我脚本要求更新块上不存在的 rich_text 字段；该块为纯 text 块（`wc_body_before.json` 可证 block keys 无 rich_text），编辑完整有效，由 S4 内容 SHA-256 一致与 S5 标记入 DOCX 实证。原始 JSON 未改，判定以本节说明+实证为准。
3. **模型边界 BLOCKED**：8002 MTPLX 缺席（curl 连接失败，实测退出码 000）；UI"AI修订/生成全文初稿"面板自身显示真实错误"AI provider request failed after bounded retries: HTTP 429"（oMLX 8001 在线但返回 429）。AI 候选生成/AI 修订属需真实模型步骤，**如实 BLOCKED 未执行**；本闭环 编辑→保存→确认→重开→下载 不依赖模型，已完成。未启停任何用户模型服务器。
4. **写操作清单（全部走真实业务 API，可审计）**：方案首页节 revision 1→2；方案概要节 revision 1→2（HTTP）→3（UI）。零删除、零 SQL 状态改写、零 reset/clean；live 库仅只读查询（一次拷贝只读副本至私有 /tmp 读取）。负例两处 409 拒绝未产生写入。
5. **未验证项**：产品内嵌入 Office 链（A22 的另一入口）与外部原生 Word 往返本轮未测（本切片指定"产品内Office链**或**写作工作稿链"二选一，已走后者）；`approved_final` 正式导出需全节冻结（0/111），未触发。

## 五、对 0927V1 结论的支撑

- "真实局部业务闭环不依赖全库清点"成立：本链全程未跑全量测试、未重建环境、未唤醒模型——HTTP 保存单次 0.198s，下载 11.3s，均实测。
- 服务端乐观锁（409 负例）、版本回执 SHA-256、重开持久、UI/API 双路径字节一致，均为当场实跑证据，支撑"REPLAY 车道可对业务路径给出可信反馈"。
- 全库债务状态未动、未冒充通过：本报告只声明本切片闭环通过，不声明全库健康。

## 六、证据文件索引

- 主证据：`runs/requirements_v2_20260919/t17_round20_0927v1/slice_loop.md`（本文）
- HTTP 脚本与结果：`slice_loop_evidence/http_loop.py`、`http_loop_body.py`、`http_loop_result.json`、`http_loop_body_result.json`
- 回执与快照：`save_receipt.json`、`save_body_receipt.json`、`wc_before.json`、`wc_body_before.json`、`final_headers.txt`、`final_download.docx`
- 浏览器截图与下载：`slice_loop_shots/01_ui_card_rev2.png`、`02_ui_edit_saved.png`、`03_ui_versions_restore.png`、`ui_download_preview.docx`
