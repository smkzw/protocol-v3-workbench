# E04 实现报告 — ProtocolSourceIntake

本次继续会话声明：由 `openai-codex/gpt-5.6-luna` fallback 执行。能力限制：未启用浏览器/原生渲染验收，因此不声称视觉通过；未调用产品模型、监听服务或后端写入路径。仓库/技能目录未发现精确命名的 `kangzhe-web-visual-design`，已读取并采用可用的 `kangzhe-design` ROUTER/core 设计约束。Owner 负责整合与最终接受，本报告不代表最终验收。

## 边界

仅涉及以下三个组件文件；未修改 App.jsx、client、包/配置、backend、Trellis 或 monitoring 组件：

- `frontend/src/features/medical-writing/protocol-workbench/ProtocolSourceIntake.jsx`
- `frontend/src/features/medical-writing/protocol-workbench/ProtocolSourceIntake.css`
- `frontend/src/features/medical-writing/protocol-workbench/ProtocolSourceIntake.test.jsx`

精确来源路径仍由注入的 `createProtocolWorkspaceApi` 形状提供：`listSources`、`importSource`、`correctSourceMetadata`、`sourceDownloadUrl`。

## 交付文件

| 文件 | SHA-256 | 行数 |
| --- | --- | ---: |
| `ProtocolSourceIntake.jsx` | `e0dbc8f879acd876aff90c0cb76cce1c277068ca5712f984207f0089ddfd05c9` | 738 |
| `ProtocolSourceIntake.css` | `4e362d2110e5827c48277025ef3949b88866600de9b000dda0f3613ef28b3d90` | 368 |
| `ProtocolSourceIntake.test.jsx` | `1496fa5db29f702a37a3efeeebcc9f51362243e785ccd20e6b4320b829ce4aa3` | 521 |

## 证据

红测（组件缺失）：

- `runs/execution/mw_protocol_v3_v1_1_source_ui_20260913/source_intake_ui_red.log`
- 组件实现前同一 Vitest 路径因 `./ProtocolSourceIntake` 无法解析而退出 1，未执行测试。

绿测（实现及行为回归）：

```text
npm exec -- vitest run --config vite.config.mjs --environment jsdom \
  src/features/medical-writing/protocol-workbench/ProtocolSourceIntake.test.jsx
```

- `source_intake_ui_green.log`
- exit 0；`Test Files 1 passed (1)`；`Tests 16 passed (16)`。

相邻传输合同：

```text
node --test src/features/medical-writing/protocol-workbench/protocolSourceApi.test.mjs
```

- 4 subtests passed；覆盖 PATCH 元数据、原始文件字节及 multipart boundary、服务端冲突说明、当前来源下载路径。

辅助检查：

- `node tests/protocol_v3_test_inventory.mjs --check`：51 tests discovered，coverage complete，duplicates 0，unknown runners 0。
- `npm exec -- esbuild src/features/medical-writing/protocol-workbench/ProtocolSourceIntake.jsx --loader:.jsx=jsx --format=esm --log-level=error`：通过。

## 行为覆盖

- 初始资料列表、空状态、中文类别/版本/地区及当前资料原文件下载。
- 后端七个 `SourceRole` 的中文可选项；不显示技术枚举作为用户文案。
- DOCX 暂存、显式类别选择、原始 `File`/字节/文件名 logical key 及未推断版本/地区。
- 非 DOCX 拒绝且不发导入请求。
- PATCH 更正携带完整当前类别、版本、地区，不重新上传；冲突保留旧卡片并展示服务端 `message`/`next_step`。
- replay 使用 `current` 身份，不使用历史 receipt；更正后保留用户取消纳入的选择。
- brief 由父级控制并跨资料刷新保留；无 `onPrepare` 时不渲染准备动作。
- 项目切换、卸载及延迟 list/upload 响应隔离；忙状态不会污染新项目。
- 缺少 `current` 身份时不声称保存成功，并先单次刷新资料列表；无自动重复 POST/轮询。
- 手动读取重试，不循环；无医学准入、质量徽章、模型就绪或审批勾选。

## Owner 集成 props

```jsx
<ProtocolSourceIntake
  projectId={projectId}
  api={createProtocolWorkspaceApi(...)}
  brief={brief}
  onBriefChange={(next) => setBrief(next)}
  onPrepare={({ userBrief, sourceArtifactIds }) => { /* owner flow */ }}
/>
```

`onPrepare` 可省略；提供时收到当前资料中仍勾选的 `source_artifact_id` 数组和原始 `brief`。本组件不触发下游生成、不作医学确认。

## 未验证项

- 未运行浏览器截图、原生渲染或实际 mounted API/真实 DOCX 上传；jsdom/transport 检查不能替代这些验收。
- 未运行无关全量测试套件。
- Owner 仍需在实际页面确认组件挂载点、宿主布局与最终视觉层次。
