# 医学写作子系统 Protocol v3：完整交接（3R.4暂停点）

生成：2026-09-11 23:30 Asia/Shanghai
交出者：ZCode（2026-09-11 21:14 接管的会话）
接收者：下一位 Agent（用户指定继续推进）
文档用途：让接手者对全局来龙去脉了然于胸，像原生做的一样继续构建。本文件不是
完成证明，不自动开始任何实施。

---

## 0. 接手前先读这一页

**当前位置：3R.3 已全部完成并验收（111/111载体）；3R.4 依赖图首交付已通过主owner
验证（217/217测试），其 fresh 独立复核因 GLM 配额耗尽而终态失败、待重派（只读复核
可合法重派，材料现成）。用户已于 23:22 无损暂停并要求交接。**

五条最重要的事实：

1. **进度远超上一份交接文档的预期**。上一份（HANDOFF_PROTOCOL_V3_20260911.md）停在
   "首批修复未验收、第二批未交付"；本夜已推进到"8批次111载体全部验收 + 全量组装
   full lint COMPLETE + 3R.4首交付验证"。请以本文件与Trellis为当前状态，不要按上
   一份交接的悲观基线重做任何事。
2. **3R.3 的验收范式已固化且高效**：worker交付 → 主owner组合套件+独立组装复现+
   越界审计 → 非同族fresh复核 → 缺陷按复核者最小方案修复 → 验收文档 → commit。
   本夜8批次共产出8份复核报告、8份验收记录、27个缺陷全部修复。**接手者应直接
   复用这套流水线与派发合同模板**（见第6节），不要另起炉灶。
3. **3R.4 复核重派是恢复后的第一个动作**（不是重做依赖图——图已交付验证）。
   GLM 5小时配额 2026-09-12 01:44:45 重置；建议直接走非GLM家族路线复核。
4. **工作树有413个脏条目是有意的**：runs/prompts/context/handoff 等证据与派发包
   按文件归属纪律不入commit。不要 git add 全部，不要清理。
5. **连续实施纪律**：常规阶段不问用户"继续"；真实用户决策点只有 3R.6 Ⅰ期模板选择、
   生产激活、真实项目cutover 等。用户已排除纯安全工程（1R.5 USER_EXCLUDED）。

---

## 1. 任务规划：完整来龙去脉

### 1.1 产品是什么，为谁而建

用户是资深医学写作人员（懒惰、视觉敏感、不熟悉计算机/AI），需要一个个人本地
研究方案工作台：导入已有资料 → AI提取事实/给推荐/写完整初稿 → 用户点选确认 →
受控修改 → QC → 原生Word → 文档就绪。硬性UX预算：标准Ⅱ/Ⅲ期路径关键点击≤20、
必填自由文本≤5、正文≥14px、8类高风险逐卡人审（红tag、AI预填理由、禁机械字数校验）、
变更后只重开受影响确认。不要让用户理解模型/提示词/队列/哈希。

### 1.2 历史时间线

| 时段 | 事件 | 对接手者的含义 |
|---|---|---|
| 2026-07-24~31 | r42旧系统推进（分诊19/19、OCR 89pass等），原父会话JSONL被删后重建证据 | 历史证据源，不是续作位置；不得重启旧失败项 |
| 2026-08-08/09 | 多Agent重构设计冻结，在隔离区构建（Phase0-8编号来源） | 隔离区=本工作区；冻结计划仅继承未替代部分 |
| 2026-08-12 | Phase1+Task2.1暂停于HEAD 3d6772f | 旧基线 |
| 2026-09-05 | 另一Agent整理design v1.3+Plan v2+handoff，用户批准DC-019~030（纯安全排除、PyMuPDF放行、GLM默认、R阶段等） | Plan v2+附加修订=任务权威 |
| 2026-09-05~08 | 完整工程review、PhaseR、1R存储/挂载/集成/简化/探针、2R.1 typed facade、3R.1模板抽取、3R.2 schema、3R.3 core+batch1交付+六内容反例修复中断 | 各阶段各有验收记录（见第4节） |
| 2026-09-08 09:34 | 用户无损暂停（batch1修复worker与batch2 worker被SIGINT） | 中断非失败 |
| 2026-09-11 早 | codex编写交接文档 HANDOFF_PROTOCOL_V3_20260911.md | 上一份交接，其§0的悲观预期已被本夜超越 |
| **2026-09-11 21:14~23:22** | **本会话（ZCode）接管：对账→工程review→Plan/goal更新→3R.3全部8批次验收关闭（111载体）→3R.4首交付验证→复核因配额耗尽失败→用户23:22无损暂停并要求交接** | **当前位置** |

