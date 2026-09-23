Working...
# T17 R12 Tester1 独立端到端报告（COPD II期 / 合成药C7）

- 项目：合成药C7 · 慢性阻塞性肺疾病 · II期 · MW-II-778C8338（新建成功，`proj_user_18e2030425fb`）
- 夹具：`runs/mw_protocol_v3_v1_1_20260913/browser_functional/synthetic-reference.docx`（699B）
- 浏览器：ego-lite TaskSpace 45，页面 `http://127.0.0.1:5186`，截图目录 `/tmp/t17_r12_tester1/`（60+ png，见下）
- SOURCE_HEAD：`05db86e66a458990163733e8673e0772e32bd86c 2026-09-23 20:55:23 +0800 docs(protocol-v3): R12 dispatched`
- 总耗时：约46min（12:47→13:33 UTC）；总点击/填充约140+（远超≤20，多为21张事实卡逐项采用+PICOS必填填充所致，如实记录）
- 本轮未改仓库任何代码；仅真实点击/查看/填充；AI长耗时步骤已耐心轮询（事实拆解~180s+，锁释放~110s）

## PASSED（达标=单步点击≤20）

| 步骤 | 结果 | 耗时 | 点击数 | 达标 | 证据 |
|---|---|---|---|---|---|
| 打开前端+项目总览（预期503直行） | PASSED | ~4s | 0（goto） | 是 | `05_project_board.png`：`monitoring_principal_unavailable HTTP503`，按已知非缺陷处理 |
| 新建项目对话框（从零/导入切换） | PASSED | ~15s | 6 | 是 | `06_new_project.png` `07_import_mode.png` `08_import_synopsis.png` |
| 从零创建COPD II期项目 | PASSED | ~5s | 1 | 是 | `14_created_workspace.png`：`MW-II-778C8338`，适应症/草案正确 |
| 产品事实填写+保存草稿 | PASSED | ~15s+解析180s+ | 7 | 是 | `36_saved_draft.png`：`草稿已保存，未完成本阶段；仍有3项必填`；小分子/全身暴露/口服固体制剂/口服已持久化（重载后`35/45`验证，首次未保存丢失后补填） |
| 事实拆解21卡逐项采用 | PASSED | ~80s | ~46 | 否（超标，逐卡必需） | `47_facts_adopted.png` `48_facts_all_adopted.png`：全部变`已采用`，`事实已采用并已回填` |
| Step1四tab补全+保存+完成+影响确认→进入Step2 | PASSED | ~10min | ~16 | 是 | `52_complete_step1.png` `57_confirm2.png`：研究目的PoC+剂量探索/竞品范围PDE3/4/总体设计随机双盲安慰剂/人群成人+中重度 |
| Step2 PICOS填充+保存 | PASSED | ~15min | ~37 | 否（超标，必填多） | `62_step2_saved.png`：`草稿已保存，未完成本阶段；内容完整后仍需点击完成`；IN-01~03/EX-01~02/BG-01/CM-A-01/CM-P-01/对照/终点/SGRQ已落盘 |
| 文献导入（PMID:33957195） | PASSED | ~60s | 2 | 是 | `42_lit_imported.png`：`1条可追溯文献`，Papp K 2021 JAAD 85(4)863-872 DOI齐全 |
| 文献搜索过滤+PubMed外链 | PASSED | ~5s | 1 | 是 | `44_lit_search.png`：`ruxolitinib`过滤命中；`https://pubmed.ncbi.nlm.nih.gov/33957195`锚点存在 |

## FAILED（阻断主链）

