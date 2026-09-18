先读权威输入与现有相邻组件合同，再写红测。合同已对齐。先写完整红测与 scratch，再实现组件。红测已失败（缺组件）。正在实现 JSX 与 CSS。编辑破坏了测试文件结构，正在修复。修正测试查询：期别用 `getAllByText`，引文匹配中文句号。9 项绿测已通过。接着跑相邻测试并写 REPORT。## Worker 交付（未挂载，未验收）

已新增复合给药候选卡三件套；按 snapshot 合同渲染全部已列期/组/步骤，不做互斥选择或事实推断。

**文件 / sha256**
- `RegimenProposalCard.jsx` — `bb0aac588e38223e3e540e112d8239c74915415ceaed95f30a8599490e1cabbb`
- `RegimenProposalCard.css` — `f23de88d606019a1432fd227c0aaa186a536ef8858d42a5e397ad964cdcea59d`
- `RegimenProposalCard.test.jsx` — `b3d2c69d72940345ee5701b9c612e9d891f97bb62aac4e84eb5c95cc96d91c0c`

**验证**
- 红测：缺组件 import 失败 → `scratch/vitest-red.log`
- 绿测：9/9 通过 → `scratch/vitest-green.log`
- 相邻 Workspace/Source：38/38 通过 → `scratch/vitest-adjacent.log`

**限制**：组件未挂载；无浏览器验收；无 CAS/后端确认。

详细报告：`runs/execution/mw_protocol_v3_regimen_card_ui_20260913/scratch/REPORT.md`
