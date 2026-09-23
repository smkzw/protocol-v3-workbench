Working...
T17-R15 tester4 interim status (session continues on next wake):

- Project `MW-II-EE441A2B` created from scratch (entry B, zero attachments); competitor retrieval 637 candidates → 55 retained → full-text extraction 55/55 done → translation/analysis phases.
- Literature module works: DOI import (NEJM 2010 tanezumab OA) + PMID dedupe ("已与现有文献合并（按DOI识别）"), search filter, invalid-input error.
- Blocking observation being timed: Chinese regulatory candidate batch `cms_regulatory_zh_v1` fails twice (`translation_generation_failed`, then `document_plan_anchor_filter`, 228/230 failed, 0 candidates), which keeps 语料准入 pending; pipeline is now in 第一轮深度分析 with save/step-1 controls disabled.
- Monitoring job bg_1 running; waiting for its result.

EXIT=0
