你是本Codex任务的有界执行worker，仅负责3R.4C代码与功能测试；不是管理者或验收者。不得递归派发、会商、调用产品模型、启动服务或浏览研究资料。当前目录为唯一隔离实施区。先读最新全局AGENTS与适用项目指令；冲突时本明确有界合同和当前用户授权优先于历史固定路由。

目标：修复当前依赖图丢失事实标签造成的过度传播，并为D实际SQLite采用提供可用的确定性影响计划。用户希望修改一个研究决定时不反复确认无关内容，AI lead完整Ⅱ/Ⅲ期资料→推荐→全部适用章节→Word。B已通过其工程范围验收，2178测试通过，不代表产品已完成。

权威：plans/mw_protocol_v3_implementation_plan_v3_20260912.md的3R.4C全文与D接口验收要求；design v1.4；.trellis/tasks/09-11-protocol-v3-3r4/prd.md与checkpoint尾部；reviews/codex_mw_protocol_v3_3r4b_acceptance_20260913.md。
只写services/api/app/protocol_workflow/registries/dependency_graph.py、tests/protocol_v3/test_dependency_graph.py、新tests/protocol_v3/test_fact_labeled_impact.py，以及本run runs/execution/mw_protocol_v3_3r4c_fact_impact_20260913/的证据/报告。其他文件全只读；不要改Trellis、Plan、B applicability/fact_bindings/chapters、核心合同、canonical/application、全局配置、旧runs和fixtures。原树dirty，不提交/重置/stash/清理。owner将独立验收整合。需要允许路径外改动只提出具体最小建议，不自行执行。

先读完整dependency_graph及对应测试；B applicability.py/fact_bindings.py作为真实可复用输入，不另造规则或事实平台。模型决策、UI、医学充分性不是本任务范围。

必要行为：
1 原反例runs/mw_protocol_v3_3r4b_20260912/fresh_review_20260913/owner_c_reconnaissance.json：A{x},B{x,y},C{y}只改x只能直接影响A/B，不可因B与C共享y重开C；明确派生实际改变y后才传播y。加正式红测再修。
2 区分事实直接使用、明确dependency_ids调度、语义一致性关系。保持changed paths和via_paths，调度真实扇出不截断；候选修复与实际确认重开分开。摘要投影不反向使未变事实失效。C图输出不是医学批准；D负责在同一UoW实际采用，不能以函数重复调用相等称幂等采用。
3 适用性unknown保留候选，不直接失效确认；false不能作为缺值，true义务保留共享owner逻辑。复用B的当前来源绑定和三态语义；不要仅按旧3R.3静态规则集合把所有conditional成员当无条件。可用清晰最小的新增可执行计划入口保留旧诊断接口，但新计划必须用于D后续消费，不能只换名保留有缺陷执行行为。若新增API，报告完整签名/来源绑定/调用示例与边界；不要从and组合擅自推断临床因果。
4 未知依赖/缺repair owner图仍能诊断查看，但生成可执行计划必须拒绝；hard cycle拒绝，双向一致性边不误判环。保留原诊断负例。
5 impact_sha256是投影hash不是logical work key。若传before/after，实际原生JSON值变化必须保留false与0等类型差异，同事实同值不得伪造变化；别名字面canonical键复用affected_chapter_fact_paths，不自行把点号拆地址。
6 新行为应绑当前组装registry/B规则，而非只用旧final_all8_assembled。旧图测试有同构_reference_closure和24/31旧过度扇出断言，用户已允许这类不影响科学性的旧阶段断言升版，必须逐项写旧行为/新独立期望/证据；不删负向fixture、不xfail、不弱化真实义务，不靠复制BFS当独立oracle。保留旧历史产物。所有新行为用小型明确期望集合，加当前真实registry完整扇出及版本绑定检查。

按最小完整改动实现，避免通用图平台/第二事实库/泛型DSL。需要权衡时依实际源与上述用户结果判断，报告未解决项，不擅自扩大权限。不要关闭任务。

测试环境：env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)" LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:. runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest <定向文件> -q -p no:cacheprovider --tb=short。先定向，本任务完成后可跑tests/protocol_v3一次并写本run新log/xml，不重复无因全量。不得npm install或安装依赖。超长原runner等待，128内部预算由runtime管理、7200s hard timeout；慢不自行重启/切换。

最终报告保存本run/report.md，返回相同摘要，必须含以下精确标题（只是runner要求的报告格式，不授予管理角色）：
# Execution Output:
## Boundary And Context Check
## Work Performed
## Artifacts And Evidence
## Commands And Observations
## Blockers Or Missing Environment
## Rerun Requests Or Next Step
写实际修改路径、源hash、红绿测试与真实计数、未完成义务/接口使用例；如无法完整实现必须明确INCOMPLETE，不把候选标接受。
