# 对象 Schema 定稿（M0 第一天 · 02_ARCHITECTURE 落地）

权威来源：plans/mw_reboot_20261017/02_ARCHITECTURE.md。本文件是代码层契约，字段命名 snake_case、JSON存储、迁移只加不改。

## 1. ProjectProfile（复用 authoring_journey.product_profile，补字段）
```json
{
  "drug_name": "string",
  "target": "string|null",            // 靶点，可选
  "molecule_type": "antibody|small_molecule|peptide|aso|sirna|other",
  "route": "oral|iv|sc|im|topical|inhalation|other",
  "indication": "string",             // 标准化术语在 eval 侧归一，代码不分支
  "phase": "II|III",
  "optional_materials": {"ib": "path|null", "synopsis": "path|null"}
}
```

## 2. CompetitorSet（新建，存 runtime 不进 git）
```json
{
  "set_id": "string",
  "project_key": "string",
  "studies": [{"study_key": "nct|string", "title": "string", "phase": "string",
               "has_protocol_file": true, "source": "ct_gov|pubmed|user_upload",
               "category": "same_target|same_class_route|same_indication|adjacent",
               "priority_score": 0.0, "priority_reasons": ["string"]}],
  "confirmed_topk": ["study_key"]
}
```

## 3. StyleKit（新建，数据非代码，runtime 存储）
```json
{
  "kit_id": "string", "project_key": "string", "built_from": ["study_key"],
  "per_node_examples": {"<semantic_node_id>": [{"text": "≤600字", "study_key": "..."}]},
  "terminology": {"drug_class_terms": ["..."], "endpoint_names_zh": ["..."]},
  "length_profile": {"<semantic_node_id>": {"p50_chars": 0, "p25": 0, "p75": 0}}
}
```

## 4. ClauseBank（新建，取代 repository 硬编码骨架）
```json
{
  "clause_id": "string",              // 如 ae_sae_reporting
  "semantic_node_ids": ["..."],
  "consensus_text": "string",         // TopK 竞品共识写法
  "anchors": ["ICH E6(R3) 4.11|中国GCP..."],
  "sources": ["study_key"],
  "variable_params": [{"name": "safety_contact", "kind": "string"}]
}
```

## 5. StudyDefinition（复用现有 typed 对象，唯一事实源，不复制字段）
现状即契约：typed StudyDefinition 已有 framing/picos/design elements。**决定**：不新建表，SectionCard/渲染器按 fact_path 引用其字段。

## 6. DecisionCard（复用 authoring_journey 推荐卡，扩schema）
```json
{"card_id": "string", "fact_path": "endpoints.primary",
 "question_zh": "string",
 "options": [{"label": "string", "analysis": "string"}],
 "recommended_index": 0, "rationale": "string",
 "competitor_practice": [{"study_key": "...", "summary": "string"}],
 "affected_node_ids": ["..."]}
```

## 7. SectionCard（新建；由 111 份冻结章节合同压缩生成，不是手写）
```json
{"card_id": "string", "semantic_node_id": "TP-MA-07节点ID",
 "tier": "D|C|N", "purpose": "≤80字",
 "required_elements": ["string"],
 "consumes_fact_paths": ["fact_path"],
 "consumes_clause_ids": ["clause_id"],
 "style_example_budget": 3,
 "length_range_chars": [200, 1200],
 "risk_level": "high|medium|low"}
```

## 8. SectionDraft（扩展 full_draft section candidate）
```json
{"section_id": "string", "semantic_node_id": "...",
 "text": "string",
 "claims": [{"span": "string", "support": ["evidence_id|fact_path|style_only"],
             "confidence": "high|medium|low", "why_unsure": "string|null"}],
 "decision_requests": [{"fact_path": "...", "options": ["..."], "recommended": 0}],
 "gaps": [{"kind": "source_missing|decision_pending|not_retrieved|mapping_failed",
           "where": "string", "next": "string"}],
 "checker_results": [{"checker": "string", "severity": "info|warn|fail", "detail": "string"}]}
```

## 9. Manuscript（复用 manuscript_documents + Office snapshots，文档级发布）
唯一当前稿；legacy working_copy 只读迁入。发布=文档级 release + 缺口清单（gaps 汇总），取消逐章冻结。

## 通用规则
- 所有新对象 JSON 存 SQLite 或 runtime JSON 文件；eval fixtures 走 runtime 不进 git。
- 语义节点 ID 一律用 TP-MA-07 v2 树，不再出现章号/标题关键词。
- 渲染器（样本量/剂量/SoA）只读 StudyDefinition + SectionCard，输出确定性文本。
