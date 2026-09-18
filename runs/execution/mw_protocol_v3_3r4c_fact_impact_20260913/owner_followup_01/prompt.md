# 3R.4C 同会话定向修复，owner已判首轮验收未通过

你仍是原 bounded execution worker，不是独立reviewer。恢复原 session sess_f7fa1d2f-dc43-49d6-9b90-f0758deed6d9，保持 GLM-5.3-Flash:max、E04。原prompt全部范围与纪律继承；产品写允许仍只有 dependency_graph.py、test_dependency_graph.py、test_fact_labeled_impact.py 和你自己的run，不改B/canonical/application/Trellis/Plan，不自行验收，不递归派发，不运行产品模型/服务。

先读最新全局AGENTS。首轮2553.682秒正常terminal，模型request/response/observed effort匹配，原3文件hash匹配报告；但owner已复现两处功能错误。证据脚本与实际JSON（只读）：runs/mw_protocol_v3_3r4d_preflight_20260913/c_owner_cases.py、c_owner_cases.json。最初synthetic probe漏source_contract_sha只是setup问题，当前脚本带真实合成合同hash且可直接执行。

1. 基础fact_requirement同时受B conditional_fact_paths控制，条件未知时改payload.x，当前返回confirmed_reopen；应候选，不能用FACT_REQUIREMENT早返回绕过B显式条件释放/未决语义。基础required并不意味着永远无条件。
2. 同一when_active字段由两个规则共享，一条applicable、一条conditional，改payload.x，当前返回candidate_check；应shared active owner wins，实际有效内容需要重开。当前循环任何unknown即False，与B已验收语义相反。

请把这两个owner反例纳入明确预期测试，复用B的source-bound declaration和三态评估，按字段与章节的实际owner判断。另验证全部inactive/全部unknown/active+unknown/active+inactive，触发条件由true变false的义务释放仍要刷新旧内容；纯无条件fact仍会重开。不要把unknown统一当false，不要只靠旧测试数字，不要让调度或同一字段的其他章节把本章节条件判定覆盖掉。无需造新规则平台；若B需暴露小纯函数共享语义，先在报告提具体修改方案，不越界改B。

你首轮“context cleanup偶发顺序污染”判断不成立：owner当时在disjoint D文件执行红测试→修复，恰与全仓回归重叠。owner日志context_cleanup_red.log+代码修复证明确定性问题，非随机失败。保留旧日志，在新报告明确纠正；2198全仓不对应现在最新固定源，owner之后又加入显式事实修订路径。此轮只跑你3R.4C相关+必要B定向测试，不跑全仓避免读写交叉；owner在两部分冻结后联合全量验证。

owner现在继续D，仍不写你3个产品文件。你只在owner_followup_01中写新日志/报告，不覆盖首轮report/receipts；无需再探测产品连接。沿用一次同模型修复，runner本轮hardwait4500秒，在预算内完成工具和验证后输出原Execution Output标准6节，带最新文件hash和精确结果。未解决如实列出，不闭任务。
