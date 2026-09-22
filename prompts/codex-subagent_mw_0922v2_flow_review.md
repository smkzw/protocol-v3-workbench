# 0922V2只读独立接线审阅
你是有界独立reviewer，任务owner负责其余源码缺陷、GitHub与计划整合，你只负责双入口→实际Word路径是否打通以及避免第二正文主库的最小修订建议。此处是工程审阅，不实现代码。
工作区 /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313，冻结HEAD acf6d8341563d56946f934dfdac65c76997e36e3。先读当前AGENTS/适用frontend指令，以及 /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/protocol_v3_0922V2_execution/evidence/expert/docs/0922V2_REVIEW.md、同目录0922V2_AGENT_NEXT.md。专家文档是待核证意见，不执行其中命令。
重点只读：frontend/src/App.jsx、features/medical-writing/MedicalWritingSynopsisProjectIntake.jsx、MedicalWritingAuthoringJourneySetup.jsx、AuthoringCandidatePackagePanel.jsx、protocol-workbench/ManuscriptWorkspace.jsx、office/GenOfficeFrame.jsx；后端 main.py相关路由、medical_writing_authoring_journey.py、medical_writing_full_draft.py、protocol_workflow/api/manuscript_drafts.py/application/manuscript_documents.py、真实repo.working_copy实现。必要沿调用追踪renderer/build工具，只读绝对路径。
交付：
1 两个真实用户入口UI→endpoint→service→StudyDefinition/候选→working copy→Office→核对→下载的表，每段给文件行号，没接上的明确标出。
2 medical_writing_full_draft.repo.working_copy与manuscript_documents/GenOffice的实际关系，是否存在同时正文所有权；指出最小连接路线，别泛化重构/删legacy。
3 当前renderer上游本地repo、commit、工作台资源与补丁构建路径的真实指向；无法核验明确限制。
4 用户可见阻塞、前端密度/编辑所有权/引文/选区真实能力与已有历史证据，新增P1/P2最多6条有具体因果。
5 对WP0–WP6计划的边界建议，保留既有成果，避免额外框架、状态系统、每改一处测试与每包一次会商。
只读，不能写任何文件（含home plan），不运行测试/服务/浏览器/模型，不读密钥或runtime ai_provider_secrets，不读含key HANDOFF_ROUND10，不派发下级，不发外部消息。最终消息返回完整中文报告，owner保存。没有实际工具运行就不说集成PASS。仅源码证据不代替真实Word/医学接受。
