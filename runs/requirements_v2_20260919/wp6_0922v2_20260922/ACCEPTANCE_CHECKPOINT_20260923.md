# Protocol v3 0922V2 WP6 当前验收检查点

时间：2026-09-23 +0800

冻结源码：`e8966d508600ad5a37c868cf2ef85c7005379b92`，已推送 `origin/main`。
结论：当前产品已形成可编辑工作稿、真实 Office/Word 往返和三层模型降级链；尚未达到 Protocol v3 整体最终交付或申报就绪。以下 PASS 只代表该条证据范围。

## 用户可见结果

- 综合 AI 默认值为本地 `mtplx / Youssofal--Qwen3.8-Flash-Next-MTPLX-Optimized-Speed / medium`。
- 设置页允许选择 provider、model、thinking、reasoning effort，并调整两个有序 fallback 槽。
- 当前 fallback 顺序为 `opencode-go / deepseek-v4.1-flash / max`，再到 `cms-router / deepseek-latest-cloud / max`。
- 本轮本地 MTPLX 服务未监听、OpenCode Go 返回 429，真实 Study B/C 由 CMS Router 完成；这证明 fallback 可用，不证明 MTPLX 生成质量。
- 已采用的全文候选不会再显示第二个“采用候选”按钮；现有 Word 人工稿不会被新候选静默覆盖。
- Study C 可编辑 DOCX 已清除正文占位符和 AI 痕迹，使用“试验参与者”术语；正式就绪仍为 false。

## 自动与运行时证据

- 后端完整回归：`2608 passed`，1 条 Python 3.14 未来行为提示。
- 前端：15 个 Vitest 文件/111 项、48 个 Node 文件/66 项通过；production build 1971 modules，通过，仅既有 chunk-size 提示。
- 真实 HTTP：13 步候选采用/恢复/SOP 复用/409 冲突/再采用/DOCX 下载，结果 PASS。
- 三研究：Study A 同 job 恢复；Study B/C 各 22 个 chunk 完成，保留实际 provider/model/fallback 回执。
- 原生 Word：Microsoft Word 16.113.1 打开、修改、保存、关闭、重开，无修复提示；CMS 引文与文献表字段仍存在。
- fresh 只读会商：`zcode / GLM-5.3-Flash / max`，同一 session、无 fallback；独立聚焦复跑 14 项通过，无 P0/P1。

## A01–A26

|ID|状态|当前证据与剩余边界|
|---|---|---|
|A01|PARTIAL|双入口薄适配及回归存在；未用当前源码各完整走一遍两入口浏览器旅程。|
|A02|PARTIAL|handoff 到同一 manuscript/Office 已实现；真实入口 B 全链未单独复验。|
|A03|PASS|Study B/C 无附件建项并形成工作稿。|
|A04|PASS|带 source gap 的正文进入真实 DOCX，可编辑、保存和下载；正式状态保持 false。|
|A05|PARTIAL|关键决定合同和组件回归存在；Study C 本轮 0 decision-required，未形成完整高风险逐卡浏览器证据。|
|A06|PARTIAL|unknown/not-applicable 合同回归通过；三研究逐章人工适用性抽样未完成。|
|A07|PASS|A/B/C 使用不同 project/job/study identity，运行制品隔离。|
|A08|PASS|冻结来源角色、项目级 SOP 确认与关键剂量/安全/统计排除均由真实 HTTP 复验。|
|A09|PASS|Word 修改保存与语义核对解耦，核对状态不阻止真实保存。|
|A10|PARTIAL|失败保持 dirty 的 bridge/存储合同通过；浏览器未逐一注入所有坏回执。|
|A11|PASS|真实 409 版本/候选冲突后重读最新稿再采用，无静默覆盖。|
|A12|PASS|同 operation recover 与 durable job 续作只补未完成。|
|A13|PARTIAL|摘要保持语义对象；摘要经 Word 人工修改后的专项浏览器证据不足。|
|A14|PARTIAL|SOA 对象所有权和表格代码回归通过；实际 SOA 表格编辑未单独完成。|
|A15|PASS|真实 GenOffice iframe 内选区在专注模式切换前后保留，iframe 未重建。|
|A16|PARTIAL|局部 AI 合同存在；没有用当前 Word 与真实产品模型完成一次局部续写。|
|A17|PARTIAL|影响范围和事实变更合同存在；未在浏览器走完真实同步。|
|A18|PARTIAL|表格语义/首块表格回归通过；当前工作稿对象级浏览器抽样不足。|
|A19|PARTIAL|否定、单位和量级只作线索的规则存在；真实 DOCX 反例覆盖不完整。|
|A20|PASS|来源 manifest/版本/hash 在 job 与候选中冻结，跨批不回读漂移来源。|
|A21|PARTIAL|真实富文本选区、Word 修改保存已通过；IME 与全部编辑格式未覆盖。|
|A22|PASS|引文插入、移动、重编号、删除及文献表原位保留，经 DOCX XML 与 Word 往返。|
|A23|PASS|working_draft/adoption_ready/formal_ready 分离，当前工作稿未伪装正式就绪。|
|A24|PARTIAL|历史、pending 与当前稿保护存在；刷新/切研究/IME 的完整组合未覆盖。|
|A25|PASS|三个项目的身份、job 和制品相互隔离。|
|A26|PASS|旧工件/事件保留，新修复以新 revision/候选/Office snapshot 形成。|

