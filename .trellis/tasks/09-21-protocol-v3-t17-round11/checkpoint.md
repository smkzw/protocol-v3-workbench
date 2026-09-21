# 当前锚点（2026-09-21）
状态：in_progress，用户授权持续实施，未阶段暂停。原生Goal旧paused状态未篡改，新prompt见plans/mw_protocol_v3_goal_prompt_20260921.txt。
本轮采用 direct 后接 independent conference：Study A 的检索快照续接、人工确认投影与当前 SQLite 状态紧密耦合，由 owner 做一个最小完整修复；冻结修复和实证后，再由 fresh reviewer 独立检查是否错误复用了已失效语料。构建期间按完整批次集中测试，不逐处测试。
2026-09-21 纠错结果：首次 revision20→22 投影在会商中被证明医学事实已变更，owner 已从在线备份将 journey/writing-reference 两库完整恢复到 revision20；逻辑级逐表哈希与备份完全一致。源码现保留同一 registry snapshot，但 triage criteria 变化会清空 active discovery/corpus projection 并要求新的人审；stale run 不得历史恢复，恢复异常会持久化。集中回归 469 passed。会商同session `sess_6dbc92ce-b722-45a0-ae67-dd518c02cfe2` corrective PASS。下一批实现“现有篮+当前标准”的显式人工复核与受控重绑，不调用模型、不重检索/下载/OCR/翻译；完成前 Study A 正确停在 corpus admission 前。
详细证据与进度：runs/requirements_v2_20260919/t17_round11/TAKEOVER_REVIEW.md。
执行+会商：恢复执行、fresh恢复审阅与续审、编辑链三次复核均已terminal；最后Word会商session52763已完成，不再poll。当前没有冻结源码范围。
当前：修正真实Word模板页眉/占位替换保真；定向测试session4765待收取。原生Word已打开own synthetic copy，目录运行时更新但文件未持久化更新，勿冒称Word格式全部通过。

2026-09-21 14:48 用户要求完成手头工作后无损暂停并递交GitHub。Study A authoring journey已推进到revision 20：framing/PICOS均完成，口服、多中心、随机双盲安慰剂对照、PASI 75主要终点、132例等事实已持久化，current_stage=corpus。真实暴露的stale revision草稿保存问题已做最小修复：只对明确HTTP 409 stale revision读取最新revision并重试同一显式草稿一次，网络未知结果不重放。该修复尚未做浏览器故障注入；未启动Study B/C，未进入完整初稿/Word链路。暂停记录：runs/requirements_v2_20260919/f12_20260921/MW_PROTOCOL_V3_R11_STUDY_A_NO_LOSS_PAUSE_20260921_1448.md；复盘：reviews/MW_PROTOCOL_V3_R11_RETROSPECTIVE_20260921.md。恢复时从Study A既有awaiting_corpus_admission继续，禁止重跑检索、分诊、下载、OCR、翻译和旧失败项。
暂停前最小静态核对：目标JSX esbuild解析通过，git diff --check通过；未运行组件/API/浏览器/全量测试。研究定义与流水线暂停快照已写入runs/requirements_v2_20260919/f12_20260921/。
停止5296 API时收到PICOS提交后的延后投影告警：confirmation ct_conf_64147b6c4d57d64cb9b9对应的triage未使用authoring journey绑定的immutable snapshot。PICOS revision20已提交，但语料投影未闭合；恢复后先核对snapshot/triage绑定并恢复同一投影，禁止重新分诊。5296/5196均已停止。
后续：真实呈现复验、Office历史列表隔离浏览器验证、当前Word内容核对接线、补答链等T17缺陷；不重复跑整轮模型掩盖未修问题。
环境：仅自有5293隔离服务（session85140）可停/重启；现有5186/5285未重启、共享DB只读，live8910与医学监查不触碰。历史文件/日志和接手前dirty均保留。

10:50 新有界执行mw_r11_design_choices_20260921：设计卡目前“展示多个选项但固定确认第一个”、未知确认意图未恢复。采用execution-plus-conference，因独立前端单元可并行且涉及科学选择落盘。worker仅占用DesignElementsCards.jsx与同名test.jsx；owner不并发改这两文件。路由/上下文以本包为准，不从历史模型名推断实际身份。
当前自有验证服务5293 session24768，Vite5193 session66234，替代先前90351/85140（已停）；现场5186/5285未动。

