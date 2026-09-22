# Protocol v3 0922V2 无损交接（WP1–WP5已实现，WP6自动回归完成）

## 1. 接手入口与权威顺序

工作区：`/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313`

按顺序读取：

1. `/Users/smkzw/.codex/AGENTS.md`
2. 工作区`AGENTS.md`
3. `plans/protocol_v3_0922V2_execution/00_START_HERE.md`
4. 同包`01_REVIEW.md`、`02_AUTHORITY_AND_MATERIALS.md`、`03_PRD.md`、`04_DESIGN.md`、`05_PLAN.md`、`06_EXECUTION_RULES.md`、`07_ACCEPTANCE.md`
5. `tasks/WP0.md`至`tasks/WP6.md`
6. `.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md`
7. 本文、`runs/requirements_v2_20260919/wp6_0922v2_20260922/PARTIAL_ACCEPTANCE_REPORT_20260922.md`及同目录复盘。

Goal文本：`plans/protocol_v3_0922V2_execution/GOAL_PROMPT.txt`。native Goal已是paused；恢复时应沿用该目标，不另建/fork任务。

## 2. 历史来龙去脉

9月21日前系统已具备研究设计、全文生成、语义稿、GenOffice快照、引用和局部AI的若干部件，但存在两套稿件所有权、生成候选没有进入当前Office、核对把同数字误当一致、保存只看HTTP成功、富文本撤销丢格式、引文表移到文末以及宽屏低密度等问题。Study A v0.9虽85/85返回，独立医学审阅仍为REVISE，且只有44 complete、40 source_gap、1 decision_required；该工件保持只读，禁止采纳或重放。

0922V2包将现有manuscript/Office定义为唯一用户当前稿，full-draft降为候选生产者薄适配。用户要求WP1–WP5连续构建、不逐改测试，WP6一次集中验收；本任务按此执行。

## 3. 本轮实现状态

### WP1 当前稿接线

- full-draft合同升级为v0.10混合正文+缺口；候选含semantic node映射、来源证据和不可变字节hash。
- 新增`protocol_workflow/application/authoring_bridge.py`与`api/authoring_bridge.py`，把两入口的authoring journey/StudyDefinition/full-draft接入同一manuscript。
- 候选采用通过CAS和事件原子激活；旧Word不被静默覆盖；v0.9历史兼容只读保留。

### WP2 决定与局部重写

- 1–6项相关决定可一次原子确认，绑定同一研究revision、framing/PICOS快照和operation。
- 事实已写但入队/回执未知时恢复同一操作，只补未完成后继，不重复问用户。
- 局部重生成与采用只替换受影响semantic blocks，保留其他正文和人工稿。

### WP3 医学语义与核对

- estimand/ICE仅在同一主要estimand、同一伴发事件和同一结局语境比较；不同ICE可有不同策略；“治疗策略人群”不被推断为治疗策略。
- 探索性目的/终点卡必须提供明确“不设置”选项，但不设全局默认。
- Office核对v2分为已直接定位、待语义核对、本次未覆盖；零检查为not_checked；无关段落同数字只算线索。

### WP4 来源冻结与SOP复用

- 每个任务冻结source id/version/hash/role/locator与完整source ref；执行和恢复只读冻结版本。
- 候选工件/UI展示实际资料版本。
- 公司SOP常规运营内容项目级一次确认后按相同公司来源版本复用；剂量、安全、统计固定排除并各自确认。

### WP5 Office、引用和宽屏

- bridge严格核对persisted、operation、内容hash、artifact/document/study revision；坏JSON/假成功/错身份保留同operation、pending bytes和dirty。
- Office操作指纹升级v2，覆盖文档hash、Office基线、打开时研究版本；旧v1事件继续恢复。
- 选区替换保存格式签名和原Slice；只支持同一段/单元格内统一行内格式。混合格式或内嵌对象明确拒绝，撤销恢复Slice。
- CMS文献表重建保留原位置、容器属性与行内样式；未知第三方字段不改。
- 现有双栏收紧：bridge左栏220–280px，候选/决定为紧凑网格与bullet；打开Office后隐藏已采用候选长卡。
- renderer可重建包：`runs/requirements_v2_20260919/wp5_renderer_repro_20260922/`。上游base `316ded6f0a39235fec8d21c068d8a0766ee6172b`，patch hash和bundle hash见manifest。不要向`genspark-ai/genoffice`公共origin推送；本项目通过工作台仓库保存补丁和bundle。

## 4. WP6当前证据

PASS：

- 工作台build 1971 modules。
- 前端15/110 Vitest与48/66 Node。
- 后端2601 passed、1 warning。
- GenOffice docs/docx-engine typecheck；docx-engine 1398 passed、1 skipped。
- renderer build 483 modules。
- 两库diff check。

日志：`runs/requirements_v2_20260919/wp6_0922v2_20260922/logs/`。第一轮失败日志保留，用于解释夹具、PYTHONPATH和派生物漂移，不要清理。

未完成：当前源码对应的隔离SQLite/HTTP、ego(lite)、2+1真实模型、原生Microsoft Word改后保存重开、完整医学接受和fresh独立会商。完整矩阵见partial acceptance，全部未完成项保持NOT_RUN。

## 5. 当前工作树与保护边界

- 暂停前HEAD起点为`acf6d8341563d56946f934dfdac65c76997e36e3`；本轮成果将以新的工作台提交推送。
- `genoffice-upstream`仍是dirty base 316ded6，本地修改已封装到工作台renderer重建包；不要reset。
- 历史runtime、会议、执行证据和大量未跟踪目录均保留。不要清理、搬迁或重新初始化。
- `runs/mw_protocol_v3_unified_tests_20260919/e2e_runtime`三份AI设置/运行日志是接手前已有dirty，未作为本轮产品配置修改清理。
- live 8910、5186、5285仍在监听，本轮未停、未重启、未写。恢复验收使用隔离端口。
- 没有在途worker、产品模型job、浏览器TaskSpace或命令session。

## 6. 恢复后的精确下一动作

先读取本交接和Trellis，核对Git HEAD/dirty、renderer manifest和监听器。随后在新的隔离runtime副本启动API/前端，按失败族执行B01–B10真实SQLite/HTTP，特别验证：双入口同稿、相关决定原子确认、enqueue/回执未知恢复、候选CAS、来源变版和Office真实receipt。不要调用v0.9或先跑85章v0.10。

控制流稳定后用ego(lite)完成V01–V08和B09–B12：三种宽屏、长文本、IME、切研究、专注不重建iframe、选区富文本替换/撤销、引文增删移动、保存丢回执和下载重开身份。然后才按批准路由`opencode-go/deepseek-v4.1-flash:max`运行两个差异研究加一个盲测；保存真实effective身份。最后用Microsoft Word实际修改、保存、关闭、重开并导出PDF，冻结产物后发起fresh工程和医学会商。

若在恢复前源码或runtime有新漂移，先记录差异，不覆盖。只有科学取舍、Ⅰ期模板、第三方互操作扩围或生产cutover需要用户决定。
