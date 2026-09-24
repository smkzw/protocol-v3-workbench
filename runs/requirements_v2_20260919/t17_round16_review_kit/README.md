# Protocol v3 · 0924V1 review kit

固定提交：`455b37ee4530628736bd6b37b622796f13e9498f`。

先读 `docs/0924V1_REVIEW.md`，再将 `docs/0924V1_AGENT_NEXT.md` 交给实施Agent。`findings.json`区分工程缺陷、恢复语义风险和验收缺口；不是八个已端到端复现的bug。

## 验证

在有Python 3和Node.js的环境中执行：

```bash
bash tools/run_all.sh
```

仅运行临时SQLite和模拟依赖测试，不启动/停止服务，不读凭证，不改项目仓库或用户数据。需要实际产品模块/接口回归后，才能关闭相应发现。

`source_excerpts/ai_runtime_fallback_provider.py`与固定提交Git blob逐字一致。其余是标明读取窗口的原始函数体节选，导入依赖由harness提供。没有将节选测试冒充整仓编译或真实浏览器验收。

本包不提供部署补丁；它提供审阅证据、可复现小场景、具体修复路径和18项集中验收要求。