### 1.3 任务串行路线（Plan v2权威）

```
Phase R/1R/2R.1/3R.1/3R.2/3R.3core  ✅ 已验收（本夜前）
3R.3 八批次内容合同                  ✅ 本夜全部验收关闭（111载体）
3R.4 依赖/影响图                     🔶 首交付已验证；复核待重派；条件规则executor未做
3R.5 R03 QC criteria registry        ⬜（含word_rules交叉校验改进项）
3R.6 Ⅰ期模板问题卡                   ⬜ 用户决策点（预选推荐T02修订版）
3R.7 术语库/缩略语/L1检查             ⬜
4R 资料链（ResearchSeed→指南）        ⬜
5R 设计推荐与确认（8高风险逐卡）       ⬜
6R 受控编辑面+写作链+新WritingPage    ⬜（20点击/5自由文本硬预算）
7R QC/Word闭环                       ⬜
8R shadow/切换/E2E（真实浏览器计数）  ⬜
```

---

## 2. 目标：已实现/未实现/方向深度分析

### 2.1 已实现（本夜增量，全部有验收记录+commit）

| 工作 | 结果 | 证据锚点 |
|---|---|---|
| 接管对账 | 7权威+6代码哈希与上份交接逐字节一致，无漂移 | runs/MW_PROTOCOL_V3_TAKEOVER_RESUME_20260911_2114.md |
| 工程review+Plan/goal更新 | 组件地图验证、A1-A4新问题、技术路线维持（不引LangGraph/MAF/分布式）、功能建议落实4R-7R | reviews/mw_protocol_v3_takeover_review_20260911.md |
| batch1修复验收 | fresh复核ACCEPT_WITH_ACTIONS，6缺陷全修（D1全局glob等值→超集最关键） | reviews/mw_protocol_v3_3r3_batch1_repair_acceptance_20260911.md |
| batch2~8交付+验收 | 7批次全走"验证→复核→修复→验收→commit"流水线；裁决1×ACCEPT+7×ACCEPT_WITH_ACTIONS，27缺陷全修 | reviews/mw_protocol_v3_3r3_batch{2..8}_acceptance_*.md |
| 全量组装 | 111章/558fixtures，full-mode lint **status=COMPLETE** | runs/mw_protocol_v3_3r3_batch8_fresh_20260911/final_all8_lint.txt |
| 跨批crosswalk | 13项全PASS（避孕扩展/PK-PD-ER确证链接/body323/父叙述/容器角色/ID唯一） | 收尾评估文档 |
| 3R.3收尾 | Trellis 09-06 completed；deferred正式移交3R.4/5、4R/6R/7R | reviews/mw_protocol_v3_3r3_batch8_acceptance_and_3r3_closure_20260912.md |
| 3R.4依赖图首交付 | dependency_graph.py(664行,三类typed边,条件事实解析,41调度边)+10测试；组合217/217；核心零触碰 | runs/mw_protocol_v3_3r4_20260912/report_codebuddy_3r4_depgraph.md |
| Commit边界 | **8个commit**：b0b3663→7118329→98db346→cfeebdf→48f01c9→a67b9a2→5c3ad99→**84488d3(HEAD)** | git log |

### 2.2 未实现（按优先序，含设计性deferred的正式去向）

1. **3R.4复核**（重派即得）→验收→commit两文件。
2. **3R.4条件适用性规则运行时executor**：各批复核均确认conditional_*_not_executed
   为deferred；依赖图已索引全部conditional_applicability_rules，executor可实现于
   registries/层。**这是合同语义从"声明"变"可执行"的关键一步**。
3. **3R.5 R03 QC registry**：68内容行（54有代码+14无代码）拆原子检查，分类
   deterministic/agent4/human；吸收改进项——word_rules样式/书签/交叉引用的checker
   交叉校验（batch4/5同类缺陷只有复核能拦，batch4 D1+batch5 D1/D2实证）。
