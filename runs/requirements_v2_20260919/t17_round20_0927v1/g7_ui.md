# G7 界面实施证据（0927V1，按0926V1 G7口径 A701–A704）

- 日期：2026-09-27（本文件所述全部检查为当场实跑）
- 工作树：`implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313_g7worktree`，分支 `g7-ui-0927v1`，基线 `5b4c8c1`（与审阅基线一致），提交 `9bf88cc` + `c024ec2`。主工作区未改动。
- 结论分列：**A701 PASSED（vitest）**、**A702 PASSED（vitest）**、**A703 PASSED（1440/1920/2560 实测截图+DOM）**、**A704 PASSED（jsdom钉住＋真实浏览器输入/拖宽实测）**；A705–A709（外部Word往返/内嵌保存重开下载/双入口闭环）**NOT_RUN——不在本批范围**（见§6）。

## 1. 反例先证失败，再修（红线8）

反例测试先行写入 vitest，对**现行逻辑**运行证红（红证据存 `g7_red_run.log`，12 failed / 1 passed）：

```
cd frontend && node_modules/.bin/vitest run --config vite.config.mjs --environment jsdom \
  src/features/medical-writing/errorContract.test.jsx \
  src/features/medical-writing/protocol-workbench/ProtocolWritingDesk.test.jsx
→ Test Files 2 failed (2)  Tests 12 failed | 1 passed (13)
```

关键红例（`/tmp/g7_red_run.log`，已留档为 `g7_red_run.log`）：
- `medicalWritingSafeErrorText({message:"failed_retryable: chunk 3 download failed"})` 返回**原文逐字透传**（AssertionError: expected 'failed_retryable: chunk 3 download fa…' to match /[\u3400-\u9fff]/）。`product_ai_provider_transient`、`network/URLError`、未知工程文本同样透传——即0926V1 F09指出的"黑名单不命中即原样输出"。源码位置：修复前 `App.jsx:592-611`（基线行号592起），诊断正则 `_MEDICAL_WRITING_DIAGNOSTIC_RE` 不含这两个后端错误码（后端产码处 `services/api/app/writing_reference_upper_layer_adapters.py:536,848`）。
- 超时分支（基线 `App.jsx:601-602`）在**无任何job证据**时输出"任务仍在后台执行"——A702反例成立。
- 桌面布局4项全红：无"宽审阅：研究比较"入口、右栏aria-label为旧值"研究设计与建议"、文档画布不在DOM前位、无宽审阅态类。

## 2. 修复内容（工作树提交）

| 文件 | 内容 |
|---|---|
| `frontend/src/features/medical-writing/errorContract.mjs`（新增） | 受控状态/错误码合同：表驱动，`product_ai_provider_transient`/`failed_retryable`/版本冲突/429/网络各映射固定安全中文；超时文案按 `jobState` 取值——默认（unknown）为"本次结果尚未确认…确认任务没有完成后再重试，避免重复提交"，**仅在 `jobState:'confirmed_running'` 时才可称"仍在后台进行"**（A702）；自家中文合同文案原样保留；其余一律受控默认文案，**无黑名单透传路径**。`redactDiagnosticText` 对URL主机/`Bearer`/`api_key|token|secret|password|authorization`/邮箱脱敏。 |
| `frontend/src/App.jsx` | 三个函数改为从 errorContract.mjs 导入（机械搬移后替换）；诊断展开点接入脱敏：`setFullDraftDiagnostic(redactDiagnosticText(...))`、`<pre class="writing-diagnostic-pre">{redactDiagnosticText(fullDraftDiagnostic)}</pre>`（"展开诊断详情（技术信息）"summary 为显式权限门）。采纳失败处的 safe 文案调用自动获得诚实超时语义。 |
| `frontend/src/features/medical-writing/protocol-workbench/ProtocolWritingDesk.jsx` | 布局换向：文档画布（含完整候选与Office iframe）为DOM前位主区；右栏改为"任务与摘要"（aria-label同步），新增"宽审阅：研究比较"开关（`aria-pressed`，Escape可退）。宽审阅=纯CSS类 `pvi-wide-review`，**不重挂载任何节点**，右栏details面板原位展开为宽审阅面。 |
| `ProtocolIntakeWorkspace.css` | `.pvi-writing-desk` 改flex（文档 `flex:1 1 auto; min-width:min(720px,100%)`）；右栏 `width:clamp(280px,21vw,400px)`、`resize:horizontal`、`min-width:264px`、`max-width:min(44vw,880px)`（可调宽）；宽审阅面 `position:fixed; inset:24px`，内容 `max-width:1160px` 限宽；≤1180px 纵向堆叠保留。 |
| `ProtocolIntakeWorkspace.test.jsx` | 既有断言 `complementary name:'研究设计与建议'` 更新为新合同 `'任务与摘要'`（合同变更非行为回退，其余断言未动）。 |
| vite.config.mjs / tests/protocol-writing-desk-functional.* / public/genoffice-fixture/g7-sample.docx | 仅dev的fixture中间件+组件验收harness（真实组件+合成数据，详见§4）；fixture docx 复用仓库既有 0913 browser_functional 合成件（`*.docx` gitignore 对该文件以 `-f` 显式豁免）。 |

## 3. 定向测试绿（未跑全量，遵守本批口径）

```
node_modules/.bin/vitest run --config vite.config.mjs --environment jsdom \
  src/features/medical-writing/errorContract.test.jsx \
  src/features/medical-writing/protocol-workbench/{ProtocolWritingDesk,ProtocolIntakeWorkspace,ManuscriptWorkspace}.test.jsx \
  src/features/medical-writing/protocol-workbench/office/GenOfficeFrame.test.jsx \
  tests/ProtocolSourceSelectionRecovery.test.jsx
→ Test Files 6 passed (6)  Tests 35 passed (35)
node --test src/features/medical-writing/protocol-workbench/office/bridge-shim.test.mjs → # pass 5 # fail 0
npm run test:inventory → vitest/jsdom: 17, node --test: 48, coverage: complete; duplicates: none
```

