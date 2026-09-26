# G3 覆盖率报告 + G4 写入边界/恢复身份验证记录 · 0927V1（2026-09-27）

仓库 protocol-v3-workbench；验证时 HEAD=5b4c8c11692fc3118eb21bfe80877f5ce9d76c65（全程未变）。
忠实度晋级维持暂停：本报告**只报数、不翻转任何状态**（红线3），全部离线零模型（A16），隔离runtime库以SQLite只读模式打开（红线2）。

## 一、覆盖率盘点（只读，当场实读）

对象库：`runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/isolated_runtime/writing_reference.sqlite3`（URI mode=ro，探针自带防误写自检）。
探针：`g3_coverage_probe.py`（留档于同目录），分类规则与产品评估器 `_evaluate_integration_for_reeval` 的判定顺序逐条对齐。

| 指标 | 当场实读 |
|---|---|
| fidelity_blocked 总数 | **165**（与0926快照口径一致，本表以实读为准） |
| 按新绑定链可复检 | **0** |
| data_missing | **165（100%）**，唯一原因＝`hy_blocked_raw_fragment` |
| 涉及批次 | 1个（wref_translation_batch_da229e6a…） |

抽样核验（3项）：翻译修订行均在、链字段（chapter_integration_result_id）均在、integration行均可按id找到——**绑定链本身没有断**；不可复检的原因是行内容：blocked_raw_provider_output非空（Hy拦截的原始片段），其中部分行另有最多8个chunk，但按评估器设计（writing_reference_translation_batch.py:8918-8924 "Hy-blocked fragment would fabricate chapter-wide omissions"）一律fail-closed为data_missing。

**结论（四段式）**：当前165项忠度拦截，在现有确定线复检口径下**没有一项可以离线翻绿**——它们的integration行带的是被拦截时的原始输出片段，不是可复算的完整候选。这不是绑定缺陷，而是这批数据的产生方式决定的：需要的是重新翻译（新的管线运行），不是重新检查旧片段。因此任何"晋级165项"的路径都必须走真实重跑，而重跑属于暂停中的放量决策（红线3），本报告不执行、也不预测通过率。

## 二、G3 修复：复检绑定改沿权威链（反例→修复→正例）

- 反例（修复前，stash法对修复前代码实跑）：G3-R1 在 (plan, chapter) 精确SQL脱靶、LIKE前缀命中多行时，启发式取"最新完整"的冒名行（`integration_g3r1_impostor`），把复检绑到错误的候选上；G3-R2 条目章节为span作用域变体、精确与LIKE双双脱靶时，即使证据链完整也判 data_missing。8项反例红（`g3g4_red_before_fix.log`：8 failed, 2 passed）。
- 修复：`reevaluate_fidelity_blocked` 第一阶段解析顺序改为——①条目翻译链（translation_id/translation_revision → WritingReferenceTranslationRevision.chapter_integration_result_id，即下游合同边界 :1855-1865 已强制的同一字段）优先；②链歧义（同组出现多个不同integration id）一律 data_missing（`ambiguous_translation_chain`），绝不猜；③仅当组内无任何链时才走既有 plan/chapter+前缀启发式，且在审计detail中如实标注 `binding="plan_chapter_or_prefix_fallback"`。
- 证据字段（A19）：审计detail新增 `binding`、`candidate_hash`（最终候选integrated_text_sha256）、`checker_version`（CHECKER_VERSION），与既有的 integration_id/chunk_ids/previous_failure_codes 并列。
- 正例（修复后）：同命令 **10 passed**（`g3g4_green_after_fix.log`）——R1断言审计detail的integration_id＝链上行、binding＝translation_chain、复检结果rejected（真实漂移候选照旧拦）；R2证明精确/LIKE双脱靶时链仍把可复检候选带回复检（rejected，非data_missing）。

## 三、G4 修复：写入边界 + 恢复身份（反例→修复→正例）

1. **写入边界（字典级重校验）**：`_insert_item_with`/`_write_item_with`（translation批）与同名辅助（preparation批）在落库前对全量payload执行 `model_validate(model_dump(mode='json'))`——`model_copy(update=...)` 不重新校验的旁路自此关闭，非法字段组合在写入点显式失败。反例：伪造 `generation_status="bogus_status"` 的条目此前可静默落库（4个反例红"ValidationError not raised"）；修后4例绿。
2. **恢复身份（synthetic_recovery_ 前缀不再自证）**：`synthetic_recovery_*` 父id此前仅凭字符串前缀即跳过存在性校验直接分配lineage（:2556-2560注释自认）。修复为三处铸造点（prepare普通回退、_allocate结构无lineage分支、a0cc222-era一次性repair）都同步写审计事件 `document_plan_synthetic_recovery_parent`（target_id=父id，detail含batch与item清单）；分配点在执行通行（persist_migrations=True）时校验记录，无记录即抛 `synthetic_recovery_parent_record_missing`——只读预检通行保持原行为，预检/执行双调用法不受影响。反例：铸造不写记录（红）、无记录父id分配被拒（红，修复前方法不存在）；修后两例绿。
3. **往返与并发**：状态转换→保存→读取逐字段等值（roundtrip）与双写者同item同期望值恰一成功（CAS rowcount 1/0）作为控制组，修复前后均绿。

## 四、回归与边界

- 同模块族：`pytest tests/test_writing_reference_translation_batch.py tests/test_writing_reference_preparation_batch.py -q` → **82 passed + 18 failed**；18失败与623ff21基线同文件记录**节点集合完全一致**（A03逐节点比对，纯现存债务）。日志：g3g4_family.log。
- 验收车道：`pytest tests/acceptance -q` → **57 passed**。
- 边界遵守：未跑全量（红线5）；未翻转任何忠度状态、未执行phase2（红线3）；隔离库只读（红线2）；改动限定四簇（reeval绑定/写入辅助/synthetic分配/prep辅助），未做顺手重构；`services/api/app/chapter_translation_pipeline.py` 存在他人并行改动（OCR并发下限常量），本切片未触碰。
- 债务与后续：165项的真实出路是"重新翻译"（属暂停中的放量决策，需正确性证明后另行授权）；写入重校验的单次开销在套件实测中无可见退化（G3/G4+族回归合计<30s）。