4. **3R.6 Ⅰ期模板**：真用户决策点，准备差异/风险/迁移影响后提问。
5. 3R.7→8R：见1.3路线。
6. 横切改进项：DOCX源文统一再核对（全批复核均以node_tree为前提，DOCX未开——
   设计性延后，记入各验收残余风险）。

### 2.3 方向深度分析（接手者判断的依据）

- **技术路线已定且经实证**：React/Tiptap受控语义编辑+Python领域服务+SQLite+
  typed facade+五类Agent职责+只读预览+原生Word回流。不引入LangGraph（除非typed
  facade被证明不够）、MAF、浏览器Word分页引擎、多数据库/分布式队列/每章自主Agent。
- **质量机制产生复利**：复核缺陷模式（word_rules空、条件规则引用未声明事实、
  归属声明缺失、负例缺expected-code、布尔prose化、日文字符、provenance窗口越界）
  已全部固化为派发合同先例条款——batch7/8 worker首次交付即合规，缺陷数从6降到2。
  **接手者写新派发合同时应继承全部先例条款**（模板见第6.3）。
- **产品的真正风险已前移到内容语义与用户价值**：3R.3完成意味着"模板义务的结构
  化"完成；接下来的3R.4-5决定"变更影响与QC能否机器执行"，4R-6R决定"AI lead写作
  是否真的完整"。工程基础设施（存储/事件/恢复/探针）此前已验收，勿重做。
- **不要被测试数字迷惑**：单元绿≠医学正确≠浏览器可用≠Word验收——四层分别记录
  （用户明令）。本夜全部工作属第一层+结构层。

---

## 3. 目前节点分析（问题与解决方向）

### 3.1 节点卡点：3R.4复核的GLM配额耗尽

- 事实：23:21派发的zcode/GLM复核于23:24终态失败（ProviderBusinessError[1308]
  5小时上限，01:44:45重置），exit 1零输出，stderr.txt留栈。
- 解决：**直接重派复核**（只读无副作用，不违反"不重复派发"纪律）。最优解是
  走非GLM家族（产物=deepseek-v4.1-flash的依赖图→codebuddy/deepseek-v4-flash同
  harness不同模型可接受[batch1/3/8先例]或omp/gpt-5.6-luna）；GLM配额恢复后亦可。
  prompt/context现成，只需替换runner路径名。
- 教训（供预算管理）：zhipu-coding-plan 5h窗口在连续多轮zcode headless复核下会
  耗尽；后续复核优先轮流用不同harness，GLM留给需要它的场合。

### 3.2 已知问题清单（按优先级）

| # | 问题 | 解决方向 |
|---|---|---|
| P1 | 3R.4复核未完成 | 重派（见3.1），材料现成 |
| P2 | 条件规则运行时未执行（全批复核确认） | 3R.4第二工作项；依赖图已索引规则，executor放registries/层 |
| P3 | word_rules三类字段checker不交叉校验（batch4/5缺陷只有复核拦住） | 纳入3R.5（lint增强），验收记录已记账 |
| P4 | DOCX源文未统一再核对（各批以node_tree为前提） | 4R资料链时对账；各验收残余风险已声明 |
| P5 | Trellis 00-bootstrap仍in_progress、1R.2元数据遗留in_progress | 低优先维护项，验收间隙对账，不阻塞产品线 |
| P6 | 工作树413脏条目 | 有意（证据/派发包）；按文件归属逐commit，勿全量add |

### 3.3 流程性教训（本夜实证）

- 过细短回合已被"连续实施+完成事件驱动"取代——保持。
- harness特性：grok后台长任务会被harness取消（两次截断，弃用于复核）；codebuddy
  plan模式拒Bash（复核者静态核验，主owner跑测试补足）；codebuddy报告在stream-json
  的result字段；omp报告在agent_end的assistant text；zcode headless stdout在进程
  结束才落盘（中途0字节是正常的，配额错误看stderr）。
- 写审计时间戳必须查date/mtime，不能凭感觉（本夜曾写错23:xx系列，已全部按mtime
  修正并在checkpoint留修正记录）。

---

## 4. 权威文档（按阅读顺序）

### 4.1 全局与项目规则

