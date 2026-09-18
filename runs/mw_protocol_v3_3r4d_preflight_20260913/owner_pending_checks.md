# D owner验收准备（执行worker终态后才运行）

当前正在运行的唯一D句柄82000；不得因慢重派，不修改worker源/测试。

已准备owner_adoption_cases.py，使用真实mounted API及临时SQLite；必须在worker terminal后核对helper接口，再以tests/protocol_v3/integration加入PYTHONPATH执行，并绑定执行前后源hash。三个独立触发是：历史精确回放不依赖后来当前模板文件、同一operation key改变decision/revision不能二次采用、条件从true到false时不能忽略未改动的残留参数。还需证明确有可执行的显式解决办法，不能把用户锁在永远无法调整的状态。此文件是验收合同，不是进行中实现的失败结论。

新worker首轮结果→owner定向反例及源核对→必要时同session定向修复（扣除已用预算）→source冻结→fresh conference→owner整合Trellis，连续进入3R5A和V1。C03当前完整off_peak链的主路由为ZCode GLM-5.3:max；派发时重读global AGENTS/live manifest和时段，不能把现在预检当正式派发。已知global guard导入故障仍不冒称audit通过，不修改global配置。

fresh reviewer的输入应为冻结原源/实现/测试和Plan/用户合同，不以worker自评或owner说服性结论替代来源。关注A类型/alias、B三态与部分保存、C标签传播、D实际事务/操作身份/重放/当前确认/恢复的一致性；已接受的B语义若源hash未变不机械重跑所有医学窗口。整稿应用验收已显式继承V1.3/V1.4，不得把D事实事件当成文档采用完成。UI/模型/Word未实际运行仍分别列未验。
