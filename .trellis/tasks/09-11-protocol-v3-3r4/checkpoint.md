# Active 3R.4

## Goal恢复实施 — 2026-09-12
用户激活新版Goal，get_goal实测active；覆盖上一轮review-only暂停。前一Goal回合归类progress（完成review、文档与当前入口）。771源码文件与审阅后hash一致，HEAD84488d3不变。
当前3R.4A，先类型反例、最小实现，再canonical绑定与全部路径对账。方式execution-plus-conference：Codex持共享类型/接线写权，事实路径盘点适合独立只读工作；冻结实现后按需独立验证，不把规划审阅当产品验收。
允许Planv3范围内源码/功能测试；不启动live/产品模型/OCR/翻译，不动旧证据。

## 当前接手锚点 — 2026-09-12 Codex

本节为最新状态；下方英文是上次开始时记录，保留历史，不再作为当前派发范围。
产品仍user_paused，3R.4未验收。本轮已完成接回工程review与设计/Plan/Goal修订，没有实现产品修复。
用户已选择“优先完整可用路径，尽早看到成品，持续补齐范围”。
当前权威：plans/mw_protocol_v3_design_v1.4_20260912.md、plans/mw_protocol_v3_implementation_plan_v3_20260912.md及未被替代旧义务。
审阅：reviews/mw_protocol_v3_full_review_20260912.md；执行PRD：本目录prd.md；Goal：plans/mw_protocol_v3_goal_prompt_20260912.txt。
HEAD84488d307eae240cc48808dea506691091817354，多项preexisting dirty/untracked成果必须保留。当前源结构和all8assembly与原接受制品相同；1860v3/18frontend/1Node通过仅支持所测范围。
已确认待修：事实输入str/JsonValue断层；49条件未执行、14重复required及无期中矛盾；一致性图x/y桥接过度传播；纯hash不足业务采用证明；错误图执行边界；虚拟引用；API缺失对象误报409；旧UI过期Word与恢复定位。真实模型、UI和Word完整接线仍属后续V1。
恢复后先核对最新指令/当前树，从3R.4A类型反例开始，再B条件/C影响/D真实采用，接路径前置和V1，不重跑旧阶段。所有历史探针/下载/OCR/翻译/五失败项不重启。
两个worker与fresh设计review均终态；报告/原始日志保留。fallback回执标签矛盾与同模型独立性限制见owner review。无后台产品任务由本轮启动。

## 历史开始记录

3R.3 complete (all 111 carriers accepted, closure
reviews/mw_protocol_v3_3r3_batch8_acceptance_and_3r3_closure_20260912.md).
Global AGENTS hash re-checked at stage start: codex AGENTS e01f795d… matches
handoff 14.1 (no drift). 3R.4 prep doc read in full; three relationship kinds
must stay distinct (fact membership / scheduling / consistency-impact);
typed edge registry added at registry level; deterministic test list from prep
doc is binding. First execution worker: registry-level dependency graph module
+ tests. Files owned by worker: NEW module under
services/api/app/protocol_workflow/registries/ + NEW tests; core contract
files read-only.

### 3R.4A当前进展
有效typed red:13failed/4passed，修复输入/输出JsonValue与presence后52passed（17新增+35旧章合同）。先前诊断草稿漏Word样式，单独保留，不作为有效产品RED。
新增事实盘点worker运行句柄59353；task mw_protocol_v3_3r4a_fact_inventory_20260912，最长7200s，写权仅新run子目录。Codex继续canonical绑定/类型兼容，未关闭A。

canonical绑定及fresh-output事实对照已实现；新增724路径字面canonical key目录，全部有合同JSON定位。类型当前generic JSON（不猜临床类型/别名），旧字符串无明确类型时报具体未决路径，盘点worker仍进行中。当前33绑定测试通过。
扩大回归1889通过/1环境前提失败（漏TMPDIR→/tmp）；补齐本机TMPDIR后该项1通过，未改旧expected。证据intermediate_regression.xml、tmpdir_followup.log。完整A仍待显式类型/别名盘点与独立验收。

最新补充：fact inventory worker已终态成功（59353不再等待），owner核对报告hash及10条明确布尔rationale，纠正其“无类型证据”的过强结论。13摘要投影映射已声明；绑定新增条件/CtQ/一致性独有路径。空结构运输与正文充分性分离，有效3红→72 targeted通过。A未验收，继续catalog可维护性与独立复核。

A冻结复核包：runs/mw_protocol_v3_3r4a_20260912/frozen_review/source_hashes.json；conference mw_protocol_v3_3r4a_review_20260912，单一fresh reviewer，未增加manager。现37绑定测试通过；独立结果返回前不关闭A。

3R.4B前置准备（未进入验收）：49条件/14重叠已抽取到runs/mw_protocol_v3_3r4b_20260912/applicability_obligation_matrix.json，显式标not_adjudicated；三态谓词15个行为反例已写，当前模块尚未实现，predicate_red.log为预期红。A冻结review运行句柄82056，继续同句柄；A尚未关闭，不修改其冻结源码。

Owner新增实证：whitespace_fidelity_probe.json显示StudyDefinition、skill input、ContentFact均继承str_strip_whitespace，JSON文本首尾被改写（包括嵌套值）。需限定facts/value字段修复，不能全局关闭ID/说明字段规范化；历史已规范化数据不改写。A冻结审阅继续同句柄82056，当前尚未实施此新增修复。

### 2026-09-13 当前最新状态
A新增JSON逐字保真/NaN错误修复已实现；真实111合同synthetic canonical读取全成功。当前42绑定测试，122定向（此前41绑定时）通过；扩大A回归1902passed/1既有tar警告，98.33秒，review_verification_receipt.json记录命令/环境/输入前后hash一致，JUnit全用例。B15个红测试明确排除，仅前置反例，不宣称全项目全绿。
首轮fresh review实际CodeBuddy/deepseek-v4-flash（primary Pi目录预检失败后fallback），静态Read/Grep可用/Bash被拒，且读到盘点owner材料，独立性限制保留。对“canonical目标必须在章节词表”“字符串false被当空”的过强结论已实测驳回；接受nonfinite错误和真实合同测试不足，已修。确认事实修订/别名退役及准入类型校验已细化到D/V1，不通过读取时silent fallback丢掉事实。
复核round2正在运行，exec句柄44800，复用CodeBuddy会话01a09654-5faa-76e6-b4fa-899fff6d8396；旧82056、59209均终态不可再poll。冻结round2源见frozen_review_round2/source_hashes.json。A未关闭，下一步等待并判定复核，只修确切A缺陷后进入B实现。B矩阵含49/14及中央实验室、停药、多重性三个源文分离分析，尚未裁定全部，不是可执行规则。

等待A同会话复核期间，独立新模块applicability.py最小三态谓词已实现（不修改A冻结源，不关闭A/B、不提前改变49合同）：15红→15绿，predicate_green.log。all/any对未知值保持三态，布尔false不与0/字符串混同，canonical字面键与对象成员显式分开。现仍需将谓词声明/义务矩阵接入实际checker和ApplicabilitySnapshot，当前小模块不算B完成。

A已由Codex按限定机械范围验收，报告reviews/codex_conference_mw_protocol_v3_3r4a_review_20260912_review.md。当前3R.4B；45绑定+15predicate=60定向通过。44800终态，全部审阅/回归句柄均结束，不再等待。下一动作B实际checker/49规则三态/14重叠/源引用目标接线；不结束整个3R.4，不声称产品验收。

B采用execution-plus-conference：独立49条件来源/处置盘点有实际并行收益；worker只写condition_worker建议，Codex持全部规则/checker写权，冻结后独立复核。不增加manager。当前派发mw_protocol_v3_3r4b_condition_matrix_20260913。

B实际检查包装器evaluate_applicable_content已接到现有evaluate_chapter_content，状态只从confirmed StudyDefinition+显式predicate计算；适用检查facts/claims/source/object，未知返回具体未决；尚不释放旧无条件义务，等待源矩阵逐项改合同。3个实际checker反例红→18总用例绿。worker句柄66271仍在运行，写权仅condition_worker；不要重派。

