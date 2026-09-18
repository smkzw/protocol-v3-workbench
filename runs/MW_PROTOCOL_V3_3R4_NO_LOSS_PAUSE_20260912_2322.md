# 医学写作子系统 Protocol v3 — 3R.4 无损暂停记录

- 时间：2026-09-11 23:22 Asia/Shanghai
- 触发：用户明确要求"无损暂停，做好任务记录"。非失败、非路由异常、非授权问题。
- 本记录性质：暂停快照与精确恢复指令；不是任何验收。

## 1. 暂停时点完成状态

### 本夜（2026-09-11 21:14 接管起）成果，全部已验证/已提交

| 项 | 状态 | 证据 |
|---|---|---|
| 接管对账+工程review+Plan/goal更新 | 完成 | reviews/mw_protocol_v3_takeover_review_20260911.md；runs/MW_PROTOCOL_V3_TAKEOVER_RESUME_20260911_2114.md |
| 3R.3 全任务（111载体、8批次） | **完成并验收** | reviews/mw_protocol_v3_3r3_batch8_acceptance_and_3r3_closure_20260912.md；Trellis 09-06 completed |
| 全八批组装+full lint | COMPLETE 111/111 | runs/mw_protocol_v3_3r3_batch8_fresh_20260911/final_all8_lint.txt |
| 跨批crosswalk | 13项全PASS | 3R.3收尾评估文档内记录 |
| 3R.4依赖图首交付 | 交付+主owner验证 | dependency_graph.py + test_dependency_graph.py（10测试）；组合217/217（runs/mw_protocol_v3_3r4_20260912/main_owner_combined_with_depgraph.xml） |
| Commit链 | 8个 | b0b3663→7118329→98db346→cfeebdb→48f01c9→a67b9a2→5c3ad99→84488d3（HEAD） |

### 暂停时在飞（唯一进程）→ 暂停后即时终态更新

- 3R.4依赖图 fresh复核（zcode/GLM-5.3-Flash headless，~23:21启动）：
  **23:24终态失败——ProviderBusinessError [1308] 已达5小时使用上限
  （zhipu-coding-plan，限额2026-09-12 01:44:45重置），exit 1，stdout.txt 0字节，
  stderr.txt留存完整栈。**
  - 这是已验证的提供商配额耗尽（本夜5次zcode/GLM复核消耗所致），非延迟非路由漂移。
  - **恢复时：直接重派该只读复核（合法：复核者只读、无重复执行副作用）。
    建议走非GLM家族路线（codebuddy/deepseek-v4-flash或omp/luna均可，产物是
    deepseek-v4.1-flash的依赖图，取非deepseek为优）；GLM配额恢复后亦可。**
  - 派发材料已就绪可直接复用：prompts/zcode_mw_protocol_v3_3r4_fresh_20260912.md
    （改为新harness时替换runner路径名）+ context/mw_protocol_v3_3r4_fresh_review_
    20260912_context.md（检查单K1-K8）。
  - ~~原文"从stdout.txt收割"已失效~~（留存供审计）。

## 2. 暂停时文件状态（2026-09-11 23:22实测）

- Git HEAD：84488d307eae240cc48808dea506691091817354；脏条目413
  （runs/prompts/context/handoff等证据与派发包，按文件归属纪律有意不入commit）。
- 关键哈希（SHA-256前16位）：
  - protocol_v3.py b76a048ff1f50cb8（=交接14.4记录，未变）
  - registries/chapters.py 9297ed918d402a46（未变）
  - registries/dependency_graph.py 2f3c7f7301d032b9（3R.4新交付）
  - test_dependency_graph.py 631559d136c4a2c9（3R.4新交付）
  - assemble_chapter_registry.py 3c96750782c68a14（未变）
  - lint_chapter_registry.py 348abbd00a047097（未变）
- Trellis：09-06-protocol-v3-3r3=completed；09-11-protocol-v3-3r4=in_progress+user_paused。

## 3. 恢复协议（按序执行）

1. 读最新全局 ~/.zcode/AGENTS.md 与 ~/.codex/AGENTS.md（阶段恢复点）+本记录+
   .trellis/tasks/09-11-protocol-v3-3r4/{task.json,checkpoint.md}。
2. 核对：HEAD仍为84488d3、第2节哈希表。
3. **重派3R.4 fresh复核**（见第1节更新：GLM配额耗尽终态失败，复核者只读可合法
   重派；建议非GLM家族路线；材料复用现成prompt/context）。
4. 裁决→（如有缺陷）主owner最小修复→组合套件（env模板见任何batch run目录的
   report_*.md的GREEN_EVIDENCE节）→验收→commit（dependency_graph两文件+验收记录）。
5. 3R.4第二工作项：条件适用性规则运行时executor（各批复核确认的deferred；
   实现位置建议registries/，与dependency_graph.py同层；契约=各批合同的
   conditional_applicability_rules已由依赖图索引）。
6. 之后：3R.5 R03 QC registry（68行拆原子，含word_rules交叉校验改进项）→
   3R.6 Ⅰ期模板问题卡（**用户决策点**：候选TP-MA-05/06、T02-00修订版、用户新提供；
   预选推荐T02修订版）。
7. 连续实施纪律、执行/会商机制、token节省规则按全局AGENTS现行版本；路由按
   /Users/smkzw/.zcode/zcode-route-manifest.json当前版（勿沿用本记录中的路由细节作
   为未来依据）。

## 4. 暂停时不做的事

- 不kill在飞只读复核（其进程自然结束，输出自落盘）。
- 不新增任何派发；不清理任何runs/rows/evidence/会话/检查点。
- 不修改已验收批次文件；不碰live workbench、8910、plan-upgrade-20260905、外部SOP。
- 本记录不改变任何验收状态、不冒标3R.4完成。

## 5. 接管夜的机制沉淀（供恢复者直接复用）

- 批次验收流水线：worker交付→主owner组合套件+独立组装复现+越界审计(mtime)→
  非同族fresh复核→缺陷按复核者最小方案修复→验收文档→commit。
- 复核先例已固化为派发合同条款（word_rules、归属声明、条件规则schema位置、
  裸布尔、负例expected-code、日文字符、provenance窗口）——新批次worker直接合规。
- harness特性：grok后台长任务会被harness取消（弃用于复核）；codebuddy plan模式
  拒Bash（复核者静态核验，主owner跑测试补足）；codebuddy报告在stream-json的
  result字段；omp报告在agent_end的assistant text。
- 测试命令模板见任何runs/mw_protocol_v3_3r3_batchN_20260911/report_*.md的
  GREEN_EVIDENCE节。