## 2026-09-21 fork执行包交接准备
用户最新要求：形成全面PRD/Plan/分步执行与验收包供gpt-5.6-sol:medium fork持续实现；约束过度设计与构建期逐改测试。当前模式execution-plus-conference：已收齐有界设计worker，独立审阅资料包，父任务负责资料/源码基线整合。
入口：plans/protocol_v3_fork_execution_20260921/00_START_HERE.md。F00–F11连续实现，F12集中测试；禁止每改一处测试一次。
设计worker26683终态完成，最终pi/openai-codex/gpt-5.6-luna:max；仅mock组件3项，后端忽略选择/非劣效字段差异仍待F01。audit-execution因跨时段路由解析失败退出1，保留不篡改，不作为产品阻塞。
自建5293/5193已停止，原5285/5186/8910未动。交包后父任务不与fork并发写源码；原native Goal未修改。最终HANDOVER_STATUS和SOURCE_STATE为移交来源。

## fork资料包交付
包入口与新Goal已完成；1名fresh native审阅者提出1 P1/4 P2，owner核对来源后全数修订：alpha范围、执行时机、选择身份/恢复兼容、明确科学确认/三态、历史审计不得阻施工。审阅handle01a0c1fb-393e-7cb1-8d09-f67545af0ff1已completed并关闭；无在途产品writer。
本包含14执行+14验收、34场景、600源码入口、43dirty源文件overlay。构建期不逐改测试；F12集中完整验收。产品未完成，F01真实采用/恢复后端合同仍待修复。
启动prompt：plans/protocol_v3_fork_execution_20260921/08_FORK_PROMPT.txt；目标prompt：同目录GOAL_PROMPT.txt；完整性证据：runs/requirements_v2_20260919/t17_round11/FORK_PACKAGE_VALIDATION.json。父任务交付后不继续写产品源码。

## 2026-09-21 Goal恢复与F01实施
F00重新锚定完成：包校验通过；HEAD 24c1ed1，dirty保留；自建5193/5293未监听，既有5186/5285/8910仅只读确认监听；无在途产品writer。当前task通过session 019fb62b-2a50-7ed0-8fb6-e66bbeb8e641重新激活。
执行模式direct：F01创建/查询/恢复/事实写入共用同一决定合同且文件紧耦合，由owner一次修复比另开共享写worker更可靠；F12再做集中独立验收。
F01实现中：用户选择进入决定option身份和实际primary objective事实；旧operation按legacy记录恢复且标选择未知；条件卡未知时可见，需用户显式确认适用性后与卡内容同一原子采用；planned_n写入现有canonical路径；NI字段、明确终点确认、旧revision不回退及原operation显式重试一并收口。未运行产品测试，完成批次后只做必要语法/静态检查并继续F02。

## 2026-09-21 F01/F02连续实现
F01源码实现完成、待F12统一验收：创建与恢复共用selection-bound决定记录；legacy操作只恢复为选择未知；primary objective实际按用户选项落盘；条件NI/期中仅在明确适用或用户同卡确认适用时可采用；planned_n进入现有canonical路径；未知结果可用原operation显式续存，旧回执不降低revision。补齐无output_sha返回二元空值及未知卡422路径。仅运行py_compile、esbuild解析和git diff --check，均退出0，未运行产品测试。
F02源码实现完成、待F12统一验收：模型问题支持推荐答案/2–3选项的结构化输出并兼容旧字符串；问题卡在给药建议处就地预选、允许少量修改；补答通过既有ApplicationService/CAS写入research.regimen_clarifications，保留question/answer/user source/origin run，不伪造外部quote；原operation可恢复，确认后由用户一次点击创建包含新confirmed_study事实的确定性后继run，旧run进入previousRunIds历史。blocked终态按钮改为只读核对，不再把recover伪装为重新生成。新run提示禁止重复询问已确认问题，真正新冲突仍需显式提问。仅做同一完整批次的py_compile、esbuild解析和diff检查，均退出0；没有运行组件/API/模型测试。
下一步F03：复核第十一轮已实现的整稿resume与共享runtime改动，只修仍存在的真实恢复缺口；不重复实现已闭合链路，不运行阶段测试。

