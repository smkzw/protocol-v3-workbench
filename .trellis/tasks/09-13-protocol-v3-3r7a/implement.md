# 执行范围

Owner direct：当前误报与三消费者共享原因可通过实际反例和源检查决定，无需额外executor；独立审阅按完成时实际解释性触发。允许services/api/app/medical_writing_content_quality.py、ai_task_runner.py、medical_writing_full_draft.py；新增protocol_workflow/terminology/{__init__,library}.py、config/medical_writing/protocol_v3/terminology.json、tests/protocol_v3/test_terminology_library.py及必要消费者反例测试、own run/Trellis/Plan。

先保存涉及源的当前hash/副本，必要失败测试后最小修改。只跑相关测试，不同时全量协议回归。没有产品模型、服务、OCR、Word、commit/archive或其他外部改动。旧真实占位测试不得弱化；新库不声称V1已接线。
