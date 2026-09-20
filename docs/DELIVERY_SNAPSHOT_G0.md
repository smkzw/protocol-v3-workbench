# G0 交付快照（整改指令响应，2026-09-20）

审计对象：远端 e3690de59e5e3808b751c8c23106a6ad3c41f596（审计包 protocol-v3-audit-current）。
本快照为实施 Agent 的真实 checkout 现状。

```text
WORKBENCH_HEAD=d83255f03992965e3d67160b23ddf16e27f2ca40
WORKBENCH_DIRTY_PATCH_SHA256=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  （排除 runs/ 运行时数据后无未提交源码改动；git status 仅剩 6 条 runs/ 运行时产物）
REPORTED_FOUR_COMMIT_SHAS=deab516 87fc1e8 451e7fe 4b52bbb
  （另有 d0b668d、d83255f 两个文档/测试轮次提交；全部位于审计基线 e3690de 之后）
GENOFFICE_HEAD=316ded6f0a39235fec8d21c068d8a0766ee6172b
GENOFFICE_DIRTY_PATCH_SHA256=be4f18c27a734ce224b086be7b3ca0d3053a65dca780285aead0c6ac0f07e40b
  （dirty 内容：package-lock.json 变更 + 未跟踪的 packages/docx-engine/tests/protocol-feasibility.spike.test.ts 可行性探针，无产品源码改动）
DEPENDENCY_LOCK_HASHES=frontend/package-lock.json sha256:83378e52cc1fdf764ea5d34c418aa0e7da2c4bdf1b099ec85e8feaadca1b2134
  后端运行环境：runs/mw_protocol_v3_1r_integration_20260905/venv（Python 3.12.13；fastapi 0.128.8；pydantic 2.13.4）
RUNTIME_ASSET_MANIFEST_HASH=见下"运行时资产"（GenOffice 渲染器安装于 frontend/public/genoffice/，由 scripts/qc/protocol_v3/build_genoffice_renderer.sh 从 316ded6f 构建 + bridge-shim.js 注入；bridge-shim.js 在 87fc1e8 中修复）
MIGRATION_VERSION=workbench_runtime.sqlite3 schema_version=2；e2e_test.sqlite（protocol workflow）schema_version=1
TEST_DATABASE_SCOPE=e2e_test.sqlite + e2e_runtime/*.sqlite3（均为 runs/mw_protocol_v3_unified_tests_20260919/ 下的独立测试运行时；不触碰任何生产库）
```

## 与审计基线 e3690de 的差异（审计发现的新旧核验状态）

审计基于 e3690de；其后本地已推进 6 个提交。逐项核验结论在整改过程中以
`FINDING_ID + ACTUAL_RUNTIME_BUILD` 格式记录（见各修复提交报告）：

- F02（桥接假成功/启动文档未消费）：**部分已修**——87fc1e8 已把 docUrl 作为
  consumePendingOpenDocx 的一次性 pending open 投递（浏览器实测渲染成功）；
  Proxy 对未知方法返回 asyncOk 的假成功面与本轮整改一并处理。
- F01/F03/F04/F05（Office 当前稿闭环/并发基线/研究版本误贴）：**未修**，G1 优先。
- F06（核对未绑定当前研究）：**未修**，G2。
- F07/F08（surgical 块内边界/冻结意图恢复）：**未修**，G3。
- F09-F13：**未修**，G4。
- F14（双入口同版本闭环证据）：部分证据在本机（场景1 双链），但未绑定运行时
  构建身份与产物哈希，G5 补齐。
- F15/F16（构建可复现/导出临时路径项目隔离）：G6。

## 运行时资产清单

- 前端：vite dev（127.0.0.1:5176，VITE_API_PROXY_TARGET=http://127.0.0.1:5275）
- 后端：uvicorn services.api.app.main:app（127.0.0.1:5275），运行环境与契约见
  checkpoint 2026-09-20 条目（WORKBENCH_RUNTIME_DIR=e2e_runtime 等）
- GenOffice 渲染器：frontend/public/genoffice/（build_genoffice_renderer.sh 产物 +
  bridge-shim.js 87fc1e8 版）