B真实期中合同无期中用例已通过：显式false+不计划声明+项目来源可通过，不需11细节/表格。当前21应用条件测试通过。实现用source_rule+source_contract双hash绑定的显式义务投影，不自动删除所有重叠字段；共享条件任一true保留义务，所有false才对残留内容报冲突。仍待更多true/unknown/残留参数及真实binding接线；此规则声明目前仅测试构造，尚未作为全49配置发布。

B当前74定向通过（45绑定+29条件）。条件已进入真实bind_applicable_input/check_applicable_output，元数据绑定相关规则摘要；未知不进入写作输入，false残留参数生成前报冲突，空输出仍过不了正文检查。复用原ApplicabilitySnapshot：内层条件false不隐藏基础章节；只有显式whole-chapter规则可排除ECOG等附录。规则声明仍未完整发布，矩阵worker66271继续运行，未验收B。

2026-09-13来源裁定：B矩阵worker66271已终态，禁止再poll/重派。owner已核对原始模板body318–324/829–832及ICH E9(R1)正式版，纠正generic JSON不能布尔判定、未来用途false等于销毁、单终点等于无多重性、IRC替代组织必需等过强建议。详见runs/mw_protocol_v3_3r4b_20260912/owner_source_adjudication_20260913.md。当前30B+45A+35旧合同=110定向通过；49配置、B独立复核仍未完成，继续实施，不暂停。

B共享事实分支新增5例，条件模块35通过（shared_obligation_green.log）。引用修复后的全111载体assembly lint完整通过，无finding；仍保留医学QC未执行标签。盘点report hash/runtime身份已核对；audit-execution因生成prompt的Z Code名称未被解析成agent而失败，原prompt未改写，详情owner worker review。此元数据缺陷不作为停点，继续规则配置。

条件模块36通过：新增实际8.1无暂时暂停的输入绑定案例，仍必须提供永久停药与整体试验停止参数；删除永久停药记录时精确missing_required_fact。证据independent_stop_green.log。规则声明仍为测试构造，待发布配置，不冒充B完成。Plan顶部历史暂停措辞已校正为当前active授权，未修改历史run。worker review-gate已通过；audit-execution原失败与原因保留。无运行中句柄。

最新来源发现：11.4.6 PK/PD/E-R引用body783并非原文直接义务，实际来自3R.3 coverage reconciliation的declared semantic expansion。旧batch6 D2把“确证性使用需链接”错误扩大到所有适用分析。下一具体动作：纯探索性实际binding反例→按分析类型区分confirmatory用途→版本化规则/skill/catalog与定向回归，再继续49配置。详见owner_source_adjudication末节；没有需要用户选择的科学参数，仍active。

2026-09-13继续实施：上一Goal回合为progress（来源裁定、真实输入验证、Plan状态校正），不是等待/停滞。PK用途修复发现输入绑定尚未提升active conditional facts，现已前移必需校验。11.4.6/skill升3.4.0，新增PK/PD/ER各自confirmatory原生布尔，旧49规则扩展为52，原fixture及expected逐字相同。新applicability_rules.json已有8条产品可读声明、44条明确pending，非完整B。727绑定、全assembly lint complete无finding；92相关通过，发布配置后40条件通过，新增确证性有链接正例待当前回归。原red两个分别保留，PK_Purpose修复证据见pk_purpose_repair。

2026-09-13当前：PK用途/active输入必需提升后的全Protocol v3回归1946passed/1既有tar警告118.34s，pk_full_regression.xml与pk_purpose_repair/regression_receipt.json，受检4源hash前后一致。之后新增14.1/14.3/15三规则，9红→50条件绿；再接ECOG/NYHA两规则并修复条件来源只看role、不看所支持主张和上下文的实证漏洞（2红→125定向绿，scale_evidence_green.log；含52条件/45A/28batch8）。当前applicability_rules.json共13条声明、39条明确pending；历史49已因按PK/PD/ER用途拆分变为52，未冒称全量完成。新active_evidence_requirements复用原EvidenceSourceRequirement检查，没有新建来源准入平台；全B仍待配置完成及fresh review。
所有本轮测试句柄10756/48763/42815/81332等均已终态。下一动作继续39条来源条件裁定与配置，优先14.7计划/批准状态、期中目的与委员会独立性、多重性/随机盲法及中央实验室。维持3R.4B active，不关闭总任务，不启动live/产品模型/OCR/翻译。

最新2026-09-13：14.7章程状态计划/草拟/已批准已实际接入配置；新增FactPredicate.accepted_values，未知枚举不当false（5红→57条件绿）。章程3红→planned/draft可绑定、approved缺真实批准记录报具体missing_required_fact、apprvoed拼错为未决；已批准有记录保真正例追加。原14.7把IRC等同安全监督的措辞已修；skill保留试验参与者保护依据。合同/skill3.4.0，新状态事实string，fact catalog728；当前54规则中16已配置、38pending，原49谱系必须在最终矩阵交代（PK+3、章程+2）。
charter_repair保留合同/skill/batch8/catalog/测试before，原fixtures和expected未改。旧batch8“适用即要求批准”断言按用户授权升版为approved分支要求/draft不要求，依据assertion_upgrade.md。A全章节合成生成器新增string样本支持，不弱化保真断言。134相关passed（charter_drafting_followup_green.log）；新增精确批准回执用例4passed（charter_approved_receipt_green.log）。章程assembly lint complete无finding；随后skill补一句试验参与者，当前测试从当前文件组装通过，下一次最终全assembly须绑定最终skill文本。
无后台运行：10756全回归、各定向句柄均终态。仍3R.4B，不暂停、不关任务。下一具体工作：38pending规则中期中目的/IDMC/IRC拆分、多重性全假设族、中央实验室与本地职责，以及随机盲法、其他正文/前置条件；先对已有worker矩阵的来源裁定，不重复盘点全部。B完整配置冻结后fresh复核；然后C事实标签影响图、D实际SQLite，再完整Ⅱ/Ⅲ路径。未调用任何产品模型/服务/OCR/翻译。

2026-09-13中央实验室续作：上一Goal回合为progress。已直接核对原DOCX body570–575：body574要求中央实验室资质与承担项目，body572心电图集中判读独立。9.2旧条件仅重复单位/特殊检测目的且遗漏中央专属内容；已升合同/skill3.4.0，加入中央资质和项目范围两事实、显式布尔触发。保留本地/共同单位及特殊检测目的，无使用中央实验室时不索要专属资料，不推断心电图判读方式。真实binding反例1红/2绿→150相关通过（central_lab_green.log，含条件/A/batch5）。全assembly lint complete无finding；central_lab_repair保留before、原fixture/expected不变及来源裁定，最新assembly包含上轮skill最终文本。当前54规则：17已配置/37pending，fact catalog730。句柄51105终态，无后台任务。下一动作继续期中/多重性及其独立目的条件，不关3R.4B，不启动live或产品模型。

2026-09-13期中分支前置：上一回合为progress（中央实验室实际修复）。检查11.4.9发现仅解除条件事实仍会留下无条件表格单元格要求，导致纯安全审查也必须填疗效alpha/IRC单元格。现RulePredicate增加source-bound conditional_object_cells，复用现有义务投影，按单元格释放而保留整表/其他必要单元格；已不适用却残留非空单元格报inactive_conditional_cell_present。3红→67条件绿，追加残留单元格和原chapter合同回归，证据conditional_cells_followup_green.log。此能力尚未配置到实际期中拆分，17声明/37pending不变，不能称期中条件全修。
下一具体动作：11.4.9将共同要求与信息量比例/正式疗效检验alpha/IDMC/IRC分别绑定实际设计；需同步控制facts及对应table cells。优先复用irc.applicable；期中设计可用一个结构化features事实保留明确成员布尔，不另建章内存储。无期中保留不计划声明与依据；是否实施/用途未知先明示，不能默认false。现有interim_case测试helper需迁移到真实产品配置，不能继续只构造单一规则掩盖子规则缺失。B完成后才fresh review。所有本轮运行句柄42614/28857/7726均已终态，无产品/模型任务启动。