## 2026-09-21 F03–F05连续实现
F03源码复核完成、待F12统一验收：第十一轮已有同run resume、失败章节隔离、局部纠错输入和旧图预算兼容；补齐恢复时对RESERVED与RUNNING两类死亡占用的一致回收，未重写既有恢复链。
F04源码复核与最小修订完成、待F12统一验收：保留Protocol v3无附件用户简述入口、DOCX空正文独立错误和当前产品模型登记；移除本流程中“不少于10字”作为继续条件，理由改为可选说明，科学确认仍保留。未改全仓其他有独立业务含义的旧合同。
F05源码实现完成、待F12统一验收：章节事实模型运行只生成候选，不再以AI actor后台写入研究定义；候选按章节显示实际建议，用户一次明确确认后才由USER actor/CAS落盘，研究变化时拒绝旧候选。缺口正文不再暴露node_id/fact_path，内部定位仍保留在SemanticBlock元数据；去除“对齐事例方案”提示，摘要不再用“研究药物/相应适应症”伪装已知事实，文档标题缺关键来源时不自动制造。F03–F05作为一个完整批次仅做一次语法/前端解析/diff静态检查，未运行产品、API、模型或浏览器测试。
下一步F06：复核并收口当前Office稿、候选、未保存输入与历史的同源关系；沿用现有快照与GenOffice，不新增编辑器或状态系统。

## 2026-09-21 F06/F07连续实现
F06源码实现完成、待F12统一验收：Office快照继续作为唯一真实可编辑字节；打开、连续保存、下载和历史读取共用同一operation/content hash链。新语义候选与已保存Word并存时，用户明确选择候选或旧Word；继续旧Word的保存沿用旧快照自身document revision/hash，不再错贴新候选来源；采用候选才绑定当前语义版本。双窗口仍按base artifact revision拒绝静默覆盖，失败时提供未保存DOCX本地备份。
F07源码实现完成、待F12统一验收：新增只读Office快照投影，直接解析最新已保存DOCX的段落、表格、脚注与XML定位；只对可确定定位的关键事实报告已定位/确定数值缺失，对结构化或改写内容明确列为未核对，研究版本变化时标记过期。该核对不创建第二正文库、不修改Word、不阻止保存/编辑/下载；页面把保存状态与核对状态分开显示。为避免过度设计，本阶段采用按需确定性投影，未新增常驻worker、第二状态机或模型调用；F12真实DOCX验收后再判断是否需要异步缓存。
下一步F08：收口Word对象级AI候选的prepare/recover/apply/undo与当前Office所有权，确保只修改授权对象且不会用语义稿覆盖人工Word。

## 2026-09-21 F08–F11连续实现与集中验收入口
F08部分实现、不得标完成：object revision模型结果已改为仅生成候选，后台不再自动写回语义正文；既有prepare/status/recover/apply保留显式确认。当前GenOffice没有稳定暴露真实Word选区/对象锚点给宿主，语义block_id不能冒充Office对象定位，因此尚未形成“当前Word选区→候选diff→基线未变才应用→撤销”的真实闭环。
F09部分实现、不得标完成：项目文献库已存在，人工元数据说明不再设10字门槛；但旧App插入回调只接旧working copy，未接Protocol v3 GenOffice。源码核查还确认GenOffice内置引用当前写入普通作者年份文本，虽保存source customXml，但不满足工作台宣称的GB/T 7714顺序编码、移动/删除后重编号和文献表联动。不得用静态标记或普通文本冒充真实引文对象；第三方EndNote/Zotero仍为未选择专项。
F10源码实现完成、待F12统一验收：当前导出优先返回最新Office快照真实字节，不再由语义稿覆盖人工Word；新增candidate/docx只用于显式打开新语义候选。既有生产导出继续承担封面、目录、题注/书签/REF、横向SOA、跨页表头和字段更新设置。
F11源码实现完成、待F12统一验收：复用研究设计+真实Word双栏，桌面改为340–460px稳定控制栏和至少720px文档区，1180px以下才回单栏；压缩嵌套卡片、导航和治疗方案间距，正文区随1920/2560增长。关键设计说明改为三条行动bullet，样本量/非劣效/期中分析改为标签—结论列表；品牌按钮使用#FF9900深色文字，风险仅#C00000；GenOffice和正文形成轻量层次，不增加装饰性3D或新布局框架。
决策：F08/F09缺口需要GenOffice上游对象/引文字段协议，继续在工作台层打补丁会形成第二编辑器或假能力，违反当前过度设计约束。先进入F12一次性编译、回归和真实呈现基线，将两项列入明确失败矩阵，再按实际阻断面确定上游最小协议修订。构建期间未逐改测试；F06–F11后尚未运行产品测试。
下一步F12：冻结当前源状态，先做一次合并静态/build/后端/前端回归；归因后启动隔离HTTP与ego(lite)宽屏旅程、真实Word字节和必要产品模型验收。live8910/5186/5285不触碰。

