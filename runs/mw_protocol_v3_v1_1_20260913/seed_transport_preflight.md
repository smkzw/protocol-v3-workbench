# 预填实际模型接线预案（未实施）

现有harness ArtifactRef.snippet每项8192字符，zhipu transport只拼ref/hash/snippet；已有Plan V1.3明确这不是全文读取。当前seed compiler真实CSU382319字符，未实际model调用，不能机械切碎以隐藏总context。

已只读核对安装OMP的pi-catalog/src/models.json：zhipu-coding-plan/glm-5.3-flash声明contextWindow1000000/maxTokens131072；这是本地目录声明，不是该端点最大输入实测。旧1R.6成功探针复用，不重跑。官方模型卡https://huggingface.co/zai-org/GLM-5.3-Flash 有多个评测上下文设置，不能据此冒接口保证；官方模型指南web工具不可打开，不绕行同一URL，不用第三方价格/限制代替权威。

候选最小技术路线：保留ArtifactRef与旧snippet接口兼容，为产品transport配置受限的完整制品解析回调，由应用层提供当前已绑定ref/hash的完整文本；消息包含已编译角色任务、完整选定源单元与明确输出schema。模型/worker不得拿repository或任意文件句柄。默认旧调用继续原行为；全量输入按实际字节与声明profile预算先编排，不静默截断/放宽为假通过。解析器错配或真正上下文失败走同logicalkey对账和同模型结构纠错，不自动fallback/重派。

这份预案不声明已实现。当前267源码在fresh C03/81462受审，adapter等冻结文件不能改。先准备实际消息注入测试与独立新compiler边界，审阅终态后再接参数；不得以测试fake响应冒真实预填或医学归一已通过。
