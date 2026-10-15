# 自检阻断修复 · 纪元R2第2次自检红节点④（2026-10-15，实现师，本ask内实跑）

## 红节点（承接自检报告）
④研究设计确认：PICOS 14字段落库断裂。任务书判定"前端保存绑定framing"。

## 根因复核与精修（读码+读库+可复现测试）
- **绑定层结论修正**：`saveCurrentDrafts` 在 picos 阶段对 picosDirty 表单
  **确实调用 stages/picos/draft**（Setup.jsx:2506-2514）；新增契约锁定测试
  （填人群概述→保存草稿→POST picos/draft）在修前代码上即通过——绑定本身
  未断。r2-2 全程无 picos/draft POST 的真因：**没有任何东西填过 PICOS 字段**
  （测试者用的是"采用当前方案文字建议"，它只写 framing.structured_design
  五维度），picos 从未 dirty，保存自然只走 framing 分支。
- **"表单重置" illusion（循环感知根因）**：完成第二步的锁定 title 是单选
  优先链——采用建议后 framingPendingDraft 优先级最高，title 显示"第一步
  草稿未并入"（14项列表"消失"）；并入后 framing 干净，title 落回
  "请先补齐第二步必填项：14项"（"复现"）。测试者读作"promote 清空表单"。
  实际 picos 表单状态经 mergeIncomingPreservingLocal 保留（读码：incoming
  空值跳过、本地保留），但14字段从未有内容。
- **产出缺口**：建议按钮住在 PICOS 适用性页却对 14 字段零产出——每次采用
  只制造 framing 草稿→并入→title 洗牌，journey.picos 恒空（任务书 DB 实证）。

## 修复（反例先红后绿；修链路功能非绕测试）
1. **建议产出 PICOS 字段**：采用当前方案文字建议在用户未自选时保守推导
   picos.design_archetype（随机+安慰剂→randomized_confirmatory；随机无
   安慰剂→randomized_exploratory；非随机不猜）——建议自此对第二步有实际
   产出，不再空转。
2. **双草稿自动落库**：应用建议后 nonce-effect 链式保存 framing 草稿→
   picos 草稿（结构化维度+推导的design_archetype一起持久化）——后端日志
   "全程无 stages/picos/draft"的断裂面自此补上。
3. **多阻断 title**：完成第二步锁定提示从单选优先链改为全量并列
   （第一步未并入＋第一步未提交＋I期Part＋第二步14项同时列出）——
   "消失又复现"的表单重置 illusion 消除。
4. 契约锁定测试：picos 阶段保存草稿必发 stages/picos/draft（防回归）。

## 反例与测试（先红后绿实证）
- vitest 三件新测试（stash摘除组件改动证红）：
  A 双阻断title——修前只显示"第一步草并入"一条（红）→修后两条并列（绿）；
  B 双草稿落库——修前无 picos/draft POST（红）→修后 framing+picos 双发且
    picos.design_archetype=randomized_confirmatory（绿）；
  C 保存绑定契约——修前即绿（绑定未断的实证），锁定防回归。
- 全库存：41文件/231测试全绿（本文件5件含前两轮修复的存续验证）。

## FAST定向自查（本ask内实跑）
1. **真机持久化路径**（r2-2牺牲项目，任务书指名复验）：读当前journey
   （rev20，picos空）→ POST stages/picos/draft（design_archetype=
   randomized_confirmatory）→ 200，rev21，picos_draft PRESENT、
   missing=13（其余字段如实）——持久化端到端在真实项目可用。
2. 前端vite dev从盘即时生效（HMR），无需重启；本ask未改后端代码。
3. r2-2旅程推进 rev20→21（写入一份picos草稿=用户工作保留机制，供下一轮
   从draft继续而非从头填）。

## 下一轮自检预期④路径
采用建议→自动双草稿落库→（如第一步有未并入）并入→title并列显示剩余
14项缺失→继续经组合推荐包/手填补齐→保存草稿（picos/draft）→完成第二步
（picos_sha256形成）→对齐记录→语料门5/5→写作入口开启。

## 账本项（任务书附观察，本ask未修、如实转交）
- B：partial_failure批次"一键确认合格候选(16)"反复出现且确认0项（UI死循环
  按钮）——需带截图复现定位；
- C：165全量批次95项fidelity_blocked（58%拦截率）——与owner 20261004a
  "高置信自动放行只拦真正可疑"方向不符，属忠实度门重设计批次（P0方向已立）；
- D："确认变更并重新核验"清空表单预填（无提示重置）——merge方向为incoming
  标量覆盖本地（读码：mergeIncomingPreservingLocal else分支），需产品裁定
  合并方向后另批修。

## 红线自检
未碰 live 8910/医学监查；模型服务器零接触（本ask无AI调用）；未清库未reset
（r2-2经产品草稿端点推进 rev20→21并留痕）；未动immutable；反例先红后绿
（stash证红三件中A/B红、C绿=绑定未断实证）；主会话并行未提交改动零触碰。