## 2026-09-21 F12第一轮集中验收
冻结HEAD仍为24c1ed128f14fa512f687efbd046a1a92b84ca13，dirty成果保留。frontend production build退出0（1971 modules）；完整前端清单15个Vitest文件/110项及48个Node文件/65项全部通过。新增真实测试使冻结清单由59升为63，已同步manifest、verifier计数/路径及digest bbc6a3920a4cfe572a998fe41f9c377564c3d10392e4c5cfc3d671d20d71bf88。旧Office URL与blocked“重新生成”阶段断言按当前候选所有权和只读核对合同升版；没有删测试或降科学门槛。
后端全回归最终2601 passed、1项Python 3.14未来行为warning，退出0。期间修复两项真实问题：旧兼容回执未回显selection_status时客户端保留同一确认意图已绑定选项；shared main项目创建不再直接导入storage，改由composition-owned admit_protocol_workflow_project维持单入口。迁移纯度断言改为检查本次新增import，避免完整套件既有模块污染造成顺序依赖。
ego(lite) TaskSpace213已完成并finish。隔离5294/5194均已停止，未触碰5186/5285/8910。真实GenOffice+产品SQLite/API在1440/1920/2560下frame宽1391/1871/2511px，均无页面横向溢出；真实纸张、页眉、表格和工具栏可见。代表性双栏CSS验收：1440左346/文档1011px，1920左460/文档1377px，2560左460/文档2017px，均无横向溢出。证据在runs/requirements_v2_20260919/f12_20260921/office-*.png和wide-*.png。5186当前项目只显示医学写作“功能未配置”，未冒充真实全业务E2E。
F12尚未完成：F08真实Word选区局部AI候选应用/撤销与F09项目文献到Word原生顺序编码引文/重编号仍缺GenOffice上游协议；实际产品模型跨研究/盲测、原生Word本轮保存重开、医学逐章验收尚未执行。下一安全动作是给GenOffice增加最小、版本化的宿主命令协议（读取稳定选区锚点、基线条件替换；项目reference映射为真实Word引用实体），先闭合F08/F09，再继续剩余F12，不新增第二正文库或假静态引文。

## 2026-09-21 F08/F09上游最小协议与集中验收
按用户最新构建纪律将F08/F09合并为一个完整批次，中途未逐文件测试。GenOffice上游增加同源`protocol-office.v1`宿主命令：复用现有DecorationSet迁移真实选区锚点；只接受同一段落/单元格文字；应用前逐字核对基线；撤销使用替换后锚点和替换文本做条件逆操作，后续新编辑存在时拒绝覆盖。产品后端新增Office选区候选端点，模型只返回候选文字，当前Office应用/撤销仍由iframe拥有；没有建立第二正文库或从语义稿写回Office。

项目文献库现直接挂入Protocol v3当前Word编辑区。插入产生可保存的`ADDIN CMS_CITATION` Word字段和现有`b:Sources`记录；编辑器按正文首次出现顺序同步数字标记，并以`CMS_BIBLIOGRAPHY_ENTRY`字段维护GB/T 7714-2015格式条目。移动/删除正文引文触发同一事务重排，未知第三方字段不改写。本系统字段在保存、关闭、重开后仍保持可编辑字段；未声称EndNote/Zotero动态刷新已经实现。

