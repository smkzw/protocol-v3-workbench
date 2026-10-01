# R27 第2轮 · 医学修订路由验证报告（r2-revroute）

- 测试者角色：第2轮医学修订路由验证员（UI黑盒，仅浏览器操作推进状态）
- 时间：2026-09-29 20:44–21:20 (+08)
- 前端 http://127.0.0.1:5186（代理→5301），后端 PID 83991（17:24 启动，晚于全部路由代码 mtime，运行为当前工作树代码）

## 任务执行路径（全部经浏览器完成）

1. 项目总看板 → 下拉选择 **R26MW-SGC2101（口服sGC激动剂）· 慢性心力衰竭（HFrEF）· MW-II-064699A9**（任务书点名项目）→ 医学写作 → 「进入写作平台」。
   - 结果：**建立工作稿失败**，界面 status 报：
     `protocol assembly plan still has unresolved scientific design blockers: intervention.active_comparator_regimen, intervention.background_treatment, intervention.investigational_product_dose_actions, intervention.investigational_product_regimen, intervention.permitted_concomitant_treatment, intervention.placebo_regimen, intervention.prohibited_concomitant_treatment, intervention.rescue_treatment`
   - 判读：R26 P0①（心衰场景研究框架/PICOS表单体塌缩为骨架）未修复的直接后果——intervention 8 项设计事实缺失，该Project 无法建工作稿。附带观察：报错现已逐字段列名（较 R26 P1④ 只报数量有改进）。
2. 依任务书备选路径改用 **已有可编辑工作稿的项目**：`合成药M8 · 复发缓解型多发性硬化 · II期 · MW-II-00990781`（proj_user_97189da36a75，工作副本版本2，编辑中，2026/9/26 已保存）。
3. 目录 → 研究设计 → **总体设计**（含实质正文段落）。在编辑器内选中目标句：
   「双盲治疗期自第1天至第24周，治疗结束后进入停药后4周的安全随访期。」
4. AI修订指令：修订意图=`medical_writing_revision`；用户指令=「请在保持随机双盲平行组设计表述不变的前提下，补充：①双盲维持与紧急揭盲程序的概括句；②停药后4周安全随访期内应采集的安全性指标概述，风格与ICH E3总体设计章节一致。」→ **提交AI修订**。
5. UI 显示「AI修订已提交，正在后台生成候选...」→「正在校验AI候选（60%，步骤4/5）」→ 完成：**4个候选**（推荐版本/备选1精炼版/备选2结构重排版/备选3保守版），均「待处置」，未写入工作副本。

## ③ 路由核对（sqlite3 只读，证据 route_verification_sql.txt）

- durable job：`mwjob_3dc3f0faf7e7f564c7304ab8`（section_ai_candidate，completed，attempt 2/3，12:50:38→13:16:38 UTC，约26分钟）
- `payload.generation_context.descriptor.ai_policy.base_url` = **https://opencode.ai/zen/go/v1**
- `route_identity_snapshot.profile_id` = `independent_ai__opencode_go_deepseek_v41_flash`（model=deepseek-v4.1-flash）
- gateway 侧 ai_task_runs.jsonl 两次 medical_writing_revision 运行（12:50:40 failed / 12:58:14 completed）route_base_url 均为 https://opencode.ai/zen/go/v1
- **期望（owner决策20260928）= https://ollama.com（independent_ai__ollama_cloud_dsv41）→ 不符 ⇒ P0 路由错误**

### 根因（实现侧定位，供集成人）

- `services/api/app/ai_execution_policy.py:382-413` `_capture_revision_cloud_route` 泛取 fallback 链第一个 enabled 云 profile；
- `isolated_runtime/ai_provider_settings.json` 的 `fallback_chain` 仅含 `independent_ai__opencode_go_deepseek_v41_flash`；新增的 `independent_ai__ollama_cloud_dsv41`（base_url=https://ollama.com，enabled）**未入链**；
- owner 决策文档「待实现」的 `TASK_TYPE_ROUTE_POLICY`（ollama_cloud_dsv41 通道优先解析）在工作树中未实现（rg 无命中）。
- 修法指向（不代改）：将修订（及分诊/设计/PICOS）的通道解析改为优先 `independent_ai__ollama_cloud_dsv41`，或将该 profile 置于 fallback 链云通道首位。

## ④ 医学视角产出质量评价（1-2句）

4个候选均逐项保真原设计事实（1:1随机、0.5mg qd、安慰剂四要素匹配、D1–W24治疗与停药后4周随访锚点），补充的随访期安全性指标清单（AE/SAE、首次给药6h心率/血压与心动过缓、PR间期/房室传导阻滞、ALC、黄斑OCT）与S1P调节剂用于RRMS的安全性关注点医学自洽、与项目已确认事实一致；且对无来源支持的「紧急揭盲程序」拒绝编造并显式记入 uncertainties，无幻觉、符合科学诚信。不足：用户指令第①项（揭盲程序概括句）因语料/事实源缺失整体未落地，需先补揭盲规则来源方可闭环。

## 其他观察（非本轮主诉）

- 修订首次尝试 12:50:40 因输出校验失败被拒：4个候选均引入了项目语料外人群词「患者」（attempt 1 失败），第二次尝试改用「受试者」后通过——术语溯源校验按设计工作，但代价是整轮重跑、总耗时约26分钟（P2：修订整体时延偏高，UI长时间停在"正在校验AI候选"无阶段内细分提示）。
- camofox 浏览器 tab 在长轮询期间两次丢失（"Tab not found"），后端 durable job 不受影响，重开页面可恢复观察（环境现象，非系统缺陷）。

## 证据清单（本目录）

- `01_overall_design_section_before_revision.png` — 修订前总体设计节与选中段落
- `02_revision_submitted_processing.png` — 提交后「AI修订已提交，正在后台生成候选...」
- `03_revision_completed_4_candidates.png` — 完成后4候选（推荐+3备选）与处置按钮
- `route_verification_sql.txt` — sqlite3 只读核对输出（durable job + ai_policy + ai_task_runs）
