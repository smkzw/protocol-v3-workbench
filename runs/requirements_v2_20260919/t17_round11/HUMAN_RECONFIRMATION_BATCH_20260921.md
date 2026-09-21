# Protocol v3 既有竞品篮子人工复核批次

日期：2026-09-21

## 目标

在研究信息变化但 ClinicalTrials.gov 检索合同和不可变快照仍一致时，沿用既有候选及人工分类，让医学经理按当前分诊条件一次核对并确认。该动作不得重新调用 AI、检索、下载、OCR、翻译，也不得自动推进父研究流水线。

## 已实现

- 读取分诊运行时返回 `reconfirmation` 状态、当前分诊条件、来源确认及完整预选分类。
- 前端以 bullet points 展示当前条件，默认预选既有人工篮子，仅在用户需要时展开逐项调整。
- 新增人工复核确认身份，保留来源确认、事实哈希、检索计划和逐候选决策谱系。
- 在一个受控事务后重绑原不可变快照，重新生成 discovery/corpus 投影，不改写旧确认或旧 AI 运行记录。
- 投影失败时保存确认并进入“待同步”；用户可直接重试同步，无须再次审核。
- 同一请求可幂等重放，不重复写 relevance decisions。
- 全排除说明改为可选；省略时写入确定性审计说明，不设置任意字数门槛。

## 独立审阅与修复

独立会商 session `sess_a19b465f-8d17-4bcb-bf41-c7f9af5fa580` 发现并复现：投影失败后 UI 无重试入口、仅 revision 变化会触发假复核、冲突状态码和审计措辞不一致。以上均已做最小修复。Ponytail 复核未发现值得引入新抽象、依赖或状态机的理由；当前实现复用既有 run/confirmation/projection-retry 合同。

## 验证

- 后端相关矩阵：450 passed。
- Protocol v3 全套：2601 passed。
- 前端正式清单：110 Vitest + 65 Node passed。
- production build：1971 modules transformed。
- py_compile 与 git diff --check：passed。

测试过程中的无效命令已如实保留：一次系统 Python 缺 pytest；一次完整套件缺测试 import 路径而在 collection 退出；一次把本应隔离的 API 测试与全套同进程运行，产生三项状态污染，同时发现一项真实 mutation inventory 漂移。补齐既有路径、恢复隔离运行并登记新增 mutator 后，最终矩阵全绿。

## 未做

- 未修改 Study A 两个真实 SQLite 数据库。
- 未重新运行任何产品模型、检索、下载、OCR 或翻译。
- 未启动或触碰 live 8910、5186、5285。
- 尚未在真实 Study A 页面执行这次人工复核，也未做该状态的 ego(lite) 浏览器呈现验收。

## 下一安全动作

在 Study A 隔离运行时读取当前 revision 20、既有快照 `wref_search_95d54c91e3c4fb21b234` 和旧确认 `ct_conf_64147b6c4d57d64cb9b9`，先只读核对 `reconfirmation.required` 与 59/256 预选篮子；随后用 ego(lite) 验证宽屏 bullet 条件、默认预选和一次确认交互。只有页面与合同一致时才执行真实人工复核写入；仍不得触发外部工作。