2026-09-13期中用途已实际配置：11.4.9/skill3.4.1，基准+信息量/疗效检验/IDMC/IRC四子规则，复用irc.applicable，结构化features不默认缺失成员。当前58规则22已声明/36pending。旧测试迁移完整catalog，原5失败原因是漏子规则或未知用途先于原目标错误；保留原expected，catalog_followup76passed。新增16种用途输出/表格组合均通过；发现相反不适用声明可混入有效正文（1红/16绿），已加入按声明owner判定的冲突检查，173相关通过（output_followup.log）。未修改旧fixture/expected。sample-size章节仍将期中或自适应一并要求alpha调整，下一步需依据原文及正式统计来源区分，并保留样本量影响说明，尚未修改该合同。B待36规则及fresh review；未关闭任务，无产品模型/服务调用。

期中修复扩大Protocol v3回归1990passed/1既有tar警告59.70秒；full_regression.log/xml及regression_receipt.json，运行中捕获的226源文件hash至结束无变化（不冒称开跑前捕获）。最终全111assembly lint complete/findings0。76335终态，不再poll。下一动作11.1期中/自适应样本量影响与错误率论证配置；全B仍未验收。

2026-09-13继续：上一Goal回合为progress（期中配置、相反声明缺陷修复、1990全回归），无阻塞。样本量11.1/skill已升3.4.0并配置真实条件：保留期中/自适应样本量影响与错误率论证，兼容interim_alpha_adjustment字段但取消必须为消耗调整数值的过强rationale；可运输含方法/依据的不需额外调整结论，医学有效性仍待真实证据/QC。3红→141相关通过；初次遗漏chapter_skill_version的lint失败保留并修复，lint_followup complete/findings0。未改原fixture/expected，before均在sample_size_condition。
IRC9.4按原合同已声明适用布尔及四类细节接入catalog，false不需虚构替代机构/章程，true缺项具体报错，unknown未决，false残留旧章程冲突；原决定主张、项目来源、不得等同安全委员会要求保留。当前24声明/34pending，58规则总数不变，731事实绑定保留旧aliases/types。最新定向证据irc_configuration/followup.log；总B未验收，下一步实际IRC输出来源/决定检查及未来用途等剩余34条，完整冻结后fresh review，再C/D和产品路径。未启动服务/产品模型/OCR翻译。

IRC最新140相关通过（followup.log）；追加真实输出仍需决定与来源的反例检查，4passed（output_check.log）。样本量/IRC的32429、26084、53082、67142均已终态，无后台运行。下一动作剩余34规则优先未来用途：不用于未来研究不能误释放当前方案所需保留/处置要求，不改写之前来源裁定。

2026-09-13未来用途续作：上一Goal回合为progress（样本量及IRC配置/回归），无阻塞。按既有来源裁定及12.7现行合同发布未来用途规则，false只解除六类未来专属事实、未来复核主张及表格，不解除current_study_assay_separation和separation主张/项目来源，也不增加销毁义务。真实输入3红→108相关通过；追加实际输出正例/来源缺失/一概销毁禁项/旧用途残留测试（output_check.log）。当前25声明33pending，共58规则，未改旧fixture/expected；before规则保留future_use_configuration。35781和79390均已终态。下一步继续33待配置条件，优先免疫原性、随机/设计与多重性，B全量冻结后fresh review；尚未进入C/D和成品路径验收。

2026-09-13免疫原性续作：上一Goal回合为progress（未来用途配置及正反输出检查）。9.3免疫原性条件按现行合同接入catalog：原生布尔，适用要求独立strategy事实和主张，不适用残留策略报冲突，未决不生成。3红→140相关通过（immunogenicity_configuration/check.log）；before规则保留，原fixture/expected未改。当前26声明/32pending，共58；55145、54454均终态。发现9.3仍把population_pk/exposure_response和共同采样方法无条件要求，3.4.1共享同样事实且存在analysis-commitment待规则，不能仅配置免疫原性就称整章完成。下一具体动作：完整读取3.4.1条件与原模板9.3来源，区分群体PK（不能以全部PK适用代替）、E-R与其他探索性研究，复用共享事实并先反例修条件，再其他32规则，最后B fresh review。尚无产品模型/服务调用。

最新来源裁定：上一Goal回合为progress（免疫原性配置及140通过）。本次完整读取3.4.1与9.3 skill并直接核对DOCX583–585，确认相同分析事实在目的章optional、检测章required，且3.4.1以文字内容作条件触发的根因。owner_source_adjudication末节记录跨章具体修复合同；下一动作原生群体PK/生物标志物适用性、复用已有E-R/免疫原性状态，真实双合同反例后修改。不能从非空文字猜适用，不能把PK总体等同群体PK。26声明32pending未变，此轮尚未修改产品合同；无后台句柄，无需用户决定，继续实施。

2026-09-13探索性目的实际修复：上一回合为来源裁定progress。本轮3.4.1/skill3.4.0，将文字内容触发改为四种明确布尔状态；新增群体PK/biomarker布尔，复用statistics.pk_pd_er.er_applicable与exploratory.immunogenicity_applicable，基础any承诺规则加四类细节子规则。全false不索要分析细节，单独群体PK true精确要求其详情，其他类型未知仍未决。原始反例红→183相关通过，lint complete/findings0；before合同/skill/catalog/batch2保留exploratory_crosschapter，旧fixture/expected未改。现31声明31pending（62规则），733事实绑定保留旧类型/aliases。61962终态，无后台。下一动作9.3使用相同四类状态及一般PK/PD独立状态控制共同采样和方法，避免把一般PK误等同群体PK；再完成剩余规则、Bfresh review、C/D和完整成品路径。

2026-09-13检测章节同步：上一Goal回合为progress（3.4.1明确适用性/183通过）。9.3合同/skill3.4.0，新增共享PK/PD/E-R any条件、群体PK与E-R各自细节条件；复用3.4.1群体PKflag与11.4.6一般PK/PD/E-R flags。全false不再强制五类细节；一般PK、PD各自true仍需共同方法、终点、采样，不能因PopPK false错误豁免。5红→定向结果见assessment_check.log；原immune测试补齐新增已适用前提，未改其expected。无相关PK/PD/E-R时仍需项目来源支持的处置主张；待实际输出组合加验。before与lint complete/0保留exploratory_crosschapter/assessment_*。34声明31pending共65规则，733绑定。93539与9084终态。继续输出验证和其余31条件，尚未B fresh验收，不启动产品服务/模型。

2026-09-13输出续验：上一回合为progress（9.3跨章修复229通过）。新增无PK但独立免疫原性两实际输出案例，发现只有不开展PK处置来源也能支持免疫原性策略的漏洞；保留assessment_output_check与immune_source_red，配置active_evidence_requirements要求project_primary明确支持immunogenicity_strategy并有context/locator/quality。修后107条件测试通过（immune_source_check.log），既保留只做免疫原性正例，也验证删除其专属来源或主张不通过。19518终态，34声明31pending不变。继续其余31条件及最终B fresh复核；不冒称完整产品或医学验收。

2026-09-13纳排重复条件退役：上一Goal回合为progress（免疫原性专属来源补齐）。5.1/5.2仅重复已有required主张的active开关退役；all-applicable/any-applicable逻辑仍在原project_specific_elements，参数/单位/窗口/例外与妊娠风险独立条件保留，contract3.4.0。按用户授权旧batch3断言升版，新增required主张断言，原fixture/expected不变，详见eligibility_condition_retirement/assertion_upgrade.md及retired_rules.json。初始red因空confirmed study前提无效，未冒称有效产品红；补合法anchor后保留旧合同重现conditional_predicate_missing，证据valid_old_contract_comparison.json明确事后比较。当前173相关通过，lint complete/0。34声明29pending共63现行规则（2条退休谱系保留），733绑定。21982/70082均终态；继续29规则、Bfresh复核、C/D及成品路径，当前无需要用户决策。

2026-09-13复筛配置：上一回合为progress（纳排重复开关退役及173通过）。直接核对DOCX410–414，5.4/skill3.4.0使用新增population.rescreening.allowed原生布尔替代screen_failure.definition文字触发。false只释放四类复筛详情及三个复筛表格cell，不释放筛选失败记录、是否允许复筛主张及其来源；true精确补四类，unknown未决。3有效红→定向结果见rescreening_configuration/check.log，lint complete/0；before保留，原fixture/expected未改。35声明28pending共63规则，734绑定。10393终态，无后台。下一步复筛实际输出表格验证及其余28条件，然后Bfresh、C/D、完整Ⅱ/Ⅲ成品路径；未请求用户阶段确认。

