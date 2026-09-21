# Study A 全文初稿决定卡闭环（2026-09-22）

## 目标与用户动作

本批次把 v0.4 的“待决定”状态接成一条可用路径：AI 给出推荐项和备选项，默认预选推荐；用户每次只确认一张决定卡；系统把确认结果写入既有 StudyDefinition 权威记录，使旧全文候选立即失效，并只重写受影响章节。没有建立第二套决定库，也没有改写不可变的旧全文工件。

## 实现结果

- 全文初稿决定项获得由 `section_id + question` 推导的稳定标识，读取时投影，不修改历史工件字节。
- 模型生成的 `fact_path` 必须来自现有可确认研究字段白名单；网关和运行器均验证该白名单。需要结构化对象的三类设计字段不能用一句推荐文字写入，明确退回研究设计界面确认。
- 标量字段按文字写入，合同声明为 `list[str]` 的字段按单项列表写入，避免确认按钮可点但后端必然 422 或静默丢值。
- API 每次只接受一个决定，复用已有的 CAS、幂等、审计和 StudyDefinition revision 机制。成功后按章节范围提交新的 durable job。
- 前端默认选中推荐项，也允许用户改选；一次点击确认后关闭旧审阅工件并监控局部重写。幂等键固定为 job、decision 与 option 的组合，未知网络结果下再次点击不会重复确认。

## 执行与复核

- 执行包：`mw_r11_decision_apply_20260922`。
- 声明主路由 `codebuddy/codebuddy-cli/deepseek-v4.1-flash:max` 未产生可用可恢复结果；runner 按 manifest 使用第一 fallback `zcode/zcode/GLM-5.3-Flash:max`，session `sess_858de745-44cd-4934-b788-c22cfafd9776`，terminal success。
- worker 找到字段形状缺陷；owner 独立复核又找到 `fact_path` 未进入模型合同的 P0，并完成同批修订。`audit-execution` 返回 `ok=true`。

## 集中验证

- 后端受影响集：111 passed。
- 前端正式清单：15 个 Vitest 文件 / 110 项，以及 48 个 Node 文件 / 65 项，均通过；最终两处收紧后 production build 再次通过，1971 modules。
- `git diff --check` 通过。
- 浏览器实测旧 v0.3 工件可继续查看，但采纳按钮禁用，符合“旧工件只读”。尚无真实 v0.4 工件，因此决定卡的真实模型渲染、一次确认和局部重写留在紧接本批的产品模型旅程验收。

## 明确边界与下一动作

本批只接受工程闭环，不接受任何医学正文。下一动作是用当前隔离运行时和产品默认 `opencode-go/deepseek-v4.1-flash:max` 生成 Study A 的真实 v0.4 工件；长轮询保持同一 durable job，不因短时无输出重派。生成后先检查三态、来源缺口、决定绑定与章节完整性，再做 fresh 医学会商；未通过前不得采纳到当前 Word。