集中验证：GenOffice生产build通过（483 modules），工作台生产build通过（1971 modules）；正式前端清单15文件/110项通过；后端受影响集7项通过。一次直接Vitest文件调用因未加载仓库DOM环境产生7个`document is not defined`，改用唯一权威inventory runner后全部通过，未为错误调用改产品或测试。

ego(lite) TaskSpace214隔离5295真实闭环：选区锁定后先在非目标段落插入“【保留】”，候选仍只替换“保存前的原文。”；条件撤销恢复原文且保留“【保留】”。先插A、再在更前位置插B、后插A得到B=`[1]`、A=`[2]`且文献表B/A排序；删除B后两处A和文献表均自动回到`[1]`。保存为artifact revision 2并重开，4个CMS字段仍为`instrField`且可编辑。DOCX证据`runs/requirements_v2_20260919/f12_20260921/office_bridge/after-fields.docx`：2个CMS_CITATION、1个CMS_BIBLIOGRAPHY_ENTRY、1个heading字段，customXml含CMS_ref-a/CMS_ref-b来源；截图`office-bridge-fields.png`。5295已停止，TaskSpace214已finish。

F08/F09实现与本轮确定性/浏览器/DOCX验收完成；F12仍需产品模型跨研究/盲测、医学逐章充分性判断及原生Microsoft Word本轮打开/保存/重开检查。继续F12，不阶段暂停。

## 2026-09-21 F08/F09原生Word纠错与F12集中回归
独立gpt-5.6-sol:medium只读审阅handle `01a0c239-0853-7f33-9172-7c40dd12824d` 完成。审阅正确识别首版`after-fields.docx`的`customXml/item1.xml`存在两个顶层：原空`b:Sources`为自闭合标签，上游保存时原样复用后又追加来源与结束标签。Microsoft Word实际打开首先显示“无法读取的内容”，证实该问题为P0；没有接受Word自动恢复掩盖错误。

上游只做最小根因修复：`buildSourcesXml()`复用原根标签时把自闭合`/>`正规化为开放`>`，没有新增保存层或旁路。顺带收口审阅发现的申报数据损失：`SourceInfo`可保留有序多作者及卷、期、页、DOI，`b:Source`不再把“张三, 李四”折叠成一个人的Last/First，Protocol Office把项目文献已有结构化元数据传入Word来源。未扩建第三方文献管理系统；完整GB/T 7714文献类型覆盖仍留到三研究内容验收按真实缺口处理。

Word原生验收制品：`runs/requirements_v2_20260919/f12_20260921/office_bridge/after-fields-fixed.docx`（SHA-256 `eddecd7b081c029d0fa5a082f5ef52fff96c4a08334fe2683ab152b3e6607d7a`）在Microsoft Word无修复提示打开，显示2处`[1]`、参考文献标题与条目、原表格、页眉页脚；Word另存为`after-fields-word-saved.docx`（SHA-256 `d897da7de7dee44c3b456f85ab538e70c6bf8ab636b26dd2c8418c074849a1a0`），关闭后重新打开无提示。Word把4个复杂字段正规化为4个`w:fldSimple`，但2个`CMS_CITATION`、1个`CMS_BIBLIOGRAPHY_HEADING`、1个`CMS_BIBLIOGRAPHY_ENTRY`指令与缓存文字、2个来源、页眉引用和表格全部保留；全部XML/rels可解析。修复后的GenOffice parser再次读取Word保存件，来源、CMS字段、表格、页眉和页脚均可识别。

实际产品模型只完成三个“选区候选”边界病例，不等同完整研究旅程。持久证据`runs/requirements_v2_20260919/f12_20260921/product_model_three_cases/gateway-result.json`，SHA-256 `805b8629653f7e96ca9e31a7c1eb229b1ea464d59681ea73fc633848132844db`；声明`deepseek-flash`，观测`deepseek-latest-cloud`，probe通过。三次初答均为非JSON，原响应不改写地持久化；每例仅做一次同模型结构纠错后完成。优效无期中、非劣效含一次无效性期中、MDD盲测三例均未臆造输入外的样本量/alpha/剂量/主要量表。密钥只在内存，不进入制品。