复筛跟进：首轮175passed/1失败，原因新增布尔rationale缺旧batch3要求的结构化标识，已准确补明“结构化原生布尔状态”并同步hash/binding，无测试expected改动。followup.log为最终定向结果，67633终态。

2026-09-13扩大验证：上一回合为progress（复筛修复176通过）。新增实际5.4输出true/false两例通过：禁止复筛只删除复筛cells，筛选失败表与是否允许复筛的来源仍必需。近期共享合同变更扩大Protocol v3回归2018passed/1既有tar警告66.98秒；rescreening_configuration/full_regression.log/xml，regression_inflight_hashes.json运行中捕获至结束无变化（非开跑前捕获）。23536终态，无后台句柄。剩余28规则重新按当前合同读出；图目录front8由正文题注清单决定has_figures，不应用户手填，其当前规则仍pending；生成/导出producer实际计算需V1/7R接线，不能仅从用户bool称图目录完成。下一动作图目录/流程图适用性发布与真实数据来源边界，其他设计条件及Bfresh review继续。35声明28pending不变，总目标仍active。

2026-09-13图目录输入条件：上一回合为progress（复筛输出与2018全回归）。front8按原合同发布figures-present，false残留非空题注清单报冲突，true缺清单具体missing_required_fact，unknown未决；3红后定向check.log。36声明27pending共63。图列表身份/编号/文档版本仍须V1/7R真实producer核对，当前输入测试不冒称自动生成或Word验收；原图索引/无图处置主张及来源要求未移除，原fixtures/expected未改。51963/92016终态，无后台。继续流程图、其他真实设计分支和最终Bfresh复核。

2026-09-13流程图条件：上一回合为progress（front8图目录输入条件133通过）。1.2按既有双条件发布randomized/escalation，5真实组合反例红→定向结果diagram_configuration/check.log；非随机/无升级不强制分配比或升级路径，单独true只需其细节，未知不生成。原合同/fixture/expected未改，before规则保留。38声明25pending共63。现diagram.*仍直接canonical key，必须在D/V1落实由已确认设计投影并退役同义可编辑字段；不因本轮输入通过就称与设计数据端到端一致。13885终态，无后台，继续其他设计条件与B最终fresh review。

2026-09-13SOA PK条件：上一回合为progress（流程图双条件/138通过）。1.3按原source-bound规则发布PK采血条件，只释放pk_timing_units，不释放访视、评估、脚注、早退、安全随访或联系访视事实。3真实红→定向check.log；true单位/参考事件结构化对象运输保真，false仍缺安全随访则精确missing_required_fact，unknown未决。数值单位充分性、真正SOA单元格/Word渲染未由此输入测试替代，仍是V1/7R实际验收。39声明24pending共63；原fixture/expected未改，before规则保留。19442终态，无后台。继续24项（设计/干预/前置签署等）及B最终fresh review，保持成品路径目标。

2026-09-13前置页三条件：上一回合为progress（SOA PK/141通过）。按front1/3/4原合同发布修订、额外签署、服务方适用性，9组合输入红→check.log；false保留版本/申办方/研究者基础事实，拒绝残留额外元数据；true具体要求对应详情，unknown未决。front1同步控制change_rationale cell，不能只释放事实却强填无修订的变更依据。签署/服务方真实页面数量及实际签署控件仍由V1/7R验收，此配置不伪称完成。42声明21pending共63，原fixture/expected未改，before保留frontmatter_configuration。58138终态，无后台。继续余21真实设计/干预条件、Bfresh复核、C/D成品路径。

2026-09-13背景治疗条件：上一回合为progress（前置页三条件150通过）。6.4.2按原条件接入，false只释放必须使用的背景治疗规则，true精确要求，unknown未决；其他允许清单与时间要求独立不释放。3红→check.log，原fixture/expected不变，before保留background_therapy_configuration。43声明20pending共63。34141终态。同步发现6.1.2 dose-modification把暂停/降低/恢复/永久停药绑定单开关，escalation以自身文字触发自身；不能直接机械发布。下一具体动作核对源与8.1既有独立停药设计，保留永久停药，按明确剂量动作/递增状态拆分，避免无减量路径时强填减量幅度，且不从字符串推断bool。之后其他条件、Bfresh、C/D与成品路径继续。

2026-09-13剂量动作修复：上一回合为progress（背景治疗165通过）。直接核对DOCX427–432及8.1独立永久停药规则。6.1.2/skill3.4.0，master仅要求明确features（hold/reduction/restart原生bool），三子规则各自控制对应事实；永久停药始终required、不受关闭master豁免。新增独立escalation_or_dlt_applicable，不用自身说明文字触发自身。3实际红→首轮212pass/1旧阶段断言失败，按用户授权升版为独立hold条件，原其他断言/fixture/expected不变，详情dose_actions_configuration/assertion_upgrade.md；最终followup.log。lint complete/0，before保留。现48声明18pending共66规则，736事实绑定。65510/90493终态。下一动作补剂量各动作组合输出及unknown成员/递增正例，核对8.1暂停事实与features的单一来源关系在D/V1实现，继续其余18条件，Bfresh review仍必需未派发。无服务/产品模型调用。

2026-09-13续验：上一回合为progress（剂量动作213通过）。16种hold/reduction/restart/escalation实际输出组合通过，去掉永久停药事实均失败，证据dose_actions_configuration/output_combinations.log。10.1.1按明确裸bool原规则发布肿瘤进展例外条件，3红→oncology_exception_configuration/check.log；true需项目例外范围，false不需，AE定义/TEAE派生基础内容不释放。不对实际项目例外适用性作医学裁决，不将该机械配置视为来源/临床审批。注射反应适用性原文需是否+理由，当前generic JSON不能当bool，下一动作明确结构化决定（applicable与理由）或审定类型后接线，不能根据非空文字猜。49声明17pending共66，736绑定。16938终态，无后台。继续剩余条件和Bfresh复核，尚未完整产品验收。

2026-09-13注射反应结构化决定：沿用execution-plus-conference，owner修共享读取与配置，B完整冻结后仍需fresh独立复核。3.3.1原合同要求是否适用与理由，FactBinding增加仅object可用的required_members布尔/非空文本声明；原生false与短理由保真，0/字符串false/缺理由不冒充决定，兼容其余无成员约束绑定。6红后51绑定通过；真实注射条件3红后250相关通过（injection_decision_configuration/followup.log）。全111合成地址测试补足新声明成员输入，未改变原断言或负向fixture。首次配置脚本误用strict model_validate(dict)失败且写入前停止，改model_validate_json后验证发布；input_check/input_followup失败证据保留。当前50声明16pending/66规则，736绑定。扩大回归句柄78078进行中，日志同目录full_regression；不可重复派发。下一步核对7.2 randomized_on_day1与一般随机设计的区别，不能把非D1随机误免除随机化时点；11.4.8无调整状态也不能免除完整家族依据。待B完后fresh/C/D及完整产品路径，尚无产品模型或服务启动。

注射决定扩大回归2072passed/1既有warning，49.33秒；full_regression.log/xml与regression_receipt.json，hash为终态后捕获如实标注。78078已终态，无后台句柄。50声明16pending，3R.4B仍未最终验收；下一动作7.2源时点语义核对/剩余条件，后续Bfresh、C/D与完整Ⅱ/Ⅲ路径。

2026-09-13随机化及盲法续作progress：直接核对DOCX488–489，7.2/skill3.4.0由D1触发改复用diagram.randomized，不在D1随机仍需时点。4红后245相关通过，2实际输出通过。首轮五失败（旧断言/局部词汇/状态运输）全部保留并修复，assertion_upgrade.md有完整更正，不改负向fixture/expected。继而核对363–369，4.5/skill3.4.0替代泛文字开关为随机、设盲、紧急揭盲、非盲人员四条件；新增masking_features对象，部分设盲不默认紧急揭盲，开放设计保留masking_procedure偏倚控制、分配角色与来源。5红→243相关通过，16实际输出组合通过且删除偏倚主张/来源均失败。新features义务与现有条件trigger一致由执行层未知阻断；初版无条件required破坏旧基础结构fixture，现显式说明结构检查不替代条件输入，原负向fixtures/expected不变，失败保留。lint complete/0；证据treatment_randomization_configuration与masking_configuration。当前55声明14pending共69规则、737事实绑定；无后台句柄。下一动作补救治疗/estimand等14条件，Bfreeze后fresh复核，再C/D完整产品路径；diagram.* canonical归并与features实际AI设计投影仍须D/V1完成，未冒称第二事实源已消除。

