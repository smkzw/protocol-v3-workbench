# Study A v0.4 产品模型结构恢复（2026-09-22）

## 现场结论

产品模型配置与用户指定一致：`opencode-go/deepseek-v4.1-flash/max`。两次独立连通性探针均通过，返回模型身份与声明一致，因此本次故障不是鉴权缺失、模型身份漂移或总配额已耗尽。OpenCode 官方 Go 文档列出的 DeepSeek V4.1 Flash 路径也是 `https://opencode.ai/zen/go/v1/chat/completions`。

## 两次未通过的真实任务

1. `mwjob_be7f1474e35f71ce2f097902`，descriptor v4，8章一批。首答外层JSON未完成，解析器只能识别一条嵌套证据对象；同模型结构纠错随后返回空最终内容，终态失败。未生成全文工件，未采纳正文。
2. `mwjob_3c36cdf12e46da237f93799d`，descriptor v5，4章一批。空最终内容的传输重试逻辑已修复，但在既定有界尝试后仍得到`provider_response_empty`，第1/22批终态失败。未生成全文工件，未采纳正文。

## 根因与修订

- `_empty_completion`此前在内容读取器明确抛出“empty”时反而返回false，导致HTTP 200空最终内容不会进入已有的有界传输重试。现仅把明确的empty/no content信号识别为空响应，畸形响应仍按原错误路径处理。
- v0.4每章增加三态、决定卡和来源缺口，8章一批在`max`推理下可能在外层JSON闭合前耗尽最终内容预算。批大小已从8降为4，并写入descriptor，确保任务身份可复现。
- 4章批次在32768 token预算下仍可能只产生推理而无最终内容。全文任务预算提升为65536；模型、provider和思考强度不变。该预算写入descriptor，使后续任务拥有新的logical work key，不重放两个失败任务。

## 验证与下一动作

受影响集中测试112 passed；py_compile与`git diff --check`通过。下一动作是重启自有5299加载代码，重新做一次身份探针，并创建新的descriptor任务。继续使用同一job长轮询；若provider明确拒绝65536则按HTTP错误修订，若成功进入第2批则保持运行。任何真实v0.4工件在fresh医学会商前不得采纳。