本批次一次性集中验证：GenOffice build 483 modules通过；工作台build 1971 modules通过；前端正式inventory为15个Vitest文件/110项和48个Node文件/65项，全部通过；GenOffice docx-engine 1398通过、1跳过；后端锁定venv与完整项目PYTHONPATH全量2601通过、1项Python 3.14 tar未来行为warning；两库`git diff --check`均通过。此前两次后端命令分别因使用系统Python缺`app`、不完整PYTHONPATH缺`packages`在collection退出，未执行测试、未改源码/expected/gate；最终有效命令使用项目锁定venv。测试按完整构建批次集中执行，没有恢复“改一处测一次”。

独立审阅的P0非法XML已关闭，原生Word保存重开已关闭；其P1多作者与核心期刊元数据已最小关闭。仍未关闭且不得冒称完成：两个差异研究加一个独立MDD盲测的完整产品旅程、111章节适用性与跨章医学一致性、A01–A26其余场景、V02–V08、完整GB/T 7714资源类型/人工抽样、复杂富文本/整格/脚注对象级AI修改。下一动作继续F12，优先建立三个独立project/study/run/document/SHA身份并运行完整“资料→推荐→确认→初稿→当前Word→下载”旅程，再按一次集中矩阵修复真实失败；不阶段暂停。

## 2026-09-21 既有竞品篮子按当前条件人工复核
实施并独立会商完成：研究事实变化但 registry 检索合同未变时，系统沿用不可变快照和既有人工篮子，显示当前医学分诊条件与完整预选结果；用户一次确认即可建立带来源谱系的新人工确认并受控重绑。该路径不调用AI、检索、下载、OCR、翻译，也不推进父研究流水线。全排除理由按用户已授权决定取消任意最少字数，留空时系统写确定性审计说明。

会商 `sess_a19b465f-8d17-4bcb-bf41-c7f9af5fa580` 实证发现投影失败后界面无重试入口及revision-only假复核；均已修复。重绑失败现在保存确认并把run置为projection_pending，成功重试回confirmed；初次确认按run revision比较事实，人工复核按自身revision比较。冲突/过期统一409，审计文字区分AI初次确认与人工复核。同键重放不重复写决策。

集中验证：相关后端450通过；Protocol v3全套2601通过、1 warning；前端正式110 Vitest+65 Node通过；production build 1971 modules通过；py_compile/diff check通过。mutation inventory增加1条route、2条journey mutator并按用户已授权的阶段断言升版为236/134/197，没有新增门控。

阶段记录：`runs/requirements_v2_20260919/t17_round11/HUMAN_RECONFIRMATION_BATCH_20260921.md`；会商审阅与metrics见对应reviews/metrics文件。Study A真实库仍保持revision20暂停态，未写入。下一动作先在隔离运行时只读验证reconfirmation状态和59/256预选，再用ego(lite)做真实宽屏交互验收，确认无误后才执行Study A人工复核；持续推进，不阶段暂停。

## 2026-09-21 既有篮子浏览器验收与自动重检索修复

ego(lite) TaskSpace 12 使用 Study A 的 SQLite online-backup 副本验收。首次发现两项同源前端缺口：`search_plan.latest_snapshot_id` 为空时没有回退到既有 `discovery_basket_projection.snapshot_id`，导致复核面板不可达；挂载时自动研究 effect 还会误发新检索。污染仅限第一份验收副本，服务立即停止，副本从未变化的原库重建。修订后旧快照直接显示，自动检索被抑制，提示改为“无需重复检索/按需重新检索”，复核卡前置于候选列表。

干净副本实际一次确认成功：revision 20→23，snapshot仍为`wref_search_95d54c91e3c4fb21b234`，confirmation `ct_reconf_81450fa2caf9cf004f20`，kind `human_reconfirmation`，projection `corpus_projected`，59/256不变。日志无新检索、AI分诊、下载、OCR或翻译；原18个SQLite哈希清单不变。1920无横向溢出，复核卡由页面1578px前置到800px。ego截图接口三次内部超时，截图状态保持UNVERIFIED，未以其他浏览器替代。

