# NEW-39 二分定位任务单（下周期第一批首件·移交规格增补）

- 出处：第10轮末修订（终轮）唯一增补；A席五链对照已锁回归窗口 r2→r5 构建
- 窗口 diff 实测（本会话复核）：`git diff 2ca9ba8c..HEAD --stat` 三文件合计
  +509/−44（authoring_journey.py 20、full_draft.py +471、repository.py 62）
- 窗口内提交：e59fe4ac（R2末修订批：取消三件套/第二步守卫/禁语/剂量一致性门）、
  46fa452c（R4+R5）＋ 未提交工作树（r6-r10 修订批：采纳CAS重锚/守卫幂等/
  统计装配门/重导出补门/NEW-32元数据等）

## 二分臂（按批回放+A席诊断同跑）

1. **B1 守卫完整性统一臂**（首嫌）：full_draft.py:884-890
   `apply_full_draft_content_guards` 统一入口（第3轮'守卫完整性'批）改变了
   逐路径守卫行为面（含批注追加与候选否决）——回放该 hunk 前/后两态，
   跑 fact→assembly 链看'采用≠装配'是否随 hunk 翻转。
2. **B2 采纳CAS重锚臂**（r6 修订）：adopt 循环删快照版本硬门——回放前后。
3. **B3 统计装配/守卫幂等臂**（r6-r10 工作树）：statistics/样本量/剂量守卫
   的文本改写与幂等返回。
4. **B4 authoring_journey 20行臂**：含 P1-53 修订门+NEW-18 枚举+sample_size
   fingerprint 持久化（framing/picos 提交路径面）。

## 诊断（A席第6轮方案，至今未执行，与二分同跑）

装配层（apply_corpus_projection 族）打印事实源读取清单：
- 读取路径（journey payload / fact conversation / study_definition 各自的
  字段映射点）逐项打点；
- 采用事件后到投影调用前的载荷快照 diff；
- 输出与 UI 已采用 4 项（给药途径/暴露范围/剂型/研究分期相关）逐一对照，
  定位'哪一层读的是另一份事实源'。

## 关联缺陷归并提示

- NEW-49（radio 首次点击装配层不接收）：随本任务同修（同邻域）；
- NEW-45（解析重置已采用卡）：S2 单一事实源同批；
- NEW-24/1④/19：同一状态机族，本任务定位后并入 M1-2/M1-3 修复。
