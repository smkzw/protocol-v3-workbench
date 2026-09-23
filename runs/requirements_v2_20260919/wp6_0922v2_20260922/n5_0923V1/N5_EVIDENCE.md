# N5 验收证据（0923V1，2026-09-23）

环境：vite 5186 → 5301（WP6 isolated runtime，当前源码重启）；MTPLX 8002 为主模型。

## 已闭合
| 项 | 结论 | 证据 |
|---|---|---|
| 本地模型身份+质量（原#1未闭合项） | PASS | LOCAL_ENDPOINT_DISCOVERY_0923V1.json n4_real_local_quality 节：精确身份4路一致、小结构化1.08s、effort支持、截断=length、长结构化820tok/13s全字段、产品网关探针passed=true 2.6s |
| V01 三视口截图（原 PARTIAL，历史 CDP 超时） | PASS | v01_writing_desk_{1440,1920,2560}.png + v01_gapfill_review_overlay_1440.png；三视口 scrollWidth<innerWidth 无外层溢出 |
| V06 真实关键决定卡（原 PARTIAL） | PASS | 研究设计基线→4.2动态章节卡：默认预选"不适用，隐藏章节"→选第二状态 retain_not_applicable+医学依据→应用到方案→greenfield_protocol_module_resolution_applied 事件落库（01:20:58Z）→复原 not_applicable+user_override（01:27:03Z）。medical_writing_greenfield.sqlite3 两笔事件 |
| 版本门禁行为 | 观察 | 旧代码后端 api-2e70aad… 被前端正确拦截（fail-closed 生效）；用当前源码重启后过门禁 |

## 进行中/未闭合（如实记录，恢复入口）
| 项 | 状态 | 精确恢复入口 |
|---|---|---|
| A16 局部AI修订（MTPLX） | BLOCKED-前置 | 设计器单元格已选中（第7行/第1列，rail 文案已切"AI只生成该单元格替换候选"），但 提交AI修订 需要已保存工作副本；"保存工作副本"按钮 disabled，详情=方案文档与当前StudyDefinition一致；待审核1项=85章补写候选未决。恢复路径：完成候选审阅（审阅全文初稿→逐项/批量确认→采用）→保存工作副本→设计器选单元格→提交AI修订（textarea此刻才启用）→审核候选→选用写入 |
| V04 等待/失败/断网出口 | NOT_RUN | 同上工作副本前置；断网模拟=暂停8002进程或断开profile |
| A13/A14 摘要/SOA 人工修改保存重开 | NOT_RUN | 需已保存工作副本+GenOffice |
| A21 IME 组合输入 | NOT_RUN | 同上 |
| V07 全旅程点击计数 | 部分 | 本轮到设计卡应用+复原≈12 clicks/2 texts（未含完整旅程） |
| Study C 样本量 | 维持 | 52f6654 已修限定语保真；数值需统计负责人（不代选） |

## 环境备注
- 5301 已用当前源码重启（原进程为旧代码，build gate 正确拦截）；启动 env 与上一 Agent 完全一致（isolated runtime + product DB），仅补装 python3.14 缺失依赖 xlrd/python-multipart（--break-system-packages）
- vite 5186（本会话启动）→ 5301；历史 vite 5187/5188/5199 代理目标已漂移（5303/5304/5299）勿混淆