2026-09-13继续跨章条件：直接读取源310–325，3.1.2.3/skill3.4.0用背景/补救两已确认布尔any替代背景文字触发，保持治疗条件/背景处置基础事实；任一适用须处理与cross-contract claim，增加其专属project_primary来源定位/context/0.9。4红→定向check.log通过，4实际输出组合通过且删除专属来源失败；证据estimand_treatment_configuration。3.1.1停药/补救合并示例以及3.1.2.4 ICE交叉核对仍待处理，不能因无补救免除其他ICE策略。
随后核对354–355，4.2/skill3.4.0以两独立布尔替换泛开关，明确非劣效假设/安慰剂对照才分别要求决定，基础对照/假设理由不释放；非劣效实际输出还需项目界值来源context/locator/0.93。5红→design_rationale_configuration/check.log，4实际输出最终output_followup通过（初次测试错误使用ContentClaim不存在字段，原错误证据保留，修为statement而非产品问题）。旧泛规则保留superseded_rules。2新bool路径必须由D/V1已确认设计投影，不能新增用户必填；qualified claim的实际医学论证/八类人审仍待真正流程，不由字符串或synthetic来源证明。当前58声明12pending共70规则、739绑定；所有工具句柄终态，无后台产品模型/服务。全量最新2072回归为本轮四章变更前；本轮全111lint complete/0与相应批次定向检查，不冒称新全量运行。下一动作12pending（主要目的rescue、ICEcrosscheck、探索终点、4.1/4.3/4.4、5.2/5.3/5.5、6.2.2、7.3、11.4.8），完成B冻结fresh独立review，随后C/D/V1。另4.2当前强制competitor_full_protocol作为design_rationale证据是否造成无竞品全文项目阻塞，需D来源准入审阅按Plan实际允许来源，不冒称已修。

2026-09-13ICE与补偿progress：3.1.2.4/skill3.4.0将群体汇总文字触发改复用背景/补救明确状态any，只控制专属crosscheck及其项目来源；无补救不能免除其他ICE策略/理由。4红→ice_crosscheck_configuration/check.log通过，lint complete/0。源310–325已直接核对。5.5/skill3.4.0依据415–418将重复招募/保留开关替换已有补偿bool，新增compensation_arrangement详情，适用需项目安排与既有规范来源，不适用仅释放补偿，伦理计划/招募/保留不释放、不虚构已批准或已兑付。3红→recruitment_compensation_configuration/check.log通过，2实际输出组合通过且删除项目来源失败。当前60声明10pending共70规则、740绑定。全量回归句柄62303运行中，同compensation目录full_regression；不可重派。
下一7.3来源发现：直接读491–493，492要求“如发生计划外访视（含电话随访），应记录日期、方式、内容、原因”，是方案中的未来记录规则，不是让作者在写方案时提供已发生访视日期。当前conditionalrequired四contact_visit字段及“是否存在”触发混淆计划与执行记录；不得机械发布bool后称修好。下一动作优先将记录规则绑定已确认方案事实，保留实际随访窗口/安全报告，旧字段历史运输另保留；不得要求用户猜未来日期。尚未改7.3合同。之后剩余条件、Bfreeze fresh、C/D/V1，仍无产品模型/服务启动。

ICE/补偿扩大回归2125passed/1既有warning，51.87秒，full_regression.log/xml；62303已终态，无后台任务。Plan v3将原49规则盘点数明确为历史基线，验收按当前完整合同/拆分谱系；design v1.4及Plan追加方案计划与执行记录区分、7.3反例及D/V1不得把新增条件字段变为用户手填表。此轮尚未修7.3源合同，下一动作从该反例开始，不重复全回归、不重跑模型。60声明10pending，Bfresh尚未派发。

2026-09-13随访方案事实已修：上一回合progress（ICE/补偿/2125回归及计划语义细化）。7.3/skill3.4.0退役如已发生访视才索要实际记录的条件；改为始终必需unscheduled_contact_recording_plan对象，date/modality/reason/assessment/safety_information五类非空规则，原日期/方式/原因/评估历史路径保留catalog但canonical_path=null不再当方案输入，不改StudyDefinition。1红→followup_recording_plan/followup.log295相关通过；真实bound输出反例证明不能以日期替代计划。原4字段仅7.3消费已核对，无跨章读者丢失；绑定registration如实列4unsupported，旧“零unsupported”阶段断言精确升版为这4项。原batch4正向输入增加计划且全部负向fixtures/expected经fixture_preservation.json比较不变，before原版保留，未弱化新必需计划以迎合旧正例。
11.4.8按原规则明确布尔no_adjustment状态但不释放任何基础家族/程序/依据义务，3红→multiplicity_configuration/check.log。源802–803只是示例，不从单主要终点数量断言无需调整；实际统计合理性仍须来源/人审。当前61声明8pending共69现行规则、741绑定（4历史方案读取已退役）。全量回归33427运行中，followup_recording_plan/full_regression.log/xml，pre_regression_hashes.json为真实开跑前快照，期间不修改产品/测试。下一步待该句柄终态后核对hash，剩余8条件与Bfresh、C/D/V1；无服务或产品模型启动。

随访/多重性扩大回归2130passed/1既有warning53.57秒；pre-run快照全部文件至终态未变，regression_receipt.json记录覆盖范围。33427已终态，无后台任务。61声明8pending不变，下一动作其余8（3.1.1救援示例/3.4.2探索非确证/5.2避孕/6.2.2标签/4.1总体设计/4.3剂量/4.4完成随访/5.3生活方式），完成B后fresh独立复核仍未派发；不把绿回归当完整产品验收。

2026-09-13探索/标签/避孕progress：3.4.2/skill3.4.0把探索解释范围及项目来源改required，退役文字开关，FDA2022 III.A印刷6–7已在线核对，方法学源见exploratory_interpretation/source_adjudication.md。不把描述支持一概禁止，也不靠探索结果直接宣称确证。反例→309相关通过+真实bound输出来源反例；旧来源组计数精确增至3，全部负向fixture/expected实际比较不变。6.2.2原bool规则接入，false不索要附加label_text，保留包装/核查主张来源；3红→labeling_configuration/check.log。
5.2/5.3/skill3.4.1使用共享risk对象applicable/reason，控制避孕引用/期限和对应cell，保留其他资格/生活方式事实；6红→301相关通过，4实际输出组合通过。纳排共享字段断言按用户授权只增同一个风险决定，不合并纳排谓词；证据contraception_configuration。当前64声明4pending共68现行规则、741绑定（4历史contact字段不供方案读取）。全量2130为本轮前三处改动前，本轮各对应批次与全111lint验证，不冒称又跑全量。无后台句柄或产品模型/服务。下一动作剩余3.1.1 rescue、4.1总体设计、4.3剂量依据、4.4研究结束/随访，完整B冻结后fresh独立review必需，随后C/D/V1。

2026-09-13研究结束细化：直接核对源359–362，4.4/skill3.4.0将随访与治疗后评估分为独立features布尔（picos.study_epochs.features），控制各自事实/主张/来源/cell；参与者完成、整体结束及结束触发始终required，不能用本章false取消其他章节实际安全随访或报告义务。5红→study_end_configuration/check.log通过，4实际输出组合通过，删除整体结束主张或参与者完成来源失败。before及superseded规则保留；原负向fixtures/expected不变。当前66声明3pending共69规则、742绑定；剩余3.1.1主要目的合并停药/补救示例、4.1总体设计的可选特征、4.3剂量依据。全B仍未验收，fresh未派发，无后台进程或产品模型。下一步三个剩余条件必须基于真实源义务处理；源357明确计划最大给药量与起始剂量依据，旧4.3只把maximum_dose标optional且泛开关只重复claim，不能机械退役后漏该义务。4.1的351–353明确期中/分层/子研究按实际适用性，需复用已确认设计与已配置期中状态；不能新造独立用户手填表。

