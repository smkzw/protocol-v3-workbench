你是本任务的单个有界工程执行worker，Codex是owner，遵循更高优先级指令和最新全局AGENTS。禁止递归派发、会商、网络检索、产品模型调用、服务启动、依赖安装、git commit/reset/stash、清理归档。不要关闭任务或宣称最终验收。

目标：为个人医学写作人员实现一张完整的复合给药候选卡，不把各期各组变成互斥选择。只创建以下三个文件：
frontend/src/features/medical-writing/protocol-workbench/RegimenProposalCard.jsx
frontend/src/features/medical-writing/protocol-workbench/RegimenProposalCard.css
frontend/src/features/medical-writing/protocol-workbench/RegimenProposalCard.test.jsx
并允许本runs/execution/mw_protocol_v3_regimen_card_ui_20260913/scratch/内日志与详细REPORT.md。禁止改其它源码/测试/manifest/计划/运行库。禁止触碰live/监查/8910/外部SOP。现有全局/项目指令、下列只读输入可读；普通目录定位仅限本实施区。

先读：/Users/smkzw/.codex/AGENTS.md、本区AGENTS.md、只读snapshot/clinical_worker.py和snapshot/recommendations.py（在本run目录）、现有ProtocolIntakeWorkspace.jsx/css及test、sourceRoleLabels.mjs、frontend/package.json及Vitest配置。无需全文扫描项目。现有产物维持不动，snapshot是本次props合同权威，不读owner可能继续改的源文件来改变合同。

公开组件：export function RegimenProposalCard({proposal, onConfirm, busy=false, error="", sourceDownloadUrl})。proposal是read_regimen_response结果：status/coverage/regimen/questions；regimen有canonical_state=proposed、periods[{id,label,timing}]、arms[{id,label}]、schedules[{period_id,arm_id,steps[{kind,timing,frequency,route,products[{name,dose:{value,unit},volume?:{value,unit}}],references:[{source_artifact_id,locator,quote}],source_support,requires_confirmation}]}]、unresolved_questions。owner将传整个提议快照，组件不得推断事实、选择第一个候选、写localStorage、API、DecisionRecord或confirmed状态。

视觉和交互：医学严谨但安静易读，中文，一张卡给出所有已列出时期/组/步骤，保留数值单位与体积，不计算换算，不把没有列出的组/期显示成停药/不适用。使用列表/自适应网格，窄屏390px不需横向滚动。正文16px，辅助至少14px，最低12px。显示“剂量方案”及小红tag“监管答辩级·需确认”，状态明确“建议，尚未确认”。依据可折叠，quote原样呈现，不展示locator/hash/内部英文枚举；同一source只出现一个下载链接，sourceDownloadUrl缺失则只显示引文，不伪造URL。source_support使用现有中文风格，历史资料不显示已批准。

主按钮“确认这套给药方案”，onConfirm(proposal)只在明确点击触发一次；没有回调、busy、proposal.status不是ready_for_review、regimen为空或存在questions/unresolved_questions时禁用并说明实际未决项。内部同步防双击，等待Promise期间禁用；回调失败保留全卡、显示可理解的错误，不自动重试；不要乐观显示已保存。外部error也可显示。不要额外必填理由、签名框或安全门。更换proposal后不把旧请求回调结果贴到新卡；owner负责CAS和后端确认有效性。

先写可证明行为的红测再实现。用现有node_modules/.bin/vitest定向跑这个新test，允许跑相邻Source/Workspace测试但非全仓重跑；保存红/绿日志到scratch。验证四个期组单元、负荷/维持都可见；明确点击前零回调；双击和未决禁用；失败保留；quote/下载去重。不能弱化旧expected或新增xfail。无需浏览器启动，owner后续实际浏览器验收，明确这是未挂载组件。

完整详细报告写scratch/REPORT.md，记录三个文件sha256、测试命令/实际结果、限制。runner管理worker_01.md，禁止直接写它；final返回简洁报告与详细报告路径。不要生成其它流程角色或cleanup建议。
