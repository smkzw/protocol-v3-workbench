# T17 第十二轮聚合报告（COPD/MS/MDD/膝OA · 2026-09-23）

## 总览
| tester | 模型 | 场景 | EXIT | 结果 |
|---|---|---|---|---|
| 1 | muse-spark(max) | COPD/入口A | BLOCKED | 走到Step2，被 Step1/Step2 互锁 + 分诊失败 卡死 |
| 2 | gemini-3.8(high) | MS/入口B | **OK** | **全链走通**（建项→框架→PICOS→例外准入→绿地文档→引用/目录/流程图验证），初稿21批排队未等 |
| 3 | grok(high) | MDD/盲测 | BLOCKED | 走到PICOS，被分诊失败+完成第二步禁用卡死（omp提前收尾一次，重派续作） |
| 4 | deepseek(max) | 膝OA/入口B | BLOCKED | 走到例外准入→建稿，被8项干预设计阻断门+分诊重试409卡死 |

## 关键结论
1. **链路首次被证明可通**：tester2 经"零附件例外准入"走完全链主干（19点击达标），文献/目录/表目录/图目录/流程图五模块全部实测存在且联动——R5以来重点模块首次 PASS。
2. **分诊流水线仍是第一断点**（但失败形态已从"假死冻结"变为"诚实失败"）：R12 全部 chunk 死于 MTPLX 对 reasoning_effort="max" 的 HTTP 400（探测实锤），400 不在回退白名单 → 整链拒绝回退云端。F1/F2 修复生效：run 落盘诚实 partial_failed，无回退假象。
3. **修复批（8fbcaca，已推送）**：①mtplx 适配器归一化 max→xhigh（双测试锁定）②设置档 rev4=xhigh ③重试门识别"竞品分诊仅部分完成"（提取 error_summary_indicates_triage_failure 谓词，两处调用共享）。
4. **过程违规自查**：tester 测试窗口内二次重启后端未同步重启前端 → 版本门拦截 tester1（"期望api-605551e3/当前api-c2e8194"）。已按铁律补齐同步重启，R13 起测试窗口内零重启。
5. **Step1/Step2 互锁（tester1 P0-1）未修**：DB 实锤其项目 framing_draft=True 残留——事实采纳对账把已确认字段重置为待确认 → 生成草稿 → 完成第二步被"返回第一步"咬住。属 R10 门禁不收敛家族，需交互复现安全修复，随 R13 验证其是否仍复现（分诊修好后循环压力源可能消失）。

## tester2 提出的 P1（下批候选）
- 事实采集校验错误直出内部字段路径（framing.product_profile.confirmed_facts.treatment_interval）
- 流程图"插入方案"因 Assembly Plan 版本未自动刷新而报 stale
- 绿地文档"恢复权威源基线"直出 rebind 技术限制

## 非缺陷（已核实）
- PMID 16481652 = Chin-Hong "Newly diagnosed HIV infection"（PubMed eutils 直查确认）——tester3 误以为是 STAR*D，导入机制无错
- 项目下拉含 13 项 = 出厂 demo 种子（保留 demo 是设计要求），prompt 措辞已澄清
- 开局 503 monitoring_principal_unavailable = 已知宿主认证缝隙

## R13 派发决定
四场景全量重派（锁定编队不变）：tester2 的 OK 是经例外放行取得的，分诊修复后需验证正常路径；另三场景验证本批修复。prompt 增加"AI 步骤可能 10-40 分钟，禁止提前收尾"条款。