| 文档 | 路径 |
|---|---|
| 全局AGENTS（zcode） | /Users/smkzw/.zcode/AGENTS.md（d12c565a5e86b3ba…@暂停时） |
| 全局AGENTS（codex） | /Users/smkzw/.codex/AGENTS.md（e01f795dcdf88674…=交接14.1记录，未变） |
| 项目AGENTS | 隔离区/AGENTS.md |
| 路由清单（当前权威） | /Users/smkzw/.zcode/zcode-route-manifest.json（执行/会商派发前必查） |
| 执行/会商工具 | /Users/smkzw/.codex/tools/hermes_workflow_guard.py（preflight/init-execution/audit等）、conference_session_runner.py |

### 4.2 计划与设计（任务权威）

| 文档 | 路径 |
|---|---|
| Design v1.3 | ../plan-upgrade-20260905/mw_protocol_v3_design_v1.3_20260905.md（**只读**） |
| Implementation Plan v2 | ../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md（**只读**，040eb6ad…） |
| Execution handoff | ../plan-upgrade-20260905/mw_protocol_v3_execution_handoff_20260905.md |
| 附加修订（用户批准变更） | 隔离区/plans/mw_protocol_v3_review_amendment_20260905.md |
| 状态索引（只作索引） | 隔离区/plans/mw_protocol_v3_execution_tracking_20260905.md（顶部指针=当前） |
| 本会话接管review+Plan更新 | 隔离区/reviews/mw_protocol_v3_takeover_review_20260911.md |

### 4.3 暂停/恢复/交接（当前状态权威）

| 文档 | 路径 |
|---|---|
| **本夜暂停记录（恢复入口）** | 隔离区/runs/MW_PROTOCOL_V3_3R4_NO_LOSS_PAUSE_20260912_2322.md |
| 上一份交接（历史背景） | 隔离区/handoff/2026-09-11/HANDOFF_PROTOCOL_V3_20260911.md |
| 3R.3收尾评估 | 隔离区/reviews/mw_protocol_v3_3r3_batch8_acceptance_and_3r3_closure_20260912.md |
| Trellis当前任务 | .trellis/tasks/09-11-protocol-v3-3r4/{task.json,checkpoint.md}（user_paused=true） |
| Trellis已完成 | .trellis/tasks/09-06-protocol-v3-3r3/（completed） |

### 4.4 3R.3验收与复核证据（8批次全套）

验收：reviews/mw_protocol_v3_3r3_batch1_repair_acceptance_20260911.md、
batch{2..7}_acceptance_20260911.md、batch8_acceptance_and_3r3_closure_20260912.md。
复核报告：runs/mw_protocol_v3_3r3_batch{N}(_resume|_fresh)_20260911/report_*.md
（batch1_fresh=codebuddy/v4-flash；batch2/4/5/7_fresh=zcode/GLM；batch3_fresh=
codebuddy/v4-flash；batch6_fresh=codebuddy/v4-flash；batch8_fresh=codebuddy/v4-flash。
每目录有dispatch.json记录路由身份/probe/血统，含grok两次截断与fallback lineage）。

### 4.5 3R.4证据

- Worker报告：runs/mw_protocol_v3_3r4_20260912/report_codebuddy_3r4_depgraph.md
- 主owner验证：runs/mw_protocol_v3_3r4_20260912/main_owner_combined_with_depgraph.xml（217 passed）
- 失败复核留痕：runs/mw_protocol_v3_3r4_fresh_20260912/{dispatch.json,stderr.txt}
- 复核材料（重派即用）：prompts/zcode_mw_protocol_v3_3r4_fresh_20260912.md +
  context/mw_protocol_v3_3r4_fresh_review_20260912_context.md（检查单K1-K8）
- 3R.4准备文档（绑定）：reviews/mw_protocol_v3_3r4_dependency_preparation_20260906.md

### 4.6 模板与SOP（只读）

TP-MA-07清洁版v2.0（018d28d3…756）、R03 QC表（3R.5来源）、T02-00Ⅰ期模板（3R.6候选）
路径见上一份交接§14.2，哈希未变。

### 4.7 代码地图

services/api/app/protocol_workflow/（canonical/ports/storage/events/runtime/
application/api/graph/registries/agent5/artifacts/legacy）与前端组件地图见上一份
交接§5（结构经本夜验证未变）；3R.3新增：config/.../tp_ma_07_v2/chapter_contracts/
（111）+chapter_skills/（111）+tests/fixtures/.../batch{1..8}.json+test_chapter_
batch{1..8}.py；3R.4新增：registries/dependency_graph.py+test_dependency_graph.py。

---

## 5. 恢复协议（接手后按序执行）

