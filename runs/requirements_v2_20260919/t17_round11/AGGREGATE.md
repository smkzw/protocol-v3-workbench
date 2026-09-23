# T17 第十一轮聚合（4场景：COPD/MS/MDD/膝OA）

## 测试者结果
| tester | 模型 | 场景/入口 | EXIT | 核心发现 |
|---|---|---|---|---|
| tester1 | muse-spark(max) | COPD/A | BLOCKED | 竞品流水线回退P0-2 + 夹具解析失败P0-1 |
| tester2 | gemini-3.8-flash(high) | MS/B | OK(产品FAILED) | 7章/104缺口、无文献/目录/流程图 |
| tester3 | grok-4.6(high) | MDD/盲测 | BLOCKED | 竞品分诊回退 + 0/111章 |
| tester4 | deepseek-v4.1(max) | 膝OA/B | 静默死亡 | 等待竞品分诊中进程消失 |

## P0 汇总
- **P0-A 竞品分诊流水线 MTPLX 空响应→冻结/回退**：所有测试者同触。根因=MTPLX speed模型对分诊chunk返回空响应→quality gate正确拦截→但流水线不重试也不fallback→回退冻结→后续全链阻断
- **P0-B 入口A夹具解析失败**：tester1上传synthetic-reference.docx→13分钟无响应（与第十轮tester1同因）

## P1 汇总
- 文献引用/目录/流程图三模块全部缺失或不可达（四测试者一致）
- 给药确认卡死路（无作答控件）——与前几轮一致
- 内部标识符（chapter-sources:hash）UI直出

## V04 断网/失败出口验证
云端死端点→任务failed→UI显示类型化错误（AiExecutionPolicyDenied + base URL must be）→出口可见、可重试、不损坏状态 ✓

## A13 手动编辑保存重开
全屏编辑正文手动键盘输入→保存→版本2→重载持久化验证 ✓（a13_manual_edit_persisted.png）

## 修复状态
- digest v4 lineage normalization（排除 anchor_path/block_hash/source_kind）已实装并实证
- 修订任务云端路由已实装并实证（opencode-go completed + 4互异候选）
- 下批需修：竞品分诊 MTPLX 空响应的 fallback 路径

## 追加（09-23 17:2x）：tester2(gemini MS) 完整报告到手
EXIT=OK，产品FAILED——核心发现：
1. 文献引用部分存在（库层可用）但文内层不可达（编辑器从未出现→编号/联动/回跳均未观察到）
2. 目录与图表缺失（导出/预览不可达）
3. 流程图缺失
4. 全屏正文编辑器中手动编辑成功（含格式工具栏、交叉引用、表格）
5. 反拟合23项全合规、MS场景隔离严密
6. 新P1：文献库导入时混合来源（GOLD题名+NEJM DOI）未作冲突提示即入库
7. 已知限制：protocol_full_draft 路由白名单硬编码限制必须使用 127.0.0.1:8002/v1 mtplx 路由

**A16 digest v4 验证结论**：全屏编辑正文→AI修订指令→提交→云端opencode-go调用→4互异候选→选用写入→WC rev 0→1→重载持久化 ✓ 全链在digest v4下已打通。
