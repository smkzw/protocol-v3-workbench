# WP0 接管与双链身份锚定
**类型：只读梳理＋最小交接定义；依赖无；不启动模型/服务。**

输入：START、REVIEW、FLOW_REVIEW、GitHub证据、当前Trellis。相关文件：App.jsx；SynopsisProjectIntake/AuthoringJourneySetup；ProtocolIntakeWorkspace/StudyContextWorkspace；main.py；authoring_journey；protocol_workflow/api/design.py/research_intake.py/composition.py；manuscript_documents；build_genoffice_renderer.sh；同级genoffice-upstream。

步骤：
1. 核对HEAD/dirty/在途任务，只补已有审阅后漂移，不重新全盘考古。旧3项runtime dirty和上游dirty patch保留。
2. 用实际入口整理project→journey definition→v3 study→template semantic node→candidate→semantic document→Office head身份表。映射缺失明确记录；不能按相同中文标题或数组下标猜配。
3. 确定现有Office链的当前稿所有权和来源/决定迁入映射，记录旧路径兼容策略及确认出处；源码适配归WP1、候选接收/激活归WP2。本包不迁移项目数据、不切换写入路径。
4. 在允许的只读范围核实配置路径/启动命令/flags/数据库根/bundle版本；未运行或进程旧代码标UNVERIFIED。不要为填表启动服务，不把源默认值当运行事实。
5. 固定上游base commit、所有必要dirty文件与未跟踪protocol-office.ts的哈希/补丁清单；必须保留可重建材料，但不复制秘密或整个node_modules。

产出：更新Trellis接线映射及运行限制，引用现有FLOW_REVIEW和manifest。完成即推进WP1；不生成额外管理册。

统一验收条件（WP6执行）：实际两入口的来源及已确认设计进入同一Word项目；保存/重开/下载身份一致；renderer由记录的源+补丁可重建；运行flags/DB/根和产物有证据。对应W01/W02/W06、A01/A02/A25。
