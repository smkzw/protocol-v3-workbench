# T17 第十一轮聚合报告（COPD/MS/MDD/膝OA 四场景）

## 测试者结果总览
| tester | 模型(thinking) | 场景/入口 | EXIT | 核心发现 |
|---|---|---|---|---|
| tester1 | muse-spark(max) | COPD/A | BLOCKED | 竞品流水线回退P0-2 + 夹具解析失败P0-1 |
| tester2 | gemini(high) | MS/B | OK(产品FAILED) | 7章/104缺口、无文献/目录/流程图 |
| tester3 | grok(high) | MDD/盲测 | BLOCKED | 竞品分诊回退 + 0/111章 |
| tester4 | deepseek(max) | 膝OA/B | 静默死亡 | 等待竞品分诊中进程消失 |

## P0 汇总
- **P0-A 竞品分诊流水线 MTPLX 空响应→冻结/回退**：全部测试者同触。根因=MTPLX本地模型对分诊chunk返回空响应(provider_response_empty)→chunk标记FAILED→流水线不重试也不fallback→framing阶段不可穿透。修复方向：竞品分诊chunk执行时确保fallback chain正确引用云端provider；或直接在chunk失败后触发durable retry并切换provider
- **P0-B 入口A夹具解析**：synthetic-reference.docx上传后卡在"正在准备文档内容"（与tester3 report中的legacy导入路径一致，后端125ms即401）

## P1 汇总（跨测试者去重）
- 文献引用/目录/流程图三模块全部缺失或不可达（一致性发现）
- 给药确认卡死路（无作答控件）
- 内部标识符（chapter-sources:hash）UI直出
- "确认以上全部N项"需先点"更新研究与文档状态"
- 手动编辑工作副本时 textarea 被折叠面板遮挡
- 章节标题模板残留

## A16 digest v4 修复验证
全屏编辑正文→AI修订指令→提交→云端opencode-go调用→4互异候选→选用写入→WC rev 0→1→重载持久化 ✓
digest v4 lineage normalization（排除anchor_path/block_hash/source_kind执行期回填字段）有效。

## V04 失败/断网出口
云端死端点场景→任务failed→UI显示类型化错误→出口可见可重试不损坏状态 ✓

## A13 手动编辑保存重开
全屏编辑正文手动键盘输入→保存→版本2已保存→重载持久化验证 ✓

## tester4 事件
tester4(deepseek-v4.1-flash max, 膝OA) 进程在竞品分诊等待期间静默退出（90B "等待竞品分诊完成中"），无EXIT标记。未重派。
