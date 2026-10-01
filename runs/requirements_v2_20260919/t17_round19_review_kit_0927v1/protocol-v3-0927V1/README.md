# protocol-v3 0927V1 审阅交付包

重点：修正重复模型/服务准备、全库测试阻塞和不稳定环境的开发方式；不降低医学文档产品门槛。

## 入口
- docs/0927V1_REVIEW.md：当前代码与交接审阅。
- docs/EFFICIENCY_PLAN.md：三车道、隔离复用、Agent闭环及计时方案。
- docs/0927V1_AGENT_NEXT.md：完整接续指令。
- docs/ACCEPTANCE_MATRIX.md：待实施验收。
- docs/EXTERNAL_RESEARCH.md：官方外部依据和适用边界。
- findings.json / source_manifest.json / verification.json：发现、来源与验证范围。

## 已运行内容
18个源码衍生隔离观察（4控制符合预期、14反例/政策检查不符合），不是18项产品PASS，也不是14独立bug。model_phase_scheduler完整源码经Git blob校验；验收门仅取相关函数加脚手架。本轮没有运行整库、真实模型、产品浏览器或Word；没有修改用户Git仓库。
新增只读JUnit诊断工具12项单测通过。它不是另一个验收门。

## 离线重现
```bash
python3 tools/run_review_probes.py
python3 -m unittest discover -s tests -v
python3 tools/junit_profile.py /absolute/path/to/existing-junit.xml --output /tmp/junit-profile.json
```
上述测试使用模拟依赖和私有临时目录；不连接模型或产品运行库。请勿将诊断生成的classname/name当作必测覆盖证明。

## 集成纪律
这是审阅和指令包，不是已经接入生产的补丁。实施应修改现有门和fixture边界，不另建通用平台。已经有的G1修复和G2部分源码保留，依据真实HEAD补验证。完整Agent指令同时在本次答复正文给出。
