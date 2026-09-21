# Study A v0.4 产品模型结构恢复（2026-09-22）

## 现场结论

产品模型配置与用户指定一致：`opencode-go/deepseek-v4.1-flash/max`。两次独立连通性探针均通过，返回模型身份与声明一致，因此本次故障不是鉴权缺失、模型身份漂移或总配额已耗尽。OpenCode 官方 Go 文档列出的 DeepSeek V4.1 Flash 路径也是 `https://opencode.ai/zen/go/v1/chat/completions`。

## 两次未通过的真实任务

1. `mwjob_be7f1474e35f71ce2f097902`，descriptor v4，8章一批。首答外层JSON未完成，解析器只能识别一条嵌套证据对象；同模型结构纠错随后返回空最终内容，终态失败。未生成全文工件，未采纳正文。
2. `mwjob_3c36cdf12e46da237f93799d`，descriptor v5，4章一批。空最终内容的传输重试逻辑已修复，但在既定有界尝试后仍得到`provider_response_empty`，第1/22批终态失败。未生成全文工件，未采纳正文。
3. `mwjob_96ee70138c21a86568eb3f3d`采用4章批次与65536预算后，前17批、68章成功持久化；第18批两章引用模型未返回的`span_project_center`，同模型结构纠错仍未删除，任务以unknown evidence span终态失败。前17批不受影响，尚未形成最终工件，未采纳正文。

## 根因与修订

- `_empty_completion`此前在内容读取器明确抛出“empty”时反而返回false，导致HTTP 200空最终内容不会进入已有的有界传输重试。现仅把明确的empty/no content信号识别为空响应，畸形响应仍按原错误路径处理。
- v0.4每章增加三态、决定卡和来源缺口，8章一批在`max`推理下可能在外层JSON闭合前耗尽最终内容预算。批大小已从8降为4，并写入descriptor，确保任务身份可复现。
- 4章批次在32768 token预算下仍可能只产生推理而无最终内容。全文任务预算提升为65536；模型、provider和思考强度不变。该预算写入descriptor，使后续任务拥有新的logical work key，不重放两个失败任务。
- 对完整模型输出做保守证据归一化：章节同时有有效与悬空span时仅删除悬空身份；若删除后没有任何有效证据，则清空该章正文与决定项并降为`source_gap`，明确要求“支持本章节正文的当前项目直接来源”。系统不会为模型补造证据，也不会接受无证据正文。

## 验证与下一动作

最新受影响集中测试113 passed；py_compile与`git diff --check`通过。下一动作是重启自有5299加载证据归一化，重试同一job `mwjob_96ee70138c21a86568eb3f3d`；executor应复用前17个chunk并从第18批继续。任何真实v0.4工件在fresh医学会商前不得采纳。
