# V1.1 资料整理应用限定工程审阅

当前仍in_progress，未关闭V1.1或完整产品。当前设计/Plan显式修订与最新用户Goal优先，独立报告是证据而非新指令。

## 独立挑战与owner裁定
首轮79056，GLM-5.3:max，session sess_8fbedfac-6412-46c4-ab27-7b9cfd0f9de4，834.375s；后续84612同会话806.323s/returncode0，同模型max，无额外独立模型意见。后续25文件hash owner复验零漂移后解除冻结。原报告及快照均保留在runs/mw_protocol_v3_v1_1_application_review_20260913/owner_followup_01。

- D1已修：correction run ID访问主任务GET返回中文404，不再500。
- R1已修：原始请求持久身份、只读recover、queued按原材料恢复，已完成与unknown不重派。真实SQLite与前端重开测试支持；不是供应商原生会话恢复。
- R2撤回：SourceIdentityService采用在SQLite BEGIN IMMEDIATE内，独立store并发写受相同事务串行化，4线程/4store保留全部修订。无需另造锁。
- D2父容器同步ref负责prepare去重；R3线程池容量属于未实测的个人系统负载事项，未据假设增加executor。
- 健康进度投影复用OS所有权；独立跨进程检查确认活任务running、死owner blocked，不自动重派。当前未有HTTP人工对账入口，明确未完成。
- N1后续新发现：首次查找后另一compiler包先提交同请求会root conflict500。Owner在seed start捕获该唯一冲突，复核已绑定原始请求身份并返回首次包；Graph原始禁止重绑定不改。真实SQLite可控竞态红测→11定向通过。此小修为owner确定性验证，不冒称纳入此前25文件独立hash。

## 实际页面证据
浏览器真实React组件、Source API、SQLite、Graph/Harness，回复为合成HTTP。批量两DOCX、类别更正、完整说明提交、刷新结果恢复已直接操作；两个不同请求恰有两次合成生成，刷新无新增调用。390px窄屏无水平溢出；说明/按钮14、正文16、辅助12px。完整App主入口构建通过，非真实全导航验收。
Owner另发现排除勾选刷新丢失：先保存真实浏览器复现和失败测试，再以同项目恢复资料logical key修正；29前端测试通过，浏览器刷新仍排除同资料。这个修改也在独立冻结解除之后，由owner行为验证。

## 尚未通过范围
真实模型完整参考输入正在单独进行，见real_reference_intake；此文件不预判其结果。无确认建议、全部适用章节、编辑保存或原生Word验收；不承诺≤20全路径点击已达标。医学事实未采用、申报适用性未批准。缺失字段长串文字需替换为AI推荐/最少问题，自动执行与继续按钮提示需优化。

验证记录：runs/mw_protocol_v3_v1_1_20260913/ 下intake_runtime_regression44、intake_mount_regression10、seed_recover_client_green5、source_selection_recovery_check29、seed_start_race_check11，计数有重叠，不相加为全量覆盖。独立39 scratch checks单列，不能替代产品验收。

## 后续真实参考调用结果（限定范围更新）
84449实际产品运行已终态ready_for_review，无纠错，原始输入514273byte、输出15867字符；模型/供应商实际回执匹配glm-5.3-flash/zhipu-coding-plan，requested max，effective effort未报告。8字段24条候选49处引用字符串/定位通过，canonical空且全部reference_only。重开相同结果，事件11→11，凭证解析0、新调用0。原文语义充分性正在独立19126审阅，不能把这些数字作为科学验收。readonly viewer实际产品组件已显示结果并展开源引文；其测试bootstrap注入已知run ID，不证明跨浏览器自动发现任务。