| 步骤 | 结果 | 耗时 | 点击数 | 说明 |
|---|---|---|---|---|
| 点“医学写作”版本门 | FAILED | ~15s | 3 | `01_version_mismatch.png` `03_mw_gate_retry.png`：`当前版本组合不可进入写作工作区 前端web-93975ff/期望api-605551e3/当前api-c2e8194`；与任务书“直接点医学写作继续”冲突；新建项目后才绕入 |
| 入口A夹具导入提取 | FAILED | ~30s | 5 | `10_extract_result.png` `11/12`：`方案摘要解析失败`→`synopsis import route configuration changed after task start`，`继续处理`空转 |
| 准备完整候选初稿 | FAILED | 21s轮询 | 1 | `15_prepare_result.png`：`方案工作台未能完成本次操作` |
| 竞品处理（790项保留但0候选/分诊失败） | FAILED | ~15s | 3 | `26_competitor.png` `27_competitor_refresh.png`：`公开研究检索已保留·790项；后续处理未完成`，`已结合790项及109份Protocol`与`0项`矛盾；`部分分块失败：研究流水线失败`，刷新/重试无效 |
| 文献插入引文 | FAILED | ~5s | 1 | `43_insert_citation.png`：`请先在左侧打开文档编辑器，再插入引文`，但左侧无编辑器入口 |
| Step1↔Step2互锁（完成第二步） | FAILED | ~5min多轮 | ~8 | `69_saved3.png` `70/71`：`完成第二步`title在`请先补齐第二步必填`与`请先保存并完成第一步变更后再提交PICOS`间摆动；Step1重确认会重置分组/中心为待确认，形成循环 |

## NOT_RUN（被上游阻断，无从验证）

生成完整初稿→逐项确认→保存工作稿→导出Word→浏览器Office打开编辑保存；引用编号自动/删除移动联动/定位回源；目录跳转/表目录/图目录；研究流程示意图形融合。工作台内按钮全量扫描无`目录/表目录/图目录/流程图/示意图/导出/预览/Word`命中，仅`保存草稿/文献/插入引文`存在。

## 问题清单

P0（主链阻断）：
- P0-1 Step1/Step2互锁+流水线失败致死循环。复现：COPD项目Step1完成确认→Step2填完保存（`草稿已保存…内容完整后仍需点击完成`）→点完成第二步disabled。截图`69_saved3.png` `68_restored.png` `70_step1_again.png` `71_final_step1.png`。
- P0-2 入口A夹具死路。复现：新建→导入方案摘要→选`synthetic-reference.docx`→导入并提取→解析失败→继续处理→英文路由错误。截图`09_uploaded.png` `10_extract_result.png` `11_continue_after_fail.png` `12_after_continue.png`。
- P0-3 医学写作版本门与任务书入口冲突。复现：初始RUX项目下点医学写作→版本组合阻断+重新检查无效。截图`01_version_mismatch.png` `03_mw_gate_retry.png`。

P1（内部标识符直出，按纪律记P1）：
- P1-1 英文枚举直出：事实卡`small_molecule`/`systemic`/`none`（应为中文小分子/全身暴露/无）。截图`48_facts_all_adopted.png`。
- P1-2 英文内部错误直出：`synopsis import route configuration changed after task start`；`fact intake conversation changed before the turn was committed`；`authoring journey change requires the current impact preview to be confirmed`。截图`11/12/42/54/64`。
- P1-3 `UNKNOWN` token直出：`记为UNKNOWN`与`未知·置信未知`混排。截图`48`。

P2（显示/缺失/矛盾）：
- P2-1 `790项+109份Protocol` vs `0项候选`自相矛盾；分诊重试无效。截图`26/27/34/45`。
- P2-2 高影响缺口计数漂移：同一项目先后显示3项→6项→7项。截图`36/48/57后`。
- P2-3 左侧导航`text=`点击被`<main>/<aside>/<p>`拦截，需ref点击；版本门出现后他模块不可点。截图`04_other_modules.png`。
- P2-4 测试空间非清洁：项目下拉仍有RUX/CMS-D001/MY009/MY008/MG-K10/RA-GREENFIELD/抑郁/MS等13项，与“旧项目已全部删除”不符。截图`23_copd_selected.png`。
- P2-5 跨适应症文献无警示：COPD项目可导入特应性皮炎ruxolitinib文献且无相关性提示（仅记录，非定性缺陷）。

