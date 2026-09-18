# Implementation

1. Worker先读产品ports/application/events/storage及现有tests，补有判别力的集成测试；不复制已存在helper或另造存储。
2. Worker所有权仅tests/protocol_v3/integration/及runs/mw_protocol_v3_1r3_20260905/新证据；主Agent负责后续最小产品修复和历史对账，不并发修改这些测试。
3. 先观察新增测试在当前产品上的真实结果；有缺陷保留红测后再安排最小修复。覆盖新增但当前实现已正确时如实记首次通过，不人为制造红测。
4. focused与protocol_v3回归，检查收集；worker不改既有fixture/expected、不自关任务。
5. 主Agent独立重跑、fresh verifier后记录功能验收，之后1R.4。1R.2全仓债务在P1R-G1前继续对账。