集中验证：frontend build 1971 modules；15/110 Vitest与48/65 Node全通过；diff check通过。记录见`runs/requirements_v2_20260919/t17_round11/HUMAN_RECONFIRMATION_BROWSER_ACCEPTANCE_20260921.md`与同名acceptance目录JSON。下一动作先提交推送本批，再对原Study A隔离运行库执行同一确定性复核，继续F12完整三研究旅程。

## 2026-09-21 Study A 原隔离运行库完成复核

执行前对`three_studies/isolated_runtime`的18个SQLite做online backup。5298独立API读取确认revision20、315候选、59/256和原确认谱系后，提交同一人工复核。结果confirmation `ct_reconf_81450fa2caf9cf004f20`，kind `human_reconfirmation`，journey revision22，原snapshot继续绑定，projection `corpus_projected`，pipeline未推进，external work未重复。

一次shell变量命名错误发生在curl命令替换完成后，因此同一idempotency key随后被重放；库内只有一条durable confirmation，revision未二次增长。除authoring journey/writing reference外，两项监查SQLite仅字节头变化，前后`.dump`哈希相同。详细记录：`runs/requirements_v2_20260919/t17_round11/STUDY_A_HUMAN_RECONFIRMATION_20260921.md`。下一动作盘点Study B/C身份和节点，继续三研究完整旅程，不重跑Study A检索/分诊。

## 2026-09-22 Study A 全文补写 v0.3 与独立会商

执行加会商模式完成本批。产品默认路由已按用户最新要求收口为`opencode-go/deepseek-v4.1-flash:max`；Study A同一durable job完成85个空白章节补写，原始工件SHA保持`c2e98124598aa71a2e36eedb173cd24163d8a8504f41d9996a963cf241192da9`。修复大定位器持久化、完成件刷新恢复和窄侧栏审阅：1600×1000实测为312px目录+1202px正文、无横向溢出、85张候选和18张当前关键卡均可定位。用户文案已明确85章是与105章文档合并的待补批次，不再把85/85冒充全文完整度。

独立会商`01a0c4df-0312-7def-ad4c-5dbe282319c9`给出REVISE。数值忠实度良好，但4.4盲法角色/揭盲职责、14.1避孕要求存在无事实支撑的规则，背景/管理章节仍有通用填充，18张章级确认也不符合决定级AI lead。会商对“缺14章”的推断经主线程读取105章真实document session后缩窄：十个正文标题已有实质种子，1.1为结构内容；1.2研究示意图、1.3研究流程表和13参考文献仍是真实缺口。v0.3未采纳。

集中验证：后端受影响160通过；前端正式110 Vitest+65 Node通过；生产build 1971 modules通过；diff check通过。阶段记录见`runs/requirements_v2_20260919/t17_round11/STUDY_A_FULL_DRAFT_V03_20260922.md`。下一动作直接进入v0.4：输出显式决定项（推荐+备选）、把来源缺口与正文完成分开、拒绝无来源的项目实施规则，并把章级重复确认压缩为决定级队列；只重跑受影响生成块，不重复上游资料处理。

## 2026-09-22 Study A 全文补写 v0.4 合同
v0.4 合同已实现并完成集中验证：每章显式区分 complete、decision_required、source_gap；决定项包含推荐与备选，缺来源不再用通用正文填充；任一待决定/缺来源在任何章节写入前阻止整批采纳。已知含无依据规则的v0.3原始工件保持不可变和可读，但升为只读，不允许再采纳。宽屏审阅区显示决定卡和缺资料列表，当前仍通过既有研究设计流程补答。

执行节点`mw_r11_full_draft_v04_contract_20260922`实际使用deepseek-v4.1-flash:max、无fallback，但受原生plan mode限制未编辑；Codex直接集成并记录其越界只读检查。最终定向105 passed；同批更广受影响集163 passed、前端110+65 passed、build 1971 modules、diff check通过。阶段记录：`runs/requirements_v2_20260919/t17_round11/STUDY_A_FULL_DRAFT_V04_CONTRACT_20260922.md`。下一动作是闭合“推荐预选→用户一次确认→StudyDefinition→仅重生成受影响章节”的一键链路，再运行真实v0.4并做fresh医学会商；不重复检索、分诊、下载、OCR或翻译。