## 重点模块结论表

| 模块 | 结论 | observed行为（缺失也是结论） |
|---|---|---|
| (a)文献引用与管理 | 部分存在，下游全阻 | 入口`文献`正常；支持DOI/PMID/官网链接导入（PMID实测导入成功，题录/DOI/期刊卷期页码完整，计数0→1）；引文格式`GB/T 7714-2015顺序编码制`；搜索过滤有效；PubMed外链有效；手动确认区要求先填标识再核对。`插入引文`点击后提示需先开文档编辑器，但工作台无编辑器/无初稿，故编号是否自动、删/移联动、定位回源均不可测。最小期望：无稿时插入按钮应disabled并说明前置条件；有稿后需自动顺序编号+删移联动+点击编号回跳文献卡/来源链接 |
| (b)目录与图表呈现 | 缺失 | 导出/预览入口不存在；目录/表目录/图目录无任何按钮、面板、设置；编号规则无从观察。最小期望：预览/导出提供可点击目录（章节锚点跳转）、独立表目录/图目录（表1/图1顺序编号+标题+页码/定位），导出Word保留域更新 |
| (c)研究流程示意图 | 缺失（仅文字提及） | 仅影响预览清单出现`研究流程图/研究流程表/研究依据`字样（`52/56/65`），无图形/文字框/层级图呈现位置；SOA表格设计器在执行统计tab被提及但未达语料准备不可见。最小期望：在PICOS确认后按研究时期自动生成横向流程图（筛选→随机→12周双盲治疗→结束/提前终止），与访视表同源、可点击定位章节 |

## 反拟合检索表（27词；无初稿故无正文污染，仅检查可见UI）

- drafting正文：未生成，不可检出，记NOT_RUN（无拟合证据，也无清白证据）。
- 工作台chrome/历史项目名中命中4词（属既有demo数据/占位，非本轮生成污染）：`类风湿关节炎`（输入占位`例如类风湿关节炎`+RA-GREENFIELD项目）、`银屑病`（CMS-D001项目）、`抑郁症`（`难治性重度抑郁症`MW-II-28B56B1C/53EF03B8）、`多发性硬化`（合成药M8 MW-II-ACB50FEC）。截图`23/34/46`。
- 其余23词均未在可见UI出现：子宫内膜异位/甲状腺眼病/肺纤维化/IPF/痛风/CLL/荨麻疹/白癜风/AML/骨髓瘤/便秘/镰状/IgAN/MASH/强直/干眼/前列腺/结直肠癌/偏头痛/骨关节炎/银屑病外的全部。
- COPD内容均有场景依据：PDE3/4、FEV1谷值、中重度加重年化率、240例、12周、LABA/LAMA、沙丁胺醇、2mg BID均为本轮用户输入原文回显+采用，无系统捏造外延。

## KNOWN_LIMITATIONS

- 仅真实用户路径；未直连后端/API/DB/文件；版本号/耗时取自界面与工具wall time，部分点击数为如实估计。
- 真实AI步骤（事实拆解/竞品/AI建议）耗时数分钟，未打断；`研究流水线失败`多次重试仍失败后停止，避免无效轮询。
- 仅测单PMID导入；未测DOI/URL/重复导入/删除文献（无删除入口可见）。
- 未达导出，(b)(c)只能给缺失结论+最小期望，无法给呈现形式/编号规则实测。
- SGRQ量表登记了元数据+确认用法，但附件上传需`完成PICOS并生成正文后`，未达。
- 未升级ego-lite（`0.5.1.11 update available`提示已忽略，待用户批准）。

EXIT=BLOCKED:写作主链阻断（Step1/Step2互锁+研究流水线失败），未生成初稿/导出/Office编辑

EXIT=0