说明：原反例运行中的 `bridge-shim.test.mjs` 属 node runner（清单规则 `.test.mjs→node`），已按其归属runner运行。eslint：新增/改动文件 0 errors；`App.jsx` 存在**基线既有**的2条 "react-hooks/exhaustive-deps rule not found"（基线 App.jsx 同样报2条，位于 9594/14113，系未安装该插件规则所致），非本次引入。全量pytest/vitest未跑（本批口径：定向）。

## 4. 浏览器实测（ego-browser，1440/1920/2560）

环境：本工作树自有 vite dev server（`127.0.0.1:5290`，已停），页面为 `frontend/tests/protocol-writing-desk-functional.html`——**真实 ProtocolWritingDesk + 真实 GenOfficeFrame**，合成数据与合成fixture docx，不写任何后端；未触碰5186/5301/8910与用户模型服务（8002缺席未动）。截图目录：`g7_shots/`。

**A703 三档布局（截图+DOM实测值）**：
| 档位 | 右栏宽 | 文档画布宽 | resize | 截图 |
|---|---|---|---|---|
| 1440 | 302px | 1104px | horizontal | `1440_desk_office.png`（真实Office编辑器加载合成docx，右栏任务/摘要+宽审阅钮+拖宽手柄） |
| 1920 | 400px | 1486px | horizontal | `1920_desk_office.png` |
| 2560 | 400px | 2126px | horizontal | `2560_desk_office.png` |

宽审阅面：三档开/关截图 `1440_wide_review.png`、`1440_wide_review_design.png`（非bridge档：研究信息/治疗方案建议/关键设计确认面板铺满1392×852宽审阅面，内容限宽1160px）、`1920_wide_review.png`、`2560_wide_review.png`。DOM断言：文档画布DOM前位、右栏 `aria-label=任务与摘要`。

**A704 Office状态保护（真实输入+真实交互）**：
- 在嵌入Office编辑器正文实际键入"G7宽审阅保持验证-A704"（`contentDocument.body.innerText` 验证 `hasTyped:true`）→ 开"宽审阅：研究比较" → 退出宽审阅：`{iframeAlive:true, srcSame:true, textPreserved:true}`；
- 右栏拖宽（CSS resize把手真实指针拖拽）：左拖302→264px（min-width钳制生效）、右拖264→564px（文档画布让宽至842px），全程 `{srcSame:true, textPreserved:true}`；
- 截图 `1440_after_toggle_typed.png`、`1440_rail_resized.png`、`1440_rail_widened.png`（图中可见所输入文字仍存在于文档内）。
- jsdom层另有 `ProtocolWritingDesk.test.jsx` 4例钉住：宽审阅开/关、savedDocument刷新叠加、布局合同、宽审阅类切换，全部断言 iframe 元素同一且 src 冻结（GenOfficeFrame既有F03会话冻结未被破坏）。

## 5. 与0926V1 G7口径逐条对照

- 右栏任务/摘要，完整候选与研究比较进宽审阅区：**完成**（桌面换向+宽审阅面；完整候选本就在宽文档区/App级"审阅全文初稿"浮层）。
- 1440/1920/2560实测关键内容完整可查：**完成**（§4，无小滚筒、按钮可达；正文14px与无112px嵌套滚筒为既有基线行为，未回改）。
- 调宽/切tab不重建Office iframe不丢dirty/选区/IME/撤销：**完成**（§4真实输入保持+元素/src同一；桌面右栏分组用`<details>`原位展开，无卸载路径；App级右栏tab条件渲染不触及编辑器画布，本轮未在浏览器复测App级UI，见§6）。
- 文案改受控状态/错误码合同（含 product_ai_provider_transient/failed_retryable/network 反例）：**完成**（§1–§3，红→绿）。
- 超时不得无证据称后台运行：**完成**（默认超时文案无后台声明；仅 `jobState:'confirmed_running'` 才允许；App.jsx:9579/9771/9936/10098 与 WritingReferencePanel.jsx:787 的既有"仍在后台进行"均在durable job确认/恢复流中（定位器已存储、可恢复核对），有job证据，未改）。
- 诊断按权限脱敏展开：**完成**（显式details为门，渲染前经 `redactDiagnosticText`；验证用例断言URL主机/凭证/邮箱被抹、`api_key=` 键名保留）。

## 6. 未验证/未跑（如实）

- **A705–A709 未跑**：外部Word往返、内嵌保存→关重开→下载一致性、摘要/引文/AI局部修订闭环、双入口、科学未决与保存权限——这些是产品端到端/真实模型项，不属于本批UI切片；且harness为合成数据，未做任何真实保存（红线：不写运行库）。
- **App级写作页（RichProtocolEditor/ai-rail）未做浏览器复测**：本批对App.jsx仅改错误文案合同与诊断脱敏（纯函数，vitest覆盖）；其右栏tab与ProseMirror编辑器的真实交互保持，沿用既有实现，本轮无新增改动故未重测。
- **隔离runtime当前无就绪v3研究定义项目**（`POST …/authoring-handoff` 对 proj_rux_03_002 返回404"未找到所请求的方案工作流对象"）：三档实测采用组件验收harness+合成数据，未走真实后端UAT链路；接入真实项目后的回归由后续UAT批次覆盖。
- 全量测试未跑（本批明确定向）；FAST车道P95等效率指标未测（无断言）。
- 我方dev server（5290）已停止；现场5301/5186/8001未做任何启停，8002缺席保持缺席。
