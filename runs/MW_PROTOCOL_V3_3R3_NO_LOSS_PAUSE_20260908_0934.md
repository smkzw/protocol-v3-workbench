# Protocol v3 3R.3 无损暂停 — 2026-09-08 09:34 CST

## 暂停状态与边界

用户明确要求“无损暂停”，覆盖此前连续推进指令。仅完成收尾、停止与保存，
等待用户明确恢复；不要因 Goal 仍显示 active 自动续作或派发。
Goal API 无暂停状态，本次未将目标冒标完成/阻断，也未改动应用数据库。
Trellis 任务仍未完成，meta.user_paused=true。恢复时以本记录和实时文件为准。

当前隔离区 HEAD=3d6772f1014f2a86f96eb3dae4fd878c70a5251c。
已有全部未提交修改原位保留，未commit/reset/stash/清理。live workbench、8910、
医学监查、外部SOP及plan-upgrade目录未写、未停服务。

已接受3R.1、3R.2及3R.3基础合同检查器；3R.3内容批次仍未完成。
首批12章节合同/12技能文件已交付过一次，正在修正；暂停时fixture52条，
包括原有48条与新增场景。仅库存计数，尚未独立确认原48ID完整、修正正确或验收通过。
修正版组装结果和partial/full检查文本已落盘；partial仍是12/111、incomplete。
第二批16章节任务已派发并阅读材料，但没有batch2合同/fixture/test交付。
没有启动后续阶段、产品模型探针、OCR、翻译、旧失败项重跑或新服务。

## 权威与文件快照

runs/mw_protocol_v3_no_loss_pause_20260908/snapshot_manifest.json 列出：
- 最新global/project AGENTS、design-v1.3、Plan-v2、handoff、冻结旧Plan、清洁模板哈希；
- 73个任务相关文件的逐文件SHA256与大小，快照位于同目录files/，约1.36MB；
- Git状态清单git_status.txt和已跟踪工作树补丁tracked_worktree.patch；
- 两个原始model-io日志的位置、哈希、尺寸、session/turn ID（原位保留，不复制私有trace）。

清洁模板SHA256仍为018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756。
3R2schema仍b76a048ff1f50cb89ea0504819281e7ef0d0f6f481c73496d577b2cb7ba0f2e9。
3R3checker仍9297ed918d402a46ce47cc2ad15e80dda7ab8cf07a38632ecef4049eb9f1b739。
Assembler当前3c96750782c68a1473715388a33f845c33b250cf04ab200e46187c99984c2b63。
Batch1fixture当前bafa03e19765408c4d7aa74d51eb8bd697dd1840c1e1d48dc4a287ebbfee8cfa。
Batch1test当前f04564b29ab7ef79941dfd567f5e6b62d1960594777e87e5d530f6e17d21612b。

快照捕获的是暂停前状态；暂停记录与Trellis收尾字段另见pause_closure_manifest.json。
不要将旧快照覆盖到后续已有新修改上；恢复先比较，不自动回滚。

## 本段验证证据与未决项

既有core验收reviews/mw_protocol_v3_3r3_core_acceptance_20260906.md仍适用其哈希范围；
上次扩展1771PASS不能代表当前章节批次验收。
Main本段：组装器明确按coverage_roles读切片，3个RED后与原8测试共11PASS；
多批组装4个RED后4PASS。证据位于runs/mw_protocol_v3_3r3_batch1_20260906/。
暂停前另修正缺失章节测试在临时副本中制造缺失，避免下一批新增破坏测试前提；
该最新测试变化尚未再跑。未在暂停后启动测试。
六个内容RED：无服务方、非随机单臂比例、共享方案身份、SVG实际哈希、
药品注册分类与试验登记混淆、缩略语空条目，均待修正版复核。
修正版需要核对摘要17行、独立证据组、条件适用性、旧48fixture保留及非空有效负例。
特别检查字段改名是否让原负例变成无效删除，不能只看PASS数字。

Main同时更新batch3/5来源准备、GCP2026官方转载核对、GVP报告时限来源；
计划补充新正文首选“试验参与者”但不篡改引文/历史标题，不声称法规禁用同义词。
参考reviews/mw_protocol_v3_gcp2026_source_check_20260908.md及相关batch specs。
这些是实现输入，不是正式医学/监管验收，不能据此新增安全工程。

## 执行、停止与会商 lineage

1. 首批最初执行：sess_b91d51c2-ce9c-48fe-9add-59201fcf8927，
   ZCode/GLM-5.3-Flash:max；原报告和receipt仍在runs/zcode_mw_protocol_v3_3r3_batch1_20260906*。
2. 首批同会话修正：logical key mw_protocol_v3_3r3_batch1_repair_20260908，
   handle28260 / PID51942，turn_6c01694b-a569-4b4c-a2ea-145b0b387d93。
   输入context/mw_protocol_v3_3r3_batch1_repair_20260908.md和同名prompts/zcode_*.md。
3. 第二批：logical key mw_protocol_v3_3r3_batch2_20260908，handle16850/PID66286，
   session sess_4df83643-16c7-405c-af7a-1ab779584ad3，
   turn_a4bc05a9-f84c-4680-9540-1491e4e29fc7。
   context/mw_protocol_v3_3r3_batch2_20260908_context.md及对应prompt保留。

两runner在核对命令绑定后收到用户授权SIGINT，均exit130/KeyboardInterrupt，
runner finally清理各自app-server。逐个核查原8个runner/后代PID均已不存在；
没有fallback或新派发。不是terminal模型失败，不允许据此自动更换模型。
model-io原位日志分别22/30条，已读最后记录均请求GLM-5.3-Flash、返回glm-5.3-flash、
variant=max；这是已完成请求身份，不等于整个任务终态验收。
两项修正/第二批runner最终报告和stdout receipt尚未落盘，不伪造完成报告。
中断处Python内存事件不保证形成最终receipt；已持久化原始日志和文件完整保留。

本段未派发新的fresh reviewer。旧基础设施reviewer
01a07306-8334-7000-9a3d-f9d3d3975e37的ACCEPT仅针对已绑定基础设施版本，
不覆盖章节修正。所有旧prompt/report/session/log/evidence保留原位。

## 精确恢复动作（仅用户明确要求恢复后）

1. 重读最新global/project AGENTS、本暂停记录、当前Plan-v2加amendment、
   Trellis3R3记录；比较快照哈希与现文件。不要重做已验收3R1/3R2/core。
2. 先对账两个logical key、原session/turn和已落盘文件；旧handles已终态，
   不再wait它们。不将缺失最终report当作未启动而新建重复工作。
3. 同模型同session续接首批修正，使用新的resume prompt/output/receipt路径，
   让执行者先检查已有24JSON/52fixtures和诊断，再补齐剩余测试/报告，不重写已正确部分。
   Core/schema/assembler/Main反例保持只读，拥有文件范围仍按repair context。
4. 对账第二批后同session继续其原16章节范围，不重复健康探针/初始派发。
   两者可在不同文件内重叠编写，但按批序核查接受；每次恢复按当前runner能力与route验明。
5. 首批稳定后运行batch1测试及Main6内容+3组装+4多批反例，复核来源和非空测试；
   然后fresh独立审阅，继续batch2到8，再3R4/3R5。
6. Task3R6才提交Ⅰ期模板选择卡。产品1R6探针已经SUCCEEDED，绝不重复。
   恢复后按用户要求持续推进；阶段报告不暂停，但本次明确用户暂停优先。

测试环境沿用runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python，
env-i必须含原TMPDIR，否则旧hygiene测试会出现环境性假失败。