## 2026-09-22 Study A 全文决定卡与局部重写闭环
决定卡闭环已实现并经owner修订接受：模型必须从既有StudyDefinition可确认字段白名单提供`fact_path`；用户每次只确认一张卡；结果复用原CAS/幂等/审计通道，旧全文候选因研究revision变化失效，只为受影响章节创建新durable job。列表字段按合同塑形，结构化设计字段拒绝用散文静默写入。浏览器幂等键固定为job/decision/option，未知网络结果可安全重试。

执行包`mw_r11_decision_apply_20260922`声明主路由未产生可用可恢复结果，按manifest使用第一fallback `zcode/zcode/GLM-5.3-Flash:max`，session `sess_858de745-44cd-4934-b788-c22cfafd9776`完成；guard audit为ok。owner发现并关闭worker遗漏的`fact_path`合同P0。集中验证后端111 passed；前端正式110+65 passed，最终production build 1971 modules，diff check通过。旧v0.3浏览器只读状态已验证；真实v0.4决定卡尚待产品模型生成。阶段记录：`runs/requirements_v2_20260919/t17_round11/STUDY_A_FULL_DRAFT_DECISION_LOOP_20260922.md`。

下一动作直接使用隔离运行时与产品默认`opencode-go/deepseek-v4.1-flash:max`运行Study A真实v0.4；保持同一durable job长轮询，生成后先做三态/证据/决定绑定/章节完整性检查，再fresh医学会商，未通过不得采纳到Word。不得重跑检索、分诊、下载、OCR或翻译。

## 2026-09-22 Study A v0.4 产品模型结构恢复
两次身份探针均通过，声明/实际均为`opencode-go/deepseek-v4.1-flash`，role为max；不是鉴权缺失、身份漂移或总配额耗尽。真实job `mwjob_be7f1474e35f71ce2f097902`（8章批次）首答外层JSON未闭合且纠错空响应；`mwjob_3c36cdf12e46da237f93799d`（4章批次）在既定有界尝试后仍以`provider_response_empty`失败。两者均未生成工件、未采纳正文。

根因修复：空`message.content`此前因helper异常分支写反而跳过有界重试，现已纠正；v0.4批大小降至4并纳入descriptor；全文max推理的最终输出预算从32768升至65536并纳入descriptor，模型/provider/强度不变。集中验证112 passed、py_compile/diff check通过。证据：`runs/requirements_v2_20260919/t17_round11/STUDY_A_FULL_DRAFT_V04_PROVIDER_RECOVERY_20260922.md`。下一动作重启自有5299、再次身份探针、创建新logical work key并长轮询；不得重试两个旧失败job，不得采纳未经fresh医学会商的工件。

第三个job `mwjob_96ee70138c21a86568eb3f3d`使用4章/65536后成功持久化17批68章，第18批因两章引用未返回的`span_project_center`且同模型纠错未删除而失败。新增科学保守归一化：保留有效span并删除悬空span；章节若因此无有效证据，清空正文/决定并降为明确`source_gap`，绝不补造证据。集中验证113 passed。下一动作重启5299后重试同一job，复用前17个chunk从第18批继续；不得新建第四个logical job。

## 2026-09-22 v0.5 证据链持久化
采用 execution-plus-conference：owner 直接修复与当前全文初稿持久化紧耦合的确定性缺陷，冻结提交后做独立工程审阅；真实 v0.5 工件形成后另启 fresh 医学会商。v0.4 已证明生成时校验有效，但最终工件未保存 evidence span 到来源/定位/摘录的映射，不能作为可采纳候选。现将证据绑定按章节持久化，避免跨批次短 ID 冲突；chunk 恢复、最终合并和采纳均重新验证引用、来源与摘录哈希。schema 已升为 artifact v5/chunk v5/descriptor v6；v3/v4 保留只读。集中回归 115 passed，py_compile 通过。阶段记录：`runs/requirements_v2_20260919/t17_round11/STUDY_A_FULL_DRAFT_V05_EVIDENCE_PROVENANCE_20260922.md`。下一动作：冻结提交与独立审阅，然后在隔离 5299 生成 Study A v0.5，逐章核对证据链并进行 fresh 医学会商；此前不得采纳。
