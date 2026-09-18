# 3R.4D 有界执行：当前模板事实采用接线

你是工程execution worker，不是独立reviewer，不关闭任务；Codex为owner和最终整合者。目标是在owner已完成的D内核上，将A/B/C真实接入同一次SQLite采用，不能另造平台。新work key mw_protocol_v3_3r4d_template_adoption_20260913_v1，写范围严格见同目录dispatch_contract.json（已有before/和hash），不得递归派发/会商/自行换模型。工程model E04 GLM-5.3-Flash:max，产品模型完全禁止调用。

## 先读与当前状态

完整读最新 /Users/smkzw/.codex/AGENTS.md、适用AGENTS；当前Plan plans/mw_protocol_v3_implementation_plan_v3_20260912.md 的3R.4D及20260913接线顺序细化、design v1.4尾部输入绑定、Trellis当前prd/checkpoint尾部。阅读 reviews/codex_mw_protocol_v3_3r4c_integration_readiness_20260913.md、B acceptance与各当前affected完整定义/测试。

用户已授权连续工程实施、保留必要科学/数据语义但排除纯安全专项；用户体验AI lead，用户不维护JSON、hash、read-set。不得改live/监查/8910/只读SOP/plan-upgrade，不commit/reset/stash/cleanup，不改旧runs/immutable数据。所有DB测试tmp synthetic，TestClient允许、不启动监听服务、不调用产品模型/OCR/翻译/旧五失败项、不联网查临床资料（本任务纯工程）。无新依赖。先行为反例后最小实现。

Owner已经实现（不是待你重做）：
- errors.py明确OBJECT-NOT_FOUND→404、SERVICE-CONFIGURATION_INCOMPLETE非retry；真正CAS409。ProtocolWorkflowError保留Python异常bookkeeping，不再掩盖事务退出错误。
- ApplyStudyDecisionCommand/API有严格bool revise_confirmed_facts，显式confirmed user决策可改confirmed已有事实，FROZEN新路径不改；旧默认路径/历史hash保持。新operation编码fact_updates hash及event。
- canonical/decision_inputs.py显式fact_path字面键+members，非空唯一refs；新采用后值hash与存在性随同event持久化。当前decision-graph从已提交事件覆盖预设节点，current/stale/unverified独立于历史canonical_state。Agent5只把实际stale重新入队；legacy无binding仍unverified，不整体重开。生产推荐输入集合完整性需5R生成上下文验证，此机制不冒充医学批准。
- application/reconstruction.py已理解新operation/refs。真实HTTP A20→无关B→另一key修改剂量30→replayA保留revision4/零新写，相关原决定stale、无关current，独立存储连接events重建hash相同。新readset混用同CAS409。
- registries/template_runtime.py load_current_template(root)从当前config源文件构建existing ChapterRegistryDocument，再通过B load_fact_catalog/load_applicability_rules作source-bound核对；不是读取旧runs组装件，不是内容/Word验收。当前111/743/70测试通过。
- C已修桥接/条件unknown/shared active owner，当前hash见readiness。直接消费 build_fact_labeled_impact_plan(graph,facts_before,facts_after,bindings,rules)；projection hash不是workkey。C源/B源本任务只读。
Owner针对性验证235项通过+输入类型/readset 9项+当前模板1项；不是当前全量。你须自行验证受影响代码，不能引用数值当本轮结果。

## 需要你完成

1. 当前模板上下文的真实采用入口：复用现有ApplicationService/UoW，提供明确typed/template-bound方式（必要时新增api schema/endpoint或现有命令可选template上下文）。保持旧无模板调用兼容，不能让旧历史重放在新规则装载前被拒。UI以后自动提供模板上下文，用户不手填。用已有load_current_template而不是复制当前JSON到第二存储。API必须实际能调用这条链，不能只存在纯函数/测试fixture。

2. 同一事务里生成并持久化：base study revision/hash、新study revision/hash、实际native fact changes、B ApplicabilitySnapshot（unknown是未决）、C完整typed impact（候选与confirmed_reopen分开）、registry/catalog/rules身份、明确operation key。优先作为既有decision event payload的版本化adoption部分存储/可查询，不建新数据库或通用工作平台，不把projection hash当idempotency key。查询必须有实际内容，可复用当前event query/API结果，不产生写或模型调用。template-bound采用的operation key/CAS材料必须绑定模板上下文、更新与显式移除意图，不能换新decision重用同key造成第二效果。保护旧历史字节hash、保留exact replay返回合法当前后继definition/原decision。

3. 在采用前验证当前目录支持的实际输入类型与别名/条件矛盾，复用B的类型/规则/投影逻辑；不能用字符串false冒充布尔false，不以缺失为false。允许部分资料未决继续保存，不强迫所有章节几百required字段一次齐全；内容生成缺项另行解决。旧事实可以留在历史，新模板变化路径需有确定canonical owner，不能自动猜alias。为“旧alias与新canonical矛盾”提供明确retired_alias_paths等删除语义：只明确退休已确认来源映射alias，新revision移除当前alias、旧revision/events不动，null不是delete，不能静默清理或删除canonical真值。别引入第二事实存储。

4. 真实SQLite验收：实际当前模板canonical字段已有值→新值（不是仅新增不同路径）；native unknown/false与不适用冲突；current registry hash绑定；同key exact replay无新aggregate/event/outbox；同path新key两次不同revision有效；同key不同意图拒绝；并发CAS一胜一待处理；提交结果unknown沿用现有查询对账不重复模型；新存储连接/事件重建保持结果；相关当前确认stale、无关current。测试尽量在新integration/test_template_fact_adoption.py保留隔离证据。不要弱化旧负例/删fixtures/xfail。

5. 检查owner新增intent/readset在事件重建和ledger重建的一致性：新payload绑定adopted revision与refs/事实变化hash应可复验，不能只接受字段存在；必要最小修复在允许文件内，保留历史无额外字段路径。不是安全专项，这是恢复正确性。

## 有意不做

- 20260913 Plan已将“整稿采用去重与有效文档版本保存”移到V1编辑器同实现/验收，未删除义务。当前ApplicationService没有整稿保存消费者；不要提前造第二文档保存链，不改canonical/document.py，不把旧文本换header hash伪装成新研究成稿。D本轮只保存事实/条件/影响/确认输入效果，文档原绑定保持，待V1显示需同步并生成完整新稿。
- 不建R03/Word/UI/生成Agent；owner会只读梳理这些，不碰你允许源码。C/B文件若发现实质缺口，给owner最小反例并标未决，不越界自修。
- 全量tests/protocol_v3只在你全部改动稳定后跑一次（若真实失败定位修复后可复跑）；owner本轮不会改你的产品源或测试。定向优先，避免反复整仓。默认环境必须带TMPDIR=$(getconf DARWIN_USER_TEMP_DIR)，否则遗留Darwin路径测试误失败。

## 环境与输出

W为当前workdir。pytest用现有 runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python，clean env PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:. TMPDIR为Darwin temp。源码侦察优先rg/skim，读完整affected定义。禁止打印环境/凭证，不读私有会话日志或运行pgrep -fl。

runner hard wait7200秒/128内部轮；慢但有进展不自重派/fallback，owner等待同一运行句柄。输出完整具体：API调用示例、哪些路径已实际接线、源hash、测试日志/反例、兼容性/未做事项。标准报告必须含：
# Execution Output:
## Boundary And Context Check
## Work Performed
## Artifacts And Evidence
## Commands And Observations
## Blockers Or Missing Environment
## Rerun Requests Or Next Step
只写本run新报告/日志，不自行验收或改Trellis。
