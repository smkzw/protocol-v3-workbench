# Protocol v3 综合AI模型选择与2+1自动降级链

## 用户决定

- 默认：`mtplx / Youssofal--Qwen3.8-Flash-Next-MTPLX-Optimized-Speed / medium`
- 第一备用：`opencode-go / deepseek-v4.1-flash / max`
- 第二备用：`cms-router / deepseek-latest-cloud / max`
- 用户可在产品设置中选择 provider、model、thinking、reasoning effort，并调整两个有序备用槽。

## 运行规则

只对429、408、500/502/503/504、传输不可达和空响应自动尝试下一条路由。合同或内容校验失败、effective模型身份不符、策略拒绝不自动换模型。每次尝试都从确定性的原始任务输入重新构建，不能把上一模型的不完整输出继续喂给下一模型。

每个AI run持久化实际provider、model、thinking、reasoning effort、fallback chain ID、父run、fallback深度和原因。全文生成额外在每个chunk及最终工件中保存路由回执；同一全文混用多条路由时，job摘要明确为`mixed`。

## 当前实测

- 隔离HTTP服务：`127.0.0.1:5304`，配置读取和状态接口均确认主路由与两个备用路由正确，响应不含密钥。
- MTPLX `127.0.0.1:11234`当前未监听；OpenCode Go在本轮真实调用中返回429；CMS Router成功承接。
- Study A：复用同一durable job的18个既有OpenCode chunk，剩余4个chunk经第二备用CMS完成；85/85目标节，最终路由摘要为`mixed`。
- Study B：22/22 chunk均经MTPLX不可达、OpenCode 429后由CMS完成；87/87目标节，21个source gap、56个partial、0个decision-required。它是可继续编辑的工作稿，并非申报就绪稿。
- Study C：22/22 chunk均经MTPLX不可达、OpenCode 429后由CMS完成；88/88目标节，31个source gap、47个partial、10个complete、0个decision-required。它同样只是可继续编辑的工作稿。

## 验证

- 受影响后端与合同回归：修复前213 passed；独立审阅修复后217 passed，18 warnings。
- 前端production build：通过，1971 modules；仅有既有chunk-size warning。
- ego(lite)：语义快照确认provider/model/thinking/reasoning effort与两个fallback槽已显示。5187当前代理旧5301，因此页面读到旧运行配置；两次截图命令超时，未形成截图证据。

## 证据

- `study_a_v10_route_receipt_reconciliation.json`
- `study_b_route_acceptance.json`
- `study_b_terminal.json`
- `study_c_route_acceptance.json`
- `study_c_terminal.json`

## 独立审阅与修复

独立只读审阅使用`codebuddy-cli/deepseek-v4.1-flash:max`同一session两轮、无fallback。首轮发现：不适用备用槽会提前终止整链、已停用连接仍会被调用。owner修复为跳过并继续后续有效路由，同时让竞品分析/方案设计/PICOS等通过统一runner的任务类型共享fallback；备用槽新增thinking模式并继承连接默认值；chunk回执增加expected/actual模型身份及端点。第二轮未发现P0/P1，并指出旧chunk应从嵌套冻结快照读取路由字段，已完成确定性修复且未重跑模型。

两个旧竞品分析实现仍直接调用provider，尚未迁入统一runner，因此暂不承诺这两个旧入口具有同一自动降级能力；这是后续P2迁移项。

## 尚未完成

- 本地MTPLX服务恢复后的真实生成质量与effective模型身份验收。
- Study C差异化真实旅程。
- WP6剩余浏览器状态、原生Microsoft Word保存重开、逐章医学判断和fresh独立审阅。
