Working...
# T17 R15 独立端到端测试报告（Tester 1，COPD II期 / 合成药C7）

SOURCE_HEAD=4cc2debc16a477cf0776bed697d89b37a9ba00f7 · 前端 http://127.0.0.1:5186 · 会话约36分钟（04:03→04:39）· 真实点击约28次（>20，未达标，主因是重试与轮询）· 截图 /tmp/t17_r15_tester1/（38张）· 项目 MW-II-869AD68B（合成药C7 · COPD · II期）

## 结论先行
写作链死在步骤01"研究框架"：建议采用报 stale、更新建议卡 in-flight 死锁超15分钟且全部操作按钮 disabled，步骤02/03锁定。**EXIT=BLOCKED:研究框架确认死锁（prefill stale + in-flight 死锁），无法进入PICOS/初稿/导出**

## PASSED / FAILED / NOT_RUN
- PASSED：项目总览503预期保护（截图01）· 新建项目建项（从零开始，约9s，截图06）· 产品字段填写（小分子/全身暴露/口服固体制剂/口服，截图07/19）· 自然语言事实填写201字（截图20）· 总体设计模式填写（截图29）· 文献PMID导入成功1条（26s，截图13）· 文献卡片含PubMed回链（截图14/15）· 取消流水线后保存草稿成功（10s，截图18）
- FAILED：夹具导入解析失败（2次不同文案，截图03/04/05）· 建议采用失败stale（截图24/33）· 更新建议死锁（截图34/35/37/38）· 人群复选框无法勾选（成人/中重度点击回滚）· 取消流水线按钮零尺寸（真实点击不可达，仅JS可点，截图16）
- NOT_RUN：逐项确认完成→初稿生成→保存→导出Word→Office编辑（前置死锁不可达）· 文献编号自动/联动/定位（无编辑器，无正文）· 目录/表目录/图目录/锚点跳转（无预览导出面）· 研究流程示意图（全站未见）

## 问题清单
- **P0-1 写作链死路**：①点击"采用推荐"→`live evidence catalog resolution failed: prefill package journey revision is stale: expected 4, package 2`（重试一次，reload后仍复现）；②点击"更新建议"→`prefill generation is already in flight for this revision (logical call mwprefillcall_5ed1d99e92754e26a07c9551); force cannot interrupt the live call`（重试2次，等待超15分钟仍`正在根据最新研究事实和调研结果更新建议...`，保存草稿/完成第一步/采用/一键采用/更新建议全disabled，步骤02 PICOS设计、03语料准备锁定）。复现：进医学写作→填产品+事实→取消流水线→保存草稿→点采用/更新。截图24/33/34/35/37/38。
- **P1-1 内部标识符直出**：`mwprefillcall_5ed1d99e92754e26a07c9551`、`prefill package journey revision is stale: expected 4, package 2`、`live evidence catalog resolution failed`、`design_recommendations_blocked:corpus_not_ready`（候选抽屉hidden节点）直接显示给用户。
- **P1-2 人群必填无法填**：`总体设计意图→目标研究人群意图*`9个复选框（成人/儿童/青少年/轻中度/中重度/重度/初治/经治疗效不佳/未经某类治疗）真实点击与label点击均回滚为unchecked；保存提示"仍有3项必填内容待确认"，完成第一步永久disabled。截图29。
- **P1-3 入口A夹具导入失败**：上传synthetic-reference.docx→"导入并提取"→先"方案摘要解析失败。已完成的解析进度仍会保留"，"继续处理"后变"synopsis import route configuration changed after task start"，被迫改走从零开始。截图03/04/05。
- **P2-1 取消流水线按钮零尺寸**：`取消研究流水线`getBoundingClientRect 0×0，ego真实点击`none can receive input`，JS click才生效；同类`提交并拆解`初始亦disabled零尺寸。截图16。
- **P2-2 文献DOI导入404**：`10.1183/13993003.00065-2023`→"文献导入失败：HTTP Error 404: Not Found"（20s）；换`PMID: 33957195`成功（26s）。单样本，或为网络/代理问题，不定缺陷。截图12/13。

## 重点模块结论表
| 模块 | 结论 | observed |
|---|---|---|
| (a)文献插入正文 | 部分存在、核心不可验 | 入口：写作页右侧"项目文献库"（DOI/PMID/官网链接+导入+手动题录+搜索+GB/T 7714-2015唯一格式）。PMID导入成功后卡片显示题名/作者/年/期刊卷期页/DOI + PubMed外链（_blank）。点"插入引文"提示"请先在左侧打开文档编辑器，再插入引文"——本阶段无编辑器。编号是否自动、删除/移动后联动、引用回跳：无正文可操作，NOT_RUN |
| (a)缺失即期望 | 最小期望：编辑器出现前禁用"插入引文"并明示；有正文后编号自动连续、删段重排、点击编号回跳文献卡 | — |
| (b)目录与图表 | 缺失（NOT_RUN） | 全站无预览/导出入口；框架/PICOS/语料/抽屉/文献区均无目录、表目录、图目录、锚点。最小期望：导出Word含可跳转中文目录（标题1-3级）+表目录/图目录（按表1/图1顺序编码） |
| (c)研究流程示意图 | 缺失（NOT_RUN） | "研究流程示意图"在框架/PICOS/总体设计/抽屉中均无呈现位置（仅有访视表SOA提及、无图）。最小期望：PICOS确认后自动生成"筛选→随机→双盲治疗12周→随访"纵向流程图嵌入正文第2章，与文字描述同源 |

## 反拟合检索表
正文未生成（死锁在框架步），可检索文本仅界面+文献卡。命中任一违禁词即记：**零命中**。说明：①文献卡为特应性皮炎（ruxolitinib cream）系我主动用PMID:33957195测试导入，非系统拟合；②项目下拉含银屑病/溃疡性结肠炎/PNH/鼻炎/类风湿/抑郁/多发性硬化/骨关节炎等**历史项目**，非本项目内容；③竞品候选仅NCT编号列表，无病种文本。COPD场景依据：项目头/适应症/标题/事实文本均为用户输入，无系统生成COPD断言可核验。

## KNOWN_LIMITATIONS
- 单DOI 404未排除网络/代理因素；仅测1个PMID，未测 manual 确认导入全流程。
- 等待纪律：竞品分诊 4/25停滞3轮（约5分钟）后选"取消本次流水线并立即提交"（JS点击，约5s生效）；prefill in-flight按10-40分钟纪律实际等超15分钟+reload+3次重试仍死锁后才判死路。
- 未改仓库任何代码；AI耗时长的等待态均如实轮询（1-2分钟间隔），未提前结束。

EXIT=BLOCKED:研究框架确认死锁

EXIT=0
