跟进评审完成，报告已写入 `runs/mw_protocol_v3_3r5a_3r7a_fresh_review_20260913/owner_followup_01/report.md`。要点如下。

# C03 跟进评审 01 — 结论：PASS

四项修复全部独立核验通过，无新增 P1/P2；另有一项首轮观察经查证属本人误报，正式撤回。

## 绑定与哈希

- `owner_followup_01/artifact_manifest.json` 绑定 252 文件，当前树逐一核对 **0 missing / 0 mismatch**；`changed_since_first_review` 恰为 4 个文件（content_quality 检测器、R03 提取器、r03_criteria.json、test_draft_marker_context.py），两个源 docx 未变。
- 新 `r03_criteria.json`（sha256 `8de39baa…2d84`）从冻结源用当前提取器再生成，与提交件 **cmp 字节相同**。

## 修复核验

1. **条件句执行条款**：正则新增 (若/如/如果)…未提供书面知情同意(书)?…(则)?(不进入筛选/不得参加/不得入组) 分支；`iter_unresolved_draft_markers` 改两级作用域（整句 fullmatch 优先，逗号子句兜底），偏移为 `sentence.start()+clause.start()` 的文本绝对偏移。我的探针（`followup_probes.log` P1–P8）：5 种条件句变体零误报；**真实草稿标记在段落与表格单元格中均检出且 offset 与字符串切片逐一相等**（如 `待医学经理确认` 25–32，slice-equals True；单元格保留 cell_id/行列身份）；锁库条款追加子句仍豁免且其后真标记仍检出；执行句尾部拼接草稿词无法藏匿；旧真阳性未变；两消费者仍接共享迭代器。
2. **investigator_center**：新旧 registry 语义 diff 恰一处——normalized_check 改为源句“负责开展试验的研究者”，其余 128 原子与 denominator(129) 不变，字节再生一致。首轮 P3-4 关闭。
3. **docstring**：改为 "zero-based paragraph-only order"，与实现一致。直接从源验证：顶层段落 27 个 / body 子元素 45 个，“填表人签字”唯一在 paragraph-only 序数 **[22]**，registry 定位 `body/paragraph[22]` 且 raw_text 逐字相等——构件定位未变化，worker 报告的 [39] 属另一套序数、非源真值。
4. **撤回首轮 P3-1**：实测 `/Users/smkzw/.codex/tools/workflow_routes.json`（live 全局清单）sha256 = `ef297ff3…` 与 `dispatch_contract.route_manifest_sha256` 完全一致。首轮我误将该字段与生成的 per-dispatch 子件 `scheduled_route_manifest.json` 比较，属对象错配，不存在漂移。未编辑任何全局配置。

## 测试与证据

- 受影响闭包 7 个测试文件（隔离 venv、env -i、no cache/pyc）：**93 passed / 0 skipped**（= 首轮 95 − word_source 6 + 新增 4 个条件句参数组，数目自洽）；owner 的 `owner_review_followup_green.log`（79 passed）存在且为另一子集，仅作对照，我的独立运行为准。
- 无 pyc / pytest cache 残留（find 复核为空）。

## 残余观察（保守方向，非缺陷、无需修复）

- 条件句与真实草稿标记**同句以逗号相连**时（“…，则不进入筛选，样本量待医学经理确认后写入。”）：真实标记检出且偏移正确，同时条件子句因逗号拆分回退报“未提供书面知情同意书”——与代码声明的取舍一致的过度检出，不产生假通过；未来放宽须保持同句可见性。
- `projection_completed` 仍为调用方声明、真实投影 V1 pending（按本跟进合同确认）；“暴露标准”源词保留，语义裁定留 V1。

医学充分性、原生 Word、UI、产品激活验收均不在本次范围；Trellis 任务未关闭，owner 验收独立进行。
