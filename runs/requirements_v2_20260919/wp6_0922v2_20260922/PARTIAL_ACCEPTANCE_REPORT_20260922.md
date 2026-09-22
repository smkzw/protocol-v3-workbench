# Protocol v3 0922V2 WP6 暂停时验收报告

时间：2026-09-22 17:30 +0800  
源码基线：`acf6d8341563d56946f934dfdac65c76997e36e3` 加当前待提交变更  
范围：WP1–WP5实现后的构建、类型检查和自动回归。用户要求在完成当前回归后无损暂停，因此本轮未启动新的隔离服务、真实产品模型、ego(lite)或Microsoft Word操作。

## 已完成的决定性检查

- 工作台生产构建：1971 modules，PASS。
- 前端权威清单：15个Vitest文件/110项；48个Node文件/66项，PASS。
- Protocol v3后端：2601 passed、1个Python 3.14未来行为warning，PASS。
- GenOffice：docx-engine与docs TypeScript检查PASS；docx-engine 1398 passed、1 skipped；renderer生产构建483 modules，PASS。
- 两库`git diff --check`：PASS。
- renderer可重建包：`../wp5_renderer_repro_20260922/manifest.json`，包含base、tracked patch、未跟踪源码、构建命令和42个bundle文件hash。

## A01–A26

当前源码变化后尚未从真实App重新走完整用户旅程。以下均保持`NOT_RUN`，避免以自动测试或9月21日旧截图替代0922V2产品验收。

|ID|状态|已有部分证据|恢复后仍需完成|
|---|---|---|---|
|A01|NOT_RUN|双入口薄适配源码与回归通过|真实入口A旅程|
|A02|NOT_RUN|authoring handoff源码与回归通过|真实入口B旅程|
|A03|NOT_RUN|无附件路径保留|浏览器零附件建项|
|A04|NOT_RUN|正文+缺口合同已实现|真实稿编辑下载|
|A05|NOT_RUN|关键未定仍为决定项|实际推荐卡与写入|
|A06|NOT_RUN|未知适用性不自动删除|三研究抽样|
|A07|NOT_RUN|项目/任务身份绑定回归通过|跨研究真实隔离|
|A08|NOT_RUN|来源角色与SOP复用实现|真实输入包医学核对|
|A09|NOT_RUN|保存与核对解耦源码完成|真实DOCX修改|
|A10|NOT_RUN|失败不挡保存合同存在|故障注入+浏览器|
|A11|NOT_RUN|条件写与恢复回归通过|双窗口实际冲突|
|A12|NOT_RUN|同operation恢复回归通过|丢回执浏览器路径|
|A13|NOT_RUN|摘要作为真实对象保留|Word手改保存重开|
|A14|NOT_RUN|SOA对象所有权未改|Word表格实际修改|
|A15|NOT_RUN|局部AI结构签名实现|iframe真实选区|
|A16|NOT_RUN|局部续写范围实现|模型+当前Word组合|
|A17|NOT_RUN|影响范围计算保留|事实变化真实同步|
|A18|NOT_RUN|表格语义映射保留|首块表格对象核对|
|A19|NOT_RUN|否定/量级只作线索|真实DOCX反例|
|A20|NOT_RUN|来源/工件hash冻结|跨批资料变版实际恢复|
|A21|NOT_RUN|renderer构建通过|真实输入、IME、格式|
|A22|NOT_RUN|CMS引用源码与引擎回归通过|实际增删移动+Word|
|A23|NOT_RUN|工作稿与正式状态分离|端到端状态显示|
|A24|NOT_RUN|历史与pending保护回归通过|刷新/切研究/IME|
|A25|NOT_RUN|项目键与CAS存在|两个项目并行实测|
|A26|NOT_RUN|历史事件不改写|保留证据的新版本修复实测|

## V01–V08

|ID|状态|说明|
|---|---|---|
|V01|NOT_RUN|需当前bundle在1440/1920/2560截图与DOM尺寸|
|V02|NOT_RUN|需computed字号实测|
|V03|NOT_RUN|需长中英文、长研究名和10+问题实测|
|V04|NOT_RUN|需等待/失败/缺资料/候选/冲突全状态|
|V05|NOT_RUN|需验证专注模式不重建iframe且保留dirty/选区|
|V06|NOT_RUN|需验证推荐预选、第二选项真实持久化|
|V07|NOT_RUN|需逐步计数点击和自由输入|
|V08|NOT_RUN|需保存、下载、重开、历史不替换head|

## B01–B12

|ID|状态|本轮已完成的部分|未完成层|
|---|---|---|---|
|B01|NOT_RUN|混合正文/缺口合同与采用代码|SQLite/API/浏览器|
|B02|NOT_RUN|authoring bridge和candidate adapter|真实双入口+模型|
|B03|NOT_RUN|同operation恢复及长轮询代码|SQLite故障注入+浏览器|
|B04|NOT_RUN|1–6项原子确认和局部重写|API/模型/浏览器|
|B05|NOT_RUN|CAS与候选原子激活|制品失败/版本冲突|
|B06|NOT_RUN|ICE同事件语义比较代码|离线病例+独立医学|
|B07|NOT_RUN|核对v2与not_checked代码|当前DOCX反例|
|B08|NOT_RUN|冻结manifest和SOP项目确认|真实输入包/API/模型|
|B09|NOT_RUN|bridge 5项Node反例PASS、服务合同回归PASS|实际SQLite+浏览器|
|B10|NOT_RUN|locator统一helper与2000上限回归PASS|真实85节初次/复用/恢复|
|B11|NOT_RUN|选区Slice/格式签名与撤销源码、类型检查PASS|浏览器对象/XML|
|B12|NOT_RUN|引文原位/样式源码、renderer重建与引擎回归PASS|浏览器+原生Word|

## 结论

WP1–WP5已达到“源码实现完成、自动回归通过”。Protocol v3整体目标仍未完成，不能宣称申报就绪。恢复后从真实SQLite/HTTP与ego(lite)开始，再做实际产品模型、当前Word、原生Word和冻结产物独立医学/工程会商。