2026-09-13冻结重新锚定：完成4.3计划最大剂量必需、4.1期中/分层/子研究独立条件与3.1.1补救补充义务纠偏，证据各configuration目录。当前70声明/0pending；这只是可执行覆盖，不是医学或产品验收。fresh_review_20260913冻结311项开跑前文件+4项运行中补捕核心合同，扩大回归2177passed/1既有warning51.99s，当前315项hash全部一致，见regression_receipt.json。独立review已实际派发，runner PID24406本轮核实存活，reviewer_scratch已有读取产物；logical key mw_protocol_v3_3r4b_fresh_review_20260913_candidate1，禁止因未见最终receipt重派。声明C03 ZCode/GLM-5.3/max，effective身份待最终receipt，不冒称已核验。全局guard因无关C01.peak字符串格式在导入时报错；未改全局，使用同一权威manifest完整C03链及既有runner，未声称guard audit通过。模式execution-plus-conference不变。审阅期间不改冻结产品/测试，owner先只读核对C依赖标签传播与D实际采用接口；结果回来后整合反例，修订制品须重验。尚未启动产品模型/服务，B/C/D/V1未验收。

C/D只读预检：owner_c_reconnaissance.json实际调用当前graph复现A{x}、B{x,y}、C{y}只变x误包含C；未改冻结源码。根因dependency_graph.impact的neighbours丢弃shared_fact_paths，随后无标签BFS。旧test_dependency_graph._reference_closure也复制相同算法，且REAL_REGISTRY_PATH固定3R.3历史产物；C应保留历史结构fixture但以当前组装注册表/独立期望集合验收新行为。先记录事实标签直接使用与候选调度，未知条件仅候选，输出实际重新确认集合和via_paths；不让一致性关系隐式制造y变化。D接线可复用application.service.apply_decision同一UoW/current/ledger/CAS/atomic协调；StudyDefinitionReducer已在精确重放时返回current不回退，应保留。当前服务未接dependency_graph（全目录搜索仅图模块），AggregateNotFound仍落入可重试CAS分类，D须实际API反例修复。此为预检，不提前宣称C/D完成；B独立审阅继续运行。

B owner冻结旁路检查：owner_invalid_cell_catalog/result以副本替换已声明单元格为不存在ID，load_applicability_rules仍接受，确认为配置目标校验缺口，尚未修复。当前70规则真实cell目标无缺失；全投影静态扫描3个table候选经原条件required_when_active_structural_objects复核均合法，见owner_projection_target_adjudication，不得误删或限制只能引用基础objects。后续修复加载校验须涵盖基础+条件源义务；此为科学/功能配置正确性，不是新增安全专项。保持B冻结至独立review返回后整合。

已准备但未应用owner_cell_validation_candidate.patch；隔离namespace执行候选load函数，70真实规则仍接受，不存在cell反例被拒绝，证据owner_cell_validation_candidate_check.json。产品源未改，不能把候选测试称已修复。Breview原runner仍处于hard wait，以kqueue进程退出事件有界等待，不发送模型状态询问或重派。前端只读复核：protocol-workbench目前仅protocolWorkspaceApi.mjs，无App消费命中；旧工作台/导出实现保留，V1按计划接真实页面与Word，不把client文件当成完整前端。

C实现准备约束（尚未落代码）：图已有所有fact→carrier直接索引，给一致性边保留原changed facts标签后，同事实共享章节本来就在direct集合，不能再从B的另一事实y制造新变化。真正调度依赖保留完整候选下游；候选重算与实际人审重开分开。派生值只在确定性派生实际改变且进入canonical变化集合时传播，不从chapter连通性推断。D先用affected_chapter_fact_paths转换已有canonical别名，再使用当前合同/适用性版本；不得把带点字面键擅自拆成嵌套地址。未知条件保留待决候选，来源错配/未知依赖图仅诊断不可执行；无效图旧可视化证据保留。impact_sha256继续用于投影比对，业务一次采用仍用现有revision+decision ledger。无需新事实库/新编排平台。

2026-09-13 B范围owner验收完成并转C，详见reviews/codex_mw_protocol_v3_3r4b_acceptance_20260913.md。C03实际GLM-5.3/max身份核实，sess_e3599511-8964-4589-b7bf-c2c90ac2e0d2已终态不重派，87188退出事件watcher已终态。原review报告.json为Markdown、stdout.log为JSON，不能按扩展猜格式。矩阵保存新adjudicated版本不改原历史，40保留ID+30新-9退役=70现行；14重叠逐项保留/条件化明确。补cell目标校验11行及一个功能负例，318相关通过，2178全回归/1既有warning52.75s，9021已终态，hash均一致。P3-5死代码意见用实际presence+innerunknown反例驳回；其余P3移交D/V1/3R.5A，不冒当前产品完成。下一动作C桥接反例正式加入并最小修复传播，读取相关完整定义/测试；不再阶段性停下。

C分工：execution-plus-conference模式继续。C图/对应测试有独立修改范围，交E04有界执行以释放owner审查D集成上下文；owner不重复写其文件。E03 peak malformed，E04同当前主模型且完整源链可执行，globalguard仍导入失败，按当前批准runner原链执行不改global、不伪称guard audit通过。合同/逻辑key及before快照见runs/execution/mw_protocol_v3_3r4c_fact_impact_20260913，目前仅prepared，必须真正派发并核实。

C worker runner已启动：统一exec句柄29852，E04 GLM-5.3-Flash/max声明，effective身份等待runtime_receipt.json，不冒称已证实。report.md/runner.log在本Crun。不要重派；owner期间只读D相邻API分类与采用链，避免与worker同时改变全量回归输入。

D只读实证：runs/mw_protocol_v3_3r4d_preflight_20260913/missing_study_response.json通过挂载真实router+隔离SQLite，已准入项目中不存在study POST决策返回409/can_retry=true及“推荐更新请重新确认”，期望404未找到；保留repro数据库，不是源码推测。未启动监听服务或产品模型。修复入口service._translate把AggregateNotFound列CAS族、MissingRepository也错列可重试CAS；router._status_for按code返回409。后续D须稳定区分404/真409/不可用户重试配置故障，并保留精确历史回放返回当前后继版本逻辑。owner尚未改这些源文件，Cworker29852拥有图/其测试。

D新增实际可达接线缺口：decision_graph_response.json中创建+采用均200，revision2、事件2、两条decision已记录，但decision-graph GET200/records=[]。现有mounted integration仅断言图HTTP200，漏实质内容；全源码replace_decision_graph仅storage实现，无业务调用。D应同事务或无写只读派生提供真实当前决策投影，历史ledger保留，不把历史confirmed当当前确认。此证据不修改任何产品源，数据库留在3r4d_preflight/decision_graph。

D第二实际缺口：confirmed_revision_response.json中confirmed revision1，新的decision/key+正确当前snapshot，修改已有dose仍409，revision保留1。_merge_facts对所有confirmed/frozen已有值变化都阻止，现有常用集成仅加NEW_FACT age而未改已确认dose。D必须显式版本化事实修订入口/采用语义与现有CAS/ledger同事务，保留旧禁止静默覆盖负例，不能一把去掉保护。当前DecisionRecord无已确认输入fact read-set；决策图投影也没有业务写者。因此当前有效性不能只凭历史canonical_state或整体revision判定，需要新决策的准确事实绑定/当前只读投影；遗留无绑定不能伪装当前批准。此为D接线细化，尚未改源或宣称已修；源/HTTP证据均在3r4d_preflight。

Plan/design已针对D实际反例细化：显式已确认事实修订、准确事实read-set/当前决策投影、真实同key回放后继版本保持、404/409/配置错误分别处理；design两处旧“产品暂停”当前措辞按已激活Goal校正，历史Bfreeze副本不变。C代码/测试范围与要求未变，owner未修改worker允许的源文件。任务状态仍仅Trellis，nativeGoal未被缩减或标完成。

