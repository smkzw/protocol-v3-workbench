# 外部研究：对本仓库有效的做法及边界
检索/核对日期：2026-09-27。以下是外部官方资料，不是仓库已经实施的能力。此处的推荐是结合本仓库问题的工程判断，不是厂商保证。

## R1 OpenAI — Harness engineering: leveraging Codex in an agent-first world
2026-02-11。官方经验强调应用和可观测性按worktree隔离，让Agent能访问真实运行证据；AGENTS作为短索引，深入规范在版本化文档中。适用本项目：减少共享运行库/服务争用和长交接叠加，规则落实到边界测试。不要照搬文中较宽松合并策略，更不能把其速度估算当成本项目收益。
```text
https://openai.com/index/harness-engineering/
```
## R2 Anthropic — Effective harnesses for long-running agents
2025-11-26。区分最初环境构建与后续增量开发，并留下足够、清晰的接续状态。适用本项目：bootstrap做成可重复使用的步骤，接续者定位当前业务进度而不是每次重新建环境。保留真实功能验证，不能仅凭服务HTTP成功宣称功能完成。
```text
https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
```
## R3 pytest — Flaky tests
官方说明将未充分隔离的系统状态、顺序依赖和全局状态列为不稳定来源。适用本项目：先修私有DB/env/线程/时钟和污染前置，减少逐次登记新指纹；盲加并行可能放大问题。隔离债务不是删除业务断言或永久KNOWN。
```text
https://docs.pytest.org/en/stable/explanation/flaky.html
https://docs.pytest.org/en/stable/how-to/tmp_path.html
https://docs.pytest.org/en/stable/how-to/monkeypatch.html
```
## R4 Playwright — Web server / Mock APIs / Best practices
官方支持复用已有测试服务和外部请求的受控响应/HAR回放，以及浏览器隔离与可诊断跟踪。适用本项目：真实前后端和保存逻辑保持不变，仅替换明确的模型/注册源边界；通过身份检查后复用服务。reuseExistingServer本身不验证代码或数据根，需现有runtime身份机制补足；不得回收不属于测试的服务。
```text
https://playwright.dev/docs/test-webserver
https://playwright.dev/docs/mock
https://playwright.dev/docs/best-practices
```
## R5 uv — Caching
官方有依赖缓存与按输入变化处理的机制。适用本项目：锁文件未变时复用既有环境、避免重复解析安装。当前requirements/venv可用即可继续，不为追求“新工具”强制迁移，也不新增镜像和注册平台。
```text
https://docs.astral.sh/uv/concepts/cache/
```

## 综合判断
这些资料共同支持“短、可重复、隔离、证据可复用”的反馈闭环，并不支持每次小改动先加载全部模型或清点一万项历史测试。本轮三车道是本项目的实施建议；回放通过不等于模型质量通过；快速测试通过不等于医学方案可正式发布。
