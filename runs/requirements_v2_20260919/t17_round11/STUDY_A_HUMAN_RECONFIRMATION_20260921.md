# Study A 原隔离运行库人工复核

日期：2026-09-21

项目：`proj_user_8a5a00cb014a`

## 执行前

- 使用 SQLite online backup 为 18 个数据库建立完整前置备份；
- journey revision 20，状态 `corpus_not_ready`；
- 原检索快照 `wref_search_95d54c91e3c4fb21b234`；
- 原分诊 run `ct_run_64da04e8e33f89dc728f`，状态 `confirmed`；
- 315 条候选中保留 59 条、排除 256 条；
- `reconfirmation.required=true`，来源确认 `ct_conf_64147b6c4d57d64cb9b9`。

## 执行动作

通过独立 5298 API 直接提交已在干净副本中验收的 `reconfirm` 请求。请求沿用全部既有人工分类、当前 journey revision 与来源确认，不调用浏览器自动研究，也不启动模型、公开检索、下载、OCR或翻译。

第一次 shell 命令使用了 zsh 只读变量名 `status`。命令替换中的 curl 已先执行成功，随后变量赋值报错；复核输出时再次使用同一 idempotency key 提交，因此 API 收到两次相同请求。第二次是幂等重放：最终只有一条 durable confirmation，journey revision 未再次增加。此处保留真实经过，不把两次 HTTP 请求误写为一次。

## 执行后

- HTTP 200；confirmation `ct_reconf_81450fa2caf9cf004f20`；
- kind `human_reconfirmation`，source confirmation `ct_conf_64147b6c4d57d64cb9b9`；
- journey revision 22；
- 原 snapshot 继续绑定，corpus triage 为 `finalized`；
- projection `corpus_projected`；run 继续为 `confirmed`；
- 59/256 分类不变；
- `pipeline_advanced=false`、`external_work_repeated=false`；
- 日志只包含 GET、两次同键 reconfirm POST 与关闭服务。

SQLite 字节层变化涉及四个文件；其中 `medical_monitoring_batches.sqlite3` 与 `medical_monitoring_daily_runs.sqlite3` 的 `.dump` SHA-256 前后完全一致，只是 API 启动造成 SQLite 文件头层变化。实际逻辑变化只在 authoring journey 与 writing reference 两库。

结构化结果与前置哈希见：

- `runs/requirements_v2_20260919/f12_20260921/study_a_human_reconfirmation_20260921/pre_reconfirmation_manifest.json`
- `runs/requirements_v2_20260919/f12_20260921/study_a_human_reconfirmation_20260921/result.json`

下一步继续 F12 三研究完整旅程，先盘点 Study B/C 当前身份、运行节点和文档状态，再选择最短的真实闭环推进；不重跑 Study A 已完成的公开检索或分诊。