Goal prompt生成增量版本plans/mw_protocol_v3_goal_prompt_20260913.txt，保留原20260912文本，追加已确认事实显式修订/真实当前决策视图/准确输入绑定/错误分类用户结果。所有原有全局AGENTS重读、超长事件等待、完整路径/20-5/医学与Word范围原文保留。原生Goal仍active且未改写objective（当前工具无活动objective改写能力）；新Plan细化已在现有Goal授权下执行，无需用户为了继续施工先手改Goal。

D接口设计待C返回后落地的约束：新决策的事实依赖绑定应按采用后的已确认值/未变上游输入记录，否则用采用前被修改字段hash会使刚确认的决定立刻过期。优先复用现有event payload/只读投影，不修改旧DecisionRecord序列化导致历史material_sha漂移；新类型/请求语义需要显式版本化。legacy无输入绑定应current_validity未证实，不改写其历史canonical_state。显式事实修订还需支持旧alias退役的删除语义，与JsonValue null区分；仅保留旧值在历史revision/events，不静默清理现行冲突或把null当删除。精确read-set比整体revision更细，也必须含未被本次决策写入的上游依赖，不能仅用fact_updates当输入依赖全集。以上是实现约束，API字段/方法签名尚未定稿，先对接C真实结果，不新造事实存储。

D/V1文档接线边界：canonical/document.py已有FactProposal及fact_or_uncertain编辑分支，可接新事实修订，无需新编辑器或第二事实库。SemanticDocumentRevision绑定整体study/applicability hash；研究事实改变后不能只换文档source hash却继续把旧相关正文称当前有效。保留未变内容，按实际影响标记待同步/形成候选，完整采用后再成为可导出版本。已确认设计修订与V2正式方案修订工作流区分，不能顺手开放冻结定稿任意覆盖；旧历史document/fact绑定与replay证据保持。


### 2026-09-13 — D 错误分类独立修复

Owner 在 C worker session 29852 仍运行期间，仅修改 disjoint errors.py、application/service.py、api/router.py 与相关测试。真实接口缺失方案从错误的 409 重确认改为 404 不重试；缺失 repository 从 DECISION-CAS 改为 SERVICE-CONFIGURATION_INCOMPLETE，不要求用户重新确认医学推荐。既有其他项目找不到对象测试仅升版错误码断言，前后状态不变断言完整保留；真正 CAS/冻结事实覆盖断言未改。新增两项测试先得到真实行为红灯，修复后连同错误目录、application service、mounted API 共 62 passed (5.74s)。证据：runs/mw_protocol_v3_3r4d_preflight_20260913/error_classification_red.log、error_classification_check.log；修改前源码在 error_before/。未启动产品模型/监听服务，未改 C worker 文件。D 事实升版与实际 decision projection 尚未实现，3R.4 未关闭。


### 2026-09-13 — D 决策查询不再空成功

真实 HTTP 新增测试先复现：创建并采纳决策后 GET decision-graph 返回空 records。现查询从既有已提交事件重建每个 decision_key 的最近采纳记录，不新增投影数据库、不写历史事件；旧记录缺少输入 read-set，明确 current_validity=unverified，不把历史 confirmed 伪装为当前仍有效。GET 前后完整 SQLite iterdump 不变。相关 63 passed (5.65s)，证据 decision_projection_red.log / decision_projection_check.log。旧查询测试从与空缓存相等升版为验证真实记录及未核实状态；原只读无副作用测试保留。当前 validity 类型/新事实绑定及事实修订尚待 D 后续完成，不能据此接受 D。C session29852 仍运行，未重派。


### D 查询相邻消费者核对

首次全量 projection_regression.log 为 35 failed / 2162 passed，不能声称全绿：30 项受查询在建项前错误要求 aggregate 存在影响，已恢复预设 read-model 节点并以真实事件覆盖同 key，保留建项前空查询行为；4 项来自 C worker 正在写入的 test_fact_labeled_impact.py，中途状态不验收、不修改；1 项因 owner clean env 漏 TMPDIR 导致 /tmp 而非 Darwin /var，后续命令恢复 TMPDIR。针对 API/Agent5/application/新增实际投影的 118 项现通过 (1.22s)，projection_consumers_check.log。尚未对 C 固定输出做联合全量验证。当前 read-model 仅保留预设节点，实际已采纳权威来自事件；旧 confirmed 仍独立于 current_validity=unverified。


### D 错误传播修复 / 当前固定子集

回归暴露 Python contextlib 恢复 __traceback__ 被 ProtocolWorkflowError 全属性冻结阻止，掩盖真实工作流错误。新增正常事务退出反例（context_cleanup_red.log）后，仅允许 Python 异常自身 bookkeeping 属性，业务 payload 的既有不可变测试不变。当前错误目录+application+真实投影+API+Agent5 共144 passed (1.50s)，error_projection_final_targeted.log；owner_error_projection_source_hashes.json 绑定当前9个源/测试文件。再次核对全局AGENTS和原生Goal：active，继续执行，原生objective未改；新prompt文本已单独保存。C健康运行仍等待，D整体未验收。


### 2026-09-13 — C 首轮终态与 owner 反例回修 / D 事实升版进行中

C 原统一句柄29852已exit0；session sess_f7fa1d2f-dc43-49d6-9b90-f0758deed6d9，2553.682s，实际GLM-5.3-Flash/max request/response/observed effort匹配，无fallback，3个文件hash与report一致。首轮2198pass不作为当前联合验收，其所谓context cleanup偶发实际为owner并行红测修复跨时点读取，已明确纠正。C未接受：owner脚本 c_owner_cases.py/json 证明①基础required但被B conditional_fact_paths控制且unknown，误confirmed_reopen；②共享when_active owner一真一unknown，误candidate，违背active owner wins。最初probe缺source_contract_sha的setup错误已补，当前结果是行为证据。

同会话定向续作已实际派发，logical key mw_protocol_v3_3r4c_fact_impact_20260913_v1:owner_followup_01，统一句柄29505，原session，E04完整原manifest hash未漂移；本轮4500s/64内部轮，已用总时2553s从7200s预算扣除。仅改C原3文件与其run，owner继续D disjoint。新报告/receipt在 runs/execution/mw_protocol_v3_3r4c_fact_impact_20260913/owner_followup_01/，禁止重派慢运行。要求本轮只跑定向，联合全量由owner源码冻结后执行。

D当前新显式路径：ApplyStudyDecisionCommand/API新增严格bool revise_confirmed_facts=false，true时仅用户confirmed决策允许修订confirmed事实；旧默认路径/历史hash不变。新intent编码进fact_updates_sha256及新event.operation，不能同key改intent重放；新路径不编辑FROZEN旧值或新增值，旧legacy默认新增事实行为保留。实际HTTP A20→B30→replayA保留B revision3/零SQLite写，canonical/application/event replay/API/Agent5共234passed (1.36s)，revision_history_check.log。旧冻结负例未修改；新增新路径冻结/intent混用/用户confirmed要求反例。revision_confirmation_red.log是proposed无效fixture（非行为证明）；改AI actor后的 revision_confirmation_behavior_red.log是真红，再修绿。

D仍未完成：需接入C current registry事实影响、B事实/条件验证、依赖read-set绑定/current validity、alias显式退休、整稿/章节版本影响同事务；当前接口新路径只完成版本推进子集，不得据此关闭3R.4。无新产品模型/监听服务；native Goal active且原文未改，新prompt在plans/mw_protocol_v3_goal_prompt_20260913.txt。


### D 当前确认输入绑定与原生事件恢复

新增 canonical/decision_inputs.py，DecisionInputRef(fact_path字面键,members显式成员) 与 DecisionInputBinding；API/Apply命令可提交非空唯一 decision_input_refs。服务在新采用后事实上计算对应值/存在性hash，随原事件同事务保存，新增输入引用也进入fact_updates意图hash；默认无refs旧hash/历史序列化不变。当前查询用每key最近事件的绑定值比较当前事实，三态 current/stale/unverified；只证明所记录输入未变，不冒称read-set覆盖齐全或医学批准。5R推荐producer必须从实际生成上下文产生并核验完整输入集合，不能让用户填写引用、更不能把客户端任意声明当专业完整性验收。