## V01–V08

|ID|状态|证据|
|---|---|---|
|V01|PARTIAL|1440/1920/2560 DOM 宽度无外层溢出，正文区分别 1106/1526/2166px；当前截图均因 CDP 超时缺失。|
|V02|PASS|当前 writing desk 三视口可见文字最小 12px、低于 12px 为 0；结论不外推到未访问的其他产品页。|
|V03|PASS|长研究名、57 章候选、110 gaps、来源/SOP 均以紧凑 bullet/折叠展示。|
|V04|PARTIAL|有稿、候选、已采用和冲突出口已实测；等待/失败/断网未全部用当前浏览器重走。|
|V05|PASS|同一 iframe/contentWindow、同一 src、选区保留，专注 class 仅切换显示。|
|V06|PARTIAL|组件证明推荐默认预选、第二选项按 index=1 保存；当前真实浏览器未重走关键卡。|
|V07|PARTIAL|历史真实旅程曾为 14 clicks/1 text；当前源码未重新完成逐步计数。|
|V08|PASS|当前稿保存、下载、重开与历史 snapshot 均存在，旧 head 未被候选静默替换。|

## B01–B12

|ID|状态|证据|
|---|---|---|
|B01|PASS|正文+缺口可进入 Word，正文无可见占位符，formal_ready=false。|
|B02|PARTIAL|统一事实/当前稿适配已实现；两入口各自真实模型旅程未全部复验。|
|B03|PARTIAL|durable resume 和同 key 续作已实测；断网、刷新、enqueue 失败的全部浏览器组合未覆盖。|
|B04|PARTIAL|1–6 项原子决定和局部重写合同回归通过；真实高风险卡到 Office 未完整走完。|
|B05|PASS|版本冲突、候选冲突和回执范围由真实 HTTP/存储合同验证，无部分静默激活。|
|B06|PARTIAL|ICE 语境比较规则和独立医学抽样完成；尚未完成全部章节医学验收。|
|B07|PARTIAL|not_checked 与语义核对规则存在；当前 DOCX 的全部否定/单位反例未覆盖。|
|B08|PASS|冻结 manifest、SOP 项目确认复用、旧方案不升格及缺来源状态由真实输入/API 验证。|
|B09|PASS|坏 JSON/persisted=false/错 identity/409/pending dirty 的桥接与实际存储合同通过。|
|B10|PASS|真实 85+ 章节规模的初次、复用与恢复未重复模型调用，locator 合同受限。|
|B11|PASS|选区、Slice、格式签名、撤销及非目标保留有组件、浏览器和 XML 证据。|
|B12|PASS|引用往返、XML 解析、原生 Word 保存重开及 renderer 重建证据成立。|

## 医学接受结论

Study C 的框架和跨章主线基本自洽，但样本量段落存在已证实的 P2 问题：若双侧 alpha=0.05、把握度 90%、组间差异 3 分、SD 8、1:1 且考虑 15% 脱落，简单两独立样本近似需要每组约 149 例、总计约 352 例；总样本量 170 例对应把握度约 62%。当前 170 例来自功能验收合成参数，DOCX 丢失了“仅用于功能验收”的限定语。因此该稿只能作为工作稿，真实项目需统计负责人确认效应量、方差、分析方法、脱落率和最终样本量后重写。

当前还有常见 AI 初稿噪音：目的、总体设计、随机盲法与样本量等内容跨章重复。系统已保留 review advisory，但人工医学编辑负担仍需继续降低。

## 尚未闭合

1. 恢复本地 MTPLX 后，验证 exact effective model identity 和真实生成质量。
2. 用当前源码补齐 V01 截图、V04 全状态、V06 真实关键卡、V07 当前点击计数。
3. 对三个工作稿逐章完成医学/统计/安全接受，优先修正 Study C 样本量和限定语保真。
4. 将两个仍直连 provider 的旧竞品分析入口迁入统一 runner；当前综合全文路径已使用新链。
5. 最终 Word/eCTD 交付仍需项目真实申办者、版本日期及项目特异来源，不能由合成验收稿替代。
