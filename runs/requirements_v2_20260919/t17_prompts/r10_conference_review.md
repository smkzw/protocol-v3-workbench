你是T17第十轮会商审阅者（资深架构+质量双重视角）。请审阅第十轮四场景测试的四份测试者报告与聚合报告，对发现的问题进行独立审阅、复盘、深挖根因、举一反三。

## 输入材料（全部存在，直接读）
- 聚合报告：/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919/t17_round10/AGGREGATE.md
- 四份原始报告：同目录 tester1_report.md / tester2_report.md / tester3_report.md / tester4_report.md
- 代码库根目录：/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313
  - 后端：services/api/app/（protocol_workflow/ 为方案工作流，agent1/seed agent2/design agent3/manuscript）
  - 前端：frontend/src/features/medical-writing/protocol-workbench/

## 你要做的
1. 逐项审阅聚合报告的 P0-A（初稿生成停滞，三测试者复现）、P0-B（确认门禁不收敛，三测试者同族）、P0-C（跨项目内容串染）、P1 各项：判定 真缺陷/误报/环境因素，并给出代码级根因假设（指出可疑文件与函数，不要泛泛而谈）。
2. 深挖 P0-A：初始生成能产出 6-10 章（说明AI调用与装配链通），随后"继续写作"停滞且前端0网络请求——根因在前端状态机、还是后端 durable executor/durable job、还是章节数据状态？给出你最可能的假设与验证方法。
3. 深挖 P0-B：门禁为什么会"每轮生成新未决项并要求确认上一轮自身补答的内容"？这是确认后事实未回写进下一轮生成的输入，还是needs_information判定逻辑把已答项重新算未决？
4. 深挖 P0-C：研究理论依据章节为何装进了另一项目的适应症/机制？沿"章节内容来源"查装配/导出合并逻辑，判断是跨项目读取、还是导出时把演示项目/旧项目内容并入。
5. 举一反三：每类根因还可能影响哪些章节/环节。
6. 给出修复优先级排序（P0>P1，考虑用户价值与修复成本）与每项的最小验证方案。

## 输出
最终回复=完整审阅意见书（中文，markdown）：每项问题一节，含 判定/根因假设（文件:函数级）/修复建议/验证方法；最后给 Top 修复优先级清单。不要修改任何代码。