实际SQLite HTTP测试完成：采纳剂量A20（绑定采用后剂量）→无关age决策（绑定indication）→另一key剂量修订30→精确回放A。原A现stale、age仍current、新剂量current、legacy create unverified；replay保留revision4，查询/重放及同key改readset的409均零新增SQLite效果。Agent5原先忽略stale队列，已有真实失败current_queue_red.log，已接线仅stale再入队，无关/legacy不被整体重开。返回current_validity为有限Literal，不改历史canonical_state。

application/reconstruction.py 同步理解新operation/refs，从新存储连接读immutable events重建后hash等于最新保存revision。revised_reconstruction_red.log是真实新事件恢复失败，修复后current_queue_check.log 235passed (1.39s)。新原生类型/字面点号/member/unknown null与missing/空重复refs测试及API改readset重放测试 input_values_check.log 9passed。无C文件改动；C续作29505仍进行，D仍未接C计划/B校验/文档影响同事务，未接受D或整体3R4。


### D/V1接线顺序明确

源检查 application/service.py 无SemanticDocument采用入口，canonical/document.py apply_decision正确要求旧doc与输入study绑定一致。为不先造第二文档保存链，Plan v3现细化D先一次保存事实/条件/impact/输入有效性，整稿版本去重及保存验收继承到V1编辑器整合，义务未删除也未验收。此为用户授权的完整可用路径优先执行顺序优化；3R4独立review需核对。已加 registries/template_runtime.py（当前配置装配，复用source-bound loader，非旧runs快照），test_current_template_runtime.py 1passed；尚未接入adoption，不能单凭装配通过宣称D接线完成。


### D 当前模板接线执行正式派发

模式execution-plus-conference：D是有明确允许文件、输入版本和SQLite验收的独立接线工作，交给单一执行worker减轻上下文并让owner同步R03/Word源审阅；整体3R4冻结后仍需独立conference。C固定源owner复核34passed，记录 reviews/codex_mw_protocol_v3_3r4c_integration_readiness_20260913.md，C可接线但不是整体/医学验收。Trellis active_subitem=D，整体仍in_progress。

D run runs/execution/mw_protocol_v3_3r4d_template_adoption_20260913，logical key mw_protocol_v3_3r4d_template_adoption_20260913_v1。单worker E04 exact approved chains，GLM-5.3-Flash:max declared，7200s/128turn。已实际启动统一句柄82000，effective/session等待terminal receipt，不能提前声称验证。允许文件和before/hash见dispatch_contract。模型/工具首次有效连接已有本turn C证据，不重复产品probe。guard已知入口错误未伪装通过，沿用准确E04完整manifest/runner。无额外chair。

owner此后只读D产品源，不改其允许文件/测试；可写Plan/Trellis/review/source审阅资料，R03暂只读梳理，避免worker全量回归跨源变化。重点交付typed/template-bound实际API采用、B部分事实验证/alias显式退休、C计划与适用性snapshot同事件事务持久化、同key不同意图拒绝、真实并发/恢复。当前所有D owner新增代码已在before冻结。完成后owner读receipt/报告/diff/定向或联合证据，再独立review；不能因慢重派。


### 3R.5A/Word并行只读预检

D统一82000仍在原runner运行，owner未改其产品源/测试。R03源分母68+表头招募fragment及模板Word源对象已只读对账，详见reviews/mw_protocol_v3_3r5a_source_preflight_20260913.md与runs/mw_protocol_v3_3r5a_source_audit_20260913/。确认Word源全部required styles/bookmarks存在；正文与全story计数差异已解释。旧PoC成功交集/最多32项selector会遗漏失败引用，已有原函数反例word_selector_counterexample.json；V1.5需全量应有对象核对，Plan已补实，不改历史PoC。安装Word版本16.112.4仅bundle事实，原生验收未运行。Plan恢复段已从历史paused纠正为get_goal实测active，原生objective未修改。


### V1界面样稿并行细化（非产品验收）

Owner在D82000原session持续执行时，仅在runs/mw_protocol_v3_v1_visual_draft_20260913生成单文件workbench.html及verification/README，未改frontend或D产品源。使用kangzhe-web-visual-design与当前portable core/interactive；用户安静阅读/16与14字号选择优先于旧动效偏好，logo使用包内已验hash。示例八卡确认/四步布局、正文编辑仅当前页面、导出明确未接线且禁用。静态JS/ID/label/资源检查通过；CUA file://导航被URL策略拒绝，未绕过，实际渲染/截图/computed style未验证，不能作为V1.4完成。D当前已创建adoption实现及真实API反例，仍无terminal receipt；owner只读其进行中源码，不据中间版本验收或回修。


### D首轮终态、实际反例与同会话回修

82000已exit0，实际session sess_bd48bcda-b1b4-4561-b26e-7fef9d514b48；3005.143秒，117模型请求，request/response GLM-5.3-Flash、observed max，无fallback。2230通过不能关闭D。Owner实际API临时SQLite反例全部失败：旧精确replay依赖当前模板而422；同logical key新decision/CAS再次写入200；期中true→false保留旧alpha参数200。见owner_adoption_cases.json，源冻结hash见owner_followup_01/source_before.json。

已按验收失败用同session实际启动86523，timeout4100秒（原7200剩余4194内），logical key原D:owner_followup_01。要求修复ledger-first/操作去重/完整条件事实校验，并给出显式退休不适用参数的可用路径、保留历史，不能只拒绝造成用户无法修改。原路线manifest hash未变。owner不改worker允许产品源，继续其他只读来源/设计细化。D/3R4仍未验收，Goal active，未阶段暂停。


### D回修等待期间的来源准备

86523同会话执行未终态，无重派。Owner只写disjoint来源/Plan材料：R03 atomic_split_examples.md细化复杂源行，未实施registry；clinical-protocol-corpus技能已完整读取，实际18份研究方案库与现有5份条款库分开盘点。v1_material_inventory.json保存18文件hash，v1_docx_structure_screen.json只保存9DOCX结构/修订计数（不复制联系人/正文）。一份clean命名Ⅰ期DOCX仍有6处插入修订，不拿文件名当clean验收；Ⅱ/Ⅲ期可读DOCX候选存在，尚未选定真实项目或通过医学准入。无OCR、无翻译、无模型/Word/服务调用，外部文件只读。Plan/design已补三实际D反例及用户一次影响确认的处理语义。独立审阅brief仅准备，未dispatch/不冒充已完成审阅。


### D回修终态/owner复验/独立整合review实际启动

86523已exit0；同session sess_bd48bcda-b1b4-4561-b26e-7fef9d514b48，1426.137秒，actual GLM-5.3-Flash/max，无fallback。首轮+续作共4431.280秒。worker2234全量通过，owner原三反例独立再跑3/3通过，未覆盖旧失败JSON；新证据owner_followup_01/owner_verification.json绑定源hash。合法条件关闭/显式retired_fact_paths、历史保留、事件恢复/C影响定向44passed4.58秒（owner_targeted.log），没有无原因复跑全量。字段由本轮未接受的新retired_alias_paths更名扩展retired_fact_paths，原legacy历史hash未改，不能把首轮临时API当已部署历史；独立review仍核对兼容边界。

模式维持execution-plus-conference，365文件冻结于runs/mw_protocol_v3_3r4_integration_review_20260913/snapshot，manifest对应hash。已实际启动fresh C03统一14579，declared GLM-5.3:max，5400秒，actual身份等待receipt；与Flash执行不同variant但同provider家族，独立性限制如实保留。旧B70医学规则未漂移无需全部重复；审A-D实际接线，整稿V1义务不删不冒通过。guard入口既有malformed string未修，准确完整C03路线经既有runner；不声称audit通过。D/3R4尚未接受，无用户阻塞/无阶段暂停，Goal active。Owner在review期间不改冻结受审源码；下一步读终态并解决实质问题，随后3R5A及完整路径。


2026-09-13最终工程验收与续接：fresh14579已exit0，actual GLM-5.3:max session sess_f804a3c6-0db9-459c-86cc-6bb687984ffa/896.844秒，无fallback；32独立反例all true，365文件最终0漂移。Codex接受A–D工程并完成task.json，不archive/commit，见reviews/codex_mw_protocol_v3_3r4_acceptance_20260913.md。新当前任务.trellis/tasks/09-13-protocol-v3-3r5a已in_progress并实际派发R03 worker10218，恢复必须读新checkpoint；不要重新跑本阶段或旧回修。
