# 前端预清理批 r2（用户指令20261003b 复验 + 20261008a 尺）留证

- 执行：实现师（fe_cleanup 批二，2026-10-08）
- 现场：HEAD 之后的工作树改动（未提交）；后端 5301 为旧进程（构建横幅如实提示，属产品守卫正常工作）
- 反例先红：`tests/test_frontend_precleanup_r2.py` 9 测先红（8+1 扩充）后绿
- FAST 自查命令与输出见文末

## ① 设计语言对齐要点（kangzhe-design SKILL.md 6.1）

本批遵循：功能优先、美观统一其次、不追求 100% 遵循；不动业务布局结构，
只清人话化与换行卫生；无花哨彩条（未新增任何装饰）。

## ② 满页宽实测（真机探针，1728×1031 视口，Camoufox）

9 个导航页逐页测量：主内容区最宽顶级子元素宽度 = 主内容区宽度的 **98%**
（1548/1548 布耳；医学写作 1628/1664）。CSS 全量扫描：**不存在**主内容区
全局 max-width 约束（`.page` 仅 padding:18px）；≥640px 的固定宽度声明
仅 5 处，均为文本可读性行宽（如 `.monitoring-scope-summary-head p`
740px）或文档预览（`.pcd-preview` 900px，A4 视感）——不属于"容器不满宽"。
结论：宽向已满，无需放宽；窄帽保留（拆掉反而伤害长文案可读性）。
"大片留白"属空态页垂直密度问题，归 fe_deep_align 逐页走查批处理。

## ③ 工程化语言清扫（4 处，反例先红）

| 位置 | 修前（真机截图实证） | 修后 |
|---|---|---|
| 监控读取阻断面板（App.jsx MonitoringReadUnavailable） | `HTTP 503 · code=monitoring_principal_unavailable` 直出 | 可见文本只剩人话提示；技术串收进 title 悬浮（`技术详情已收进悬浮提示；反馈问题时可提供。`） |
| 原始监读错误提示（App.jsx setRawMonitoringError） | `标题：人话（HTTP 503 · code=xxx）` | 去掉技术串拼接 |
| 构建漂移横幅（runtimeReadiness.js） | `前后端构建不一致（当前源码树期望 api-ec75…，运行中后端 api-b88…）——请重启本子系统后端(5301)…` | `前后端构建不一致：页面已更新，运行中的服务还是旧版本——请重启本子系统后端服务后刷新页面`（哈希与端口号不再直出；'构建不一致'字样保留，既有 vitest 契约不受影响） |
| 顶栏 AI 胶囊（App.jsx AiGatewayPanel） | `可运行 AI 设置 · mtplx · mtplx-flash-next-optimized-speed` | `可运行 AI 设置`（非压缩态 `AI 接入状态`）；provider/model 细节进 title 与设置弹窗 |
| 写作页保存状态（App.jsx） | `绿地候选基线`（greenfield 工程术语） | `新建方案候选基线`；按钮提示同步人话化 |

## ④ 不和谐换行修复（4 处，反例先红）

| 位置 | 修前（1440 视口实证） | 修后 |
|---|---|---|
| 顶栏指标胶囊 `.metric` | `未读决/策`、`高风险开/放`、`待交/接` 断词换行（fe_cleanup_r1/before_dashboard_1440.png 与 r2_before 截图） | `white-space: nowrap`（真机复测 span 高 21px=单行） |
| 写作工具条按钮 `.working-copy-actions button` | `创建/工作副/本`、`版/式估/算` 断词成三行（按钮高 88px） | `white-space: nowrap`（容器本就 overflow-x 滚动；复测按钮高 31px=单行） |
| 侧栏导航 `.nav-item span` | `证据调研与方案/设计`、`安全信号与PV协/同` 词素中间截断 | `text-wrap: balance`（复测两行均衡：`证据调研与/方案设计`、`安全信号/与PV协同`） |
| 主内容区 `.page` | 超长英文串（哈希/URL）无兜底 | `overflow-wrap: break-word`（CJK 断行行为不变） |

## 截图留证

- `r2_before_wrap_sim1440_writing.png`：修前（1440 等效布局，body zoom 1.2 模拟）——胶囊断词、按钮三行、哈希横幅、模型 ID 胶囊
- `r2_after_wrap_sim1440_writing.png`：修后同视角——按钮单行、横幅人话化、胶囊单行、AI 胶囊只留状态
- `r2_after_humanized_panel_zoom140_writing.png`：修后（zoom 1.4 放大）——新建方案候选基线、工具条完整按钮、人话化横幅
- 监控阻断面板修后态（人话提示+悬浮技术串）与侧栏平衡断行见上方 ③/④ 表格描述（同 r2_after 系列现场确认）
- r1 批旧证（before/after_dashboard_1440 等 4 张）保留未动

## 红绿证据（反例先红）

```
python3 -m pytest tests/test_frontend_precleanup_r2.py -q   # 修前: 8 failed → 扩充后 9 failed/修后: 9 passed
npx vitest run src/runtimeReadiness.test.jsx                # 8 passed（'构建不一致'契约保留）
pytest tests/test_frontend_ai_role_settings_contract.py 等 6 文件  # 165 passed + 3 subtests（相邻契约无回归）
```

## FAST 自查补充说明（诚实边界）

- 全量 `npx vitest run`（85 文件）存在 140 failed——**与本批无关的存量状态**：
  以 git stash 前后双跑对比，失败集合逐字一致（28 failed files / 140 failed
  tests 前后相同），含大量 "No test suite found" 空套件文件；不在本批修复范围。
- 后端 5301 仍是旧进程（横幅正确提示"运行中的服务还是旧版本"），重启属
  集成人/编排口径，本批未动后端。

## 收尾

浏览器探针空间已用毕，标签已关闭；测试会话未新建项目、未写入任何业务数据
（只读走查 + 前端源码/样式修改）。
