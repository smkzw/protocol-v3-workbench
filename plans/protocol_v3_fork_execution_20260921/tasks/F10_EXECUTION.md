# F10 执行包：模板、文控、Word排版与当前版本导出

任务性质：未来任务定义；实际状态只在Trellis/HANDOVER_STATUS。依赖：F05, F06。
覆盖需求：R3, R4；验收：A13, A14, A19, A21, A23。

## 输入与范围
先读本包00_START_HERE、PRD、执行规范、临床内容合同及本任务完整受影响定义。
初始模板生成与原快照下载，原始SOP及已保存Office不可后台重写。
所有任务共同禁写：共享runtime/现场数据库、live8910、医学监查、外部SOP、只读plan-upgrade、凭证及旧不可变证据。

## 文件入口
- [services/api/app/protocol_workflow/agent3/word_export_production.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/word_export_production.py)
- [services/api/app/protocol_workflow/agent3/word_export.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/agent3/word_export.py)
- [services/api/app/protocol_workflow/api/manuscript_drafts.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/api/manuscript_drafts.py)
- [config/medical_writing/protocol_v3/templates/tp_ma_07_v2/template.json](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/config/medical_writing/protocol_v3/templates/tp_ma_07_v2/template.json)
- [tests/protocol_v3/test_production_export_ownership.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/tests/protocol_v3/test_production_export_ownership.py)
- [tests/protocol_v3/test_word_source_objects.py](/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/tests/protocol_v3/test_word_source_objects.py)
目录/拟新增文件以当前源核查为准；不存在的测试或实现先按本包状态解释，不假定它已完成。跨出上述文件先在现有checkpoint写出直接因果和最小范围，非必要不扩展。

## 微步骤
1. 复用本轮封面/TOC/textbox/页眉修复；最新trackRevisions与updateFields去重尚需最终新工件实证，旧截图不能绑定新hash。
2. 逐项区分模板说明、示例数据、合法签字空白、真实研究信息；清理初始模板不按蓝色/关键词全删，人工正文保持所有权。
3. 查机构/日期/版本默认1.0/缩略语/额外签字页是否有明确来源和适用性；未知显示缺口，不能猜真实机构。
4. 实现文档题注书签、交叉引用、TOC和表图目录、SOA横页、跨页表头/脚注、段落字体/孤行的正确生成与保留；逐项实际运行验证集中F12。
5. 当前已保存Office导出原字节，不生成模型、不重投影摘要/SOA、不换术语；文件名与内部项目/版本身份可核对。
6. 实现并说明Word原生更新域→保存→重开→PDF的交付路径；F12绑定生成/保存/PDF hash及producer取得原生证据，eCTD只判文档就绪范围。

## 预期交付
- 最小完整代码/配置变更及使用说明（本任务若只读，不造代码变更）。
- 源版本/hash、改动列表、执行命令/退出码、实际行为与未验证项。
- 源码核查与实现状态；运行验收证据集中到F12补齐，执行者不把implemented冒充verified。

## 可复用检查命令
从实施区根运行；带cd frontend的命令各自从根开始，不连着cd。以下命令留待F12集中验收；构建期仅符合BUILD_DISCIPLINE的必要阻塞诊断才运行。禁止逐微步骤、逐文件或逐修改运行。
```sh
PYTHONPATH=services/api:packages:.:tests:tests/protocol_v3:tests/protocol_v3/integration runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_production_export_ownership.py tests/protocol_v3/test_word_source_objects.py -q
```
命令期望：退出0且对应行为符合验收；现有失败先归因并保留，不通过改expected/xfail抹掉。依赖/路径变更先定位当前权威，不随意安装新环境。

## 下一步
完成实现后继续后续集成；完整样稿及Word原生证据在F12取得，限定不包含监管批准或未选第三方动态互操作。

## 构建期约束
遵守 [BUILD_DISCIPLINE](../BUILD_DISCIPLINE.md)：不扩建无当下需求的框架、抽象或状态系统；不逐改测试。完成最小完整实现后继续下一个依赖已实现的任务，集中验收前保留未验证标记。