1. 读§4.1全局AGENTS（两份）+本文档+暂停记录+Trellis 3R.4任务记录。
2. 核对：git HEAD=84488d3、暂停记录§2哈希表、无新派发进程。
3. **重派3R.4复核**（§3.1；非GLM家族优先）。
4. 裁决→修复（如有）→组合套件→验收→commit（dependency_graph.py+
   test_dependency_graph.py+验收记录）。
5. 派发3R.4第二工作项：条件规则executor（§2.2-2）。
6. 3R.5 R03 QC（§2.2-3）→3R.6用户决策点（准备好差异/风险/推荐再问）。
7. 之后按§1.3路线连续推进；常规阶段不问用户"继续"。

## 6. 机制沉淀（直接复用）

### 6.1 批次/任务验收流水线
worker交付 → 主owner：组合套件（含全部既有批次共存）+独立组装复现（assemble CLI）
+partial/full lint+越界审计（核心与既有文件mtime）→ 非同族fresh复核（prompt带
Delegated mode前缀+检查单+输出schema，经hermes preflight）→ 缺陷按复核者最小方案
修复→组合套件复验→验收文档（缺陷/修复/证据/残余风险/范围）→ 外科手术式git add
→commit。并发纪律：≤2执行+1~2复核，分散harness/订阅，文件域互斥。

### 6.2 测试环境模板（冻结）
```
env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin \
  HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ \
  LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 \
  PYTHONPATH=tests/protocol_v3:services/api:packages:. \
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest ... \
  -q -p no:cacheprovider --tb=short --junitxml=<新文件名.xml>
```
venv=runs/mw_protocol_v3_1r_integration_20260905/venv（Python3.12.13）；勿动全局环境。

### 6.3 派发合同先例条款（写进每个新worker的context）
word_rules样式/书签从node_tree完整回填（禁空/禁不全/禁虚构交叉引用id）；新事实根
归属声明；条件规则在合同顶层（schema字段名conditional_applicability_rule_id/
triggering_fact_paths/condition/rationale/required_when_active_fact_paths），触发
事实必须声明于fact_requirements；布尔触发裸true/false；每条source负例带
expected-code子集断言（禁空真or）；合成标记显著；无外文字符混入；provenance窗口
不越node_tree范围；两段RED（缺测试文件→缺工件）；报告schema固定。

### 6.4 Harness行为速查
| harness | 报告位置 | 注意 |
|---|---|---|
| codebuddy | stream-json的result字段 | plan模式拒Bash（复核者静态核验即可）；bypassPermissions用于执行 |
| omp/pi | agent_end的assistant text | 探针回显provider/model；--thinking xhigh |
| zcode headless | 进程结束才落盘stdout | 5h配额窗口；clean env(env -i)必守 |
| grok | json的text | 后台长任务会被harness取消——复核勿用 |

## 7. 保护边界（不可违反）

live workbench（../workbench，医学监查并行开发）、8910服务、plan-upgrade-20260905、
外部SOP/模板源文件：**只读，不停不覆盖不迁移不清理**。历史runs/rows/evidence/
会话/检查点不可删除改写（清理需单独授权，本夜仅清理了源码内可再生__pycache__）。
凭证不落盘。禁止改expected/删负向fixture/xfail掩问题。产品真实模型调用仅按阶段
合同（1R.6探针已SUCCEEDED勿重复）。

## 8. 本夜执行血统（审计索引）

8 commit：b0b3663（基础设施+batch1/2）→7118329（batch3/4）→98db346（batch3修复）→
cfeebdb（batch6/7）→48f01c9（batch5+修复）→a67b9a2（batch8+全111里程碑）→
5c3ad99（batch7声明修复）→84488d3（batch8修复+3R.3收官）。
派发记录：每runs/mw_protocol_v3_*_2026091*/dispatch.json（路由/probe/时间mtime校正）。
跨会话记忆：~/.zcode/cli/memories/projects/project-851a82f3bfce61db/memory/
mw-protocol-v3-takeover-state.md。

---

**给接手者的最后一句话**：这个项目的质量门槛不在"代码能不能跑"，而在"医学内容
语义是否正确、复核是否真独立、用户是否真的少点击"。3R.3的27个缺陷全部是复核
体系拦下的——保持这个体系，先例条款只会越积越厚，交付只会越来越干净。祝顺利。
