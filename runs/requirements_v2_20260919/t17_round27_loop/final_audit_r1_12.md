# 12 轮用户视角测试循环（R1–R12）· 独立收官审计报告

- 审计人：独立复核员（只读角色）
- 审计日期：2026-10-08
- 审计对象：`runs/requirements_v2_20260919/t17_round27_loop/`（retest_r1..r12 + 各轮席位报告 + CLOSURE_REPORT + 基准轮资产）＋ `runs/benchmark_real_protocols/` ＋ git（f72fa95..HEAD=a1b6609d）＋ `runs/acceptance_gate/run_2026-10-07T215130Z_68559/`
- 方法与边界：**只读**。未修改任何既有文件（仅新建本报告）、未推进系统状态、未开浏览器、未跑测试、未触碰 8910/模型服务器。live 核查仅用只读命令（`git log/status/ls-files`、`lsof`、`pgrep/ps`、`stat`、zip/JSON 只读解析、rg 文本抽样）。涉密文件（/tmp）仅读文件头与行数，未把其内容复制入本报告。
- 被审查方自述的收官口径（送审输入，逐项核验）：第 7 轮（合成场景）新缺陷 2；第 8–12 轮为真实方案基准轮（对象=芦可替尼 AD III 期信息包）；第 12 轮收官"新缺陷 1、closed=21、开放 P0/P1=0、回归 0；未收敛仅因再测试 allPass=false"。

---

## ① 账本终态重建与核对 —— 部分通过（closed≈20 可逐条复现；"21"与"开放 P0/P1=0"不可复现）

### 1.1 逐轮重建（来源：retest_r1..r12 十二份复测报告＋对应材料）

| 轮 | 关闭项（浏览器/制品验证） | 关键证据路径 |
|---|---|---|
| r1 | ⑤ 入口B解析32分钟 | `retest_r1_material/evidence_entryB.txt`（review_ready/elapsed=898s/10:28:45）、`retest_r1_shots/`、`RT1_PD301_preview_export.docx` |
| r2 | ③ OCR 环境缺口（含 N5 编排器所有权失配） | `retest_r2_material/ocr_probe_r2{,_recheck}.json`（passed=true）、`tr_probe_r2*.json`、`concurrency_drill_summary_recheck.json`（tr 1178/1178、co_resident 0） |
| r3 | NEW-P0-12/14 建稿500；P0-1 重算500 | HEAD=1b4c756；`retest_r3_material/`（OCR probe、drill）、`RT3_OB501_preview_export.docx` |
| r4 | NEW-P0-19/L2 撰写侧死锁（分诊侧以反例测试为证） | HEAD=f37b64e；`retest_r4_material/`、`RT4_IB501_preview_export.docx` |
| r5 | NEW-P0-23/16 建项守卫泄漏；NEW-P0-21 篮子移交 | HEAD=2556332；`retest_r5_material/`、`RT5_HPT801_preview_export.docx` |
| r6 | P0-24 平台入口幂等；P2-43 放行幂等；P1-42 批注清扫 | HEAD=06d0b4f3；`retest_r6.md` §一（三处真实连点探针）、`RT6_PHN902_preview_export.docx`（批注 0 命中） |
| r7 | P0-26 导出渲染双修；P1-30/17 版本门堵1.0（门本体；反馈弱另记 R7-N1） | HEAD=1dfde82e；`retest_r7_shots/10-冻结进度0of109.png`、`RT7_GER601_preview_export.docx` |
| r8 | P0-18 样本量输入层门（正反双向） | HEAD=18ed698b；`retest_r8.md` §一、`retest_r8_shots/10-样本量修正后导出落地.png`、`RT8_ID701_preview_export.docx` |
| r9 | P0-05 总数优先；P0-06 DMC 分支；P1-48 锚点录入链（上纸留挂） | HEAD=0ddfb758；`RT9_BE204_preview_export.docx` |
| r10 | P1-50 重复行去重；P1-51 批量冻结行内结果；归位批最小件（邮箱/VZV/considerations/AESI 条件化） | HEAD=0400c3dd；`retest_r10_shots/10-批量冻结行内跳过清单.png`、`RT10_BE204_redose_export.docx` |
| r11 | P1-45 吞吐透明化 | HEAD=a1b6609d；`retest_r11.md` §一 |
| r12 | 无新关闭；新立案 ⑥ 幂等继承死路（P1），并确认 P0-27/P1-48上纸/P0-03/P0-25 仍挂账 | HEAD=a1b6609d；`retest_r12.md` |

累计（复测口径，归位批按 1 条计）：**1+1+2+1+2+2+2+1+3+3+1+0 = 19（第1–10轮）+1（第11轮 P1-45）= 20 条**。CLOSURE_REPORT ⑤ 自述 "closed 19条（17+P0-06+P0-18限定版）"——与本次重建的前 10 轮 19 条**逐条吻合**（17 + P0-06 + P0-18）；第 11 轮再关 P1-45 后应为 20。**"closed=21" 无法从任何既有材料复现**（差 1 条，需一个未留痕的计数约定，例如把"归位批"拆成 4 件或把 N5/忠实度门重设计另计）；差异属记账口径，非证据缺失——20 条每一条均有可比对的证据路径。

### 1.2 "开放 P0/P1=0" —— 不成立

第 12 轮收官时明确的开放/挂账项（均有书面记录）：

- **fpv/挂账（修复已落、验证未成）**：P0-27 剂量门（生成层无窗口，`retest_r10.md` §一、`retest_r12.md` §二）、P1-48 上纸（生成链）、P0-03 正向批量冻结、P0-25 初稿校验宽容度/507/批次跳过（`retest_r6.md` §一）。
- **已立案未修复的 P1**：⑥ 幂等继承死路（第 12 轮新立案，`retest_r12.md` §一）；【V1】标题占位（第 12 轮仍未清，`r11-B/review.md` §三、`r12-B/review.md`§二；本审计在 `r12-B/r12b_smoke_r12_full.txt` 实测命中 1 处）。
- **基准轮评审立案的 P1/P2 族**（"内容缺口"类）：r10-A AD 导出件的样本量 850 断裂（→P1-53 规格在库）、SAE 报告路径空、6.3/6.4 空、SoA/参考文献/保险空、2.3.x 空等（`r11-B/review.md` §四 7 项 P1、`r12-B/review.md` §三 7 项 P1+10 项 P2），加上历史 P1 族（R2-N1/N2、R4-N1、R5-N1/N2、R6-N1/N2/N3、R9-N1、R10-N1，见 `retest_r11.md` §五"与账本的差口"）与种子①②"未按原路径复跑"。

复测协调员自己在第 11/12 轮报告里写明："**收敛≠全清**……P0-27/P1-48上纸/P0-03/P0-25、种子①②⑥未按原路径复跑、历史 P1 族仍开放"（`retest_r11.md` §五、`retest_r12.md` §二）。因此"开放 P0/P1=0"只有在把"开放"重新定义为"均有归属与下一周期安排"（规格在库/移交清单）时才勉强成立；按报告采用的 open/fpv/closed 三态口径，**不成立**。

### 1.3 "回归 0"

- 逐轮抽查口径（每轮建项＋导出 2 点）：12 轮中 r1–r11 各 2/2 重过；**第 12 轮导出未重复执行**（`retest_r12.md` §三明示"本轮因生成死路未重复导出——维持 R10 通过结论"），实际执行 1/2。以"抽查未见回归"计，**成立**。
- 若指全库验收门：**不成立**。HEAD=a1b6609d 上最近一次全库门 `runs/acceptance_gate/run_2026-10-07T215130Z_68559/result.json`：`verdict=FAIL`、`failed=70`（未匹配已知失败账的 nodeid）、`reasons=[baseline_is_ancestor_of_head_increment_mode, required_selftest_failed, new_pyflakes_undefined_name]`、selftests 0/5 通过、security_sentinel_blocked 1 条；含新增 pyflakes undefined ×2（`services/api/app/medical_writing_repository.py:3510-3511`，字符串注解＋函数内局部 import，**运行时无险**，但门红）。该门含工作树未提交改动引起的指纹漂移/清单计数类失败（见⑤）。LOOP 自身把"全库门"列为 NEXT_GATE（CLOSURE_REPORT ④/⑤），**从未声称全库门为绿**——此项不计为隐瞒，但任何"回归 0"的对外表述必须限定在抽查口径。

### 1.4 深查 closed ②条（反例＋修复＋浏览器复测）

**P0-18 样本量输入层门 —— 三证据齐，通过。**
1) 反例（红）：`r1-B/review.md:74-77`——OAB 件"差1.5/SD3.2/双侧0.05/90% → 声明60例/组"，复算需 96 例/组、60 例实际把握度 72.8%（另有 BPH 290→132 同族）。
2) 修复：`18ed698b`（三层门：输入层 422＋生成层护栏＋导出门；提交信息载 13 红→13 绿＋前端 4+4 红绿＋live 422 实录）。
3) 浏览器复测：`retest_r8.md` §一（负向探针门实时触发且复算数=96 例/组、正向修正后门消解；导出件 9.1 载修正后声明）；本审计解包 `retest_r8_material/RT8_ID701_preview_export.docx` 实测命中"复算需每组96例；考虑15%脱落放大后每组113例，共226例"（且无"样本量待确认"悬置块）。**证据链完整可复现。**

**P0-24 平台入口幂等 —— 反例与修复齐，复测以叙事为主，通过（附缺口）。**
1) 反例：`06d0b4f3` 提交信息原文"现场 w6-13：8连点零响应=onClick未派发"＋截图 `r6-A/w6-13-平台入口重试.png`（实测显示"建立工作稿失败：方案装配仍有未决设计事实（1项）"，与会话未决事实一致）；**R6-A 测试者的独立报告未归档**（该目录仅 13 张截图），反例的原始台账缺失。
2) 修复：`06d0b4f3`（服务端放行幂等＋GET-first 导航＋remount＋心跳；红先 3+3 测＋live 复验；提交信息另载 rev17/rev18 状态自洽实证）。
3) 浏览器复测：`retest_r6.md` §一三处真实连点探针（建项=恰好1项目、放行=单次版本推进、入口=单次进入）；R7-A 全链截图（`r7-A/w7-04-进入写作平台复测.png` 等）。探针本身**无截图存档**（叙事＋后续轮走通为凭）。

### 1.5 特别核查：第 1 轮"14分钟关闭17条"复测批次 —— 无法核实，且以现存记录衡量疑有水分

- 全仓检索（`关闭17/17 条/十四条/14 分钟/14min/复测批次` 等 8 组模式，范围 runs/、.trellis/、docs/、plans/）：**不存在**"14分钟关闭17条"或近似表述。
- 最近似的两条真实记录：(a) `HANDOFF_1004_PAUSE.md:43`"反馈聚合：**24新缺陷/17开放P0/P1**"——17 是"**开放**"数，不是关闭数；(b) 第 1 轮复测（`retest_r1.md`，10-04 10:03–10:35，约 32 分钟）**实际只浏览器关闭 1 条（⑤）**，另 2 项回归抽查通过；①②④⑥ 明示"未按原路径复跑/未复现，维持账本原状"；同轮"末修订批一"仅具名 3 项（检索条件安全化/500指引/vite脚枪根治，`HANDOFF_1004_PAUSE.md:20,43`）。
- 结论：**任何"第 1 轮已关闭 17 条"的说法都与存档不符**（17 是开放计数）；若该批次指"末修订批一"，其被浏览器复验覆盖的比例很低（3 项具名修复中仅 vite 脚枪有"git diff 实读"证据，检索安全化/500 指引未在 r1 复测中直接验证）。该数字**不得对外引用**。

---

## ② 撰写者导出 docx 解包核验 —— 通过

取样说明：r8-A、r12-A 均无导出目录（第 8/12 轮无撰写席导出），改取基准轮主对象 **`r10-A/export.docx`**（=r11-C/r12-B 的主审件）。

- 完整性：md5 `97728674ffea727d27edb9b91750b472`，与 `r11-C/evidence/R11C11_R10A_AD乳膏_III期_RUX_20261007_1731.docx` **逐字节一致**；25 个 OOXML 成员（document.xml/7 个 header/footer/styles/theme/customXml/docProps），`word/media` 为空（媒体 0 声称 ✓）。
- 真实性：真 WordprocessingML；文本内 `<w:`/`</w:`/`w:rPr`/`richtext`/`xmlns`/`TODO/FIXME` **0 命中**（P0-26 渲染清扫对该件成立）；`&lt;` 3 处为正文合法的 `<`（ALT/AST>2×ULN、eGFR<50）；页脚含"草稿预览·DRAFT PREVIEW·不可用于提交"＋PAGE/NUMPAGES 域、settings updateFields=true；页眉含"MW-III-DD06A563-DRAFT 版本号/草案-1"。
- 篇幅量：非空段落 **306**、`<w:p>` 标签 366、表格 6、正文净字符 **28,942**（CJK 20,861）；封面/版本表/14 章目录结构完整（本审计实测章目录落盘）。
- 计数比对（vs 评审报告）：`【待补齐】`33、骨架 7、`safety@sponsor.example` 5、VZV/水痘 2/2、`草案-1` 1 vs `V1.0` 2、监管管理部门 1、`small_molecule` 1、850 出现 5 处且无 215——与 r12-B/r11-B 记载吻合；**两处 ±1**：受试者 **79**（评审记 78）、rescue **10**（评审记 11），属计数口径微差，不影响判定。
- 生成器指纹：core.xml creator="CMS AI医学经理工作台"、created/modified=2000-01-01（确定性占位）；app.xml "Microsoft Macintosh Word"（底层 Word 模板派生）。属正常产品链特征，非伪装/非伪造。

结论：**通过**（真实性、字数/段落量、结构、页脚域、内部标记零残留均可复现；r12-B"页眉无版本信息"的 P2 与解包不符——版本号在页眉，缺的是日期）。

---

## ③ 单轮测试报告证据链核查（主查 r12，辅查 r1/r8/r10）—— 通过（附 2 处缺口）

- **r12（`retest_r12.md`）**：报告称"全部浏览器操作＋只读 GET 取证"。实测 `retest_r12_material/` 只含 drill 产物＋OCR probe（JSON 内容与报告数字一致：OCR 200/passed=true；drill translation 1033/1033、triage 611.6s、co_resident 0），**`retest_r12_shots/` 为空（0 文件）**；本轮唯一新缺陷（⑥ 幂等继承死路）的"只读 GET（job 状态）"响应**未归档**——证据链依赖报告叙事。相应地，`retest_r11_shots/` 亦为空（P1-45 关闭亦无截图）。
- **r10**：`retest_r10_shots/10-批量冻结行内跳过清单.png` 与报告断言一致（真实产品 UI、KZ-BE204、"以下章节本次未冻结（逐章原因）"逐章点名）——截图真实、可对证。
- **r1**：`retest_r1_material/evidence_entryB.txt` 含 review_ready/898s/10:28:45 全链记录；`ocr_probe_r1*.json` 仅含 502 detail（与"环境验证失败"一致）；`concurrency_drill_summary.json` tr 0/2、co_resident 61（与报告"翻译相全断"一致）。
- **无 API 直推痕迹**：全 loop 目录（排除日志）扫描写动词：`PUT/PATCH/DELETE` **0 命中**；唯一 POST=各轮 `retest_r*_drill.py` 打到产品自身 `/api/ai-gateway/probe`（round26 既有并逐轮披露的并发测试协议，只读探测）。各轮报告的"工具等价披露"（受控输入 value setter/只读 GET 等）粒度诚实。
- 缺口（计入 discrepancies）：r11/r12 零截图；r12 主发现（新缺陷）无截图、无 GET 归档。

---

## ④ 收尾纪律（空间/缓存清理记录）—— 基本通过（附 2 项）

- 12 轮报告均有收尾段（浏览器标签关闭、任务空间清空）；r1–r5 另披露临时文件服务器 5397/5398/5399 用后停；本审计 live 只读核验：**三端口现无监听**。r6-E 报告如实标注 `cleaned=false`（关闭动作完成但零残留未能独立核对）——诚实项，非缺陷。
- 磁盘/缓存清理：loop 窗口（10-04→10-07）内**未见新的清理执行记录**；最近一次为 `cleanup_manifest_20260930.json`（5 个测试项目移除≈687MB 十进制/655MiB，kept 2、unmapped 3；与提交 612ee3b6"655MB freed，DB 行未动"一致）。红线（不清库、不删 DB 行）未见违反。
- 遗留：`frontend/runs/requirements_v2_20260919/t17_round27_loop/impl_slice1/r3e_writing_platform_after_fix.png` 为误落副本（untracked）；5301(pid 6663)/5186(pid 9202) dev 服务仍在运行（现场在役状态，与本轮报告 HEAD 指纹描述一致）。

---

## ⑤ git log f72fa95..HEAD 与账本修复的对应性 —— 部分通过

- 边界与终态：`f72fa95` 为 HEAD 的祖先 ✓；HEAD=`a1b6609d` ✓（与 r11/r12 报告一致）。
- 账本点名的九提交**全部在 log 中**：`a882c6d9 / 1b4c7563 / f37b64e8 / 25563326 / 06d0b4f3 / 1dfde82e / 18ed698b / 0ddfb758 / 0400c3dd`（各轮复测报告的 HEAD 均可在 log 中定位），另含 `c41ad127`（第 1 轮批＋证据）、`a1268ca0`（调度器串行根修）等。
- **缺口 1（对应不完整）**：第 1–5 轮的部分修复**从未提交**，仍是工作树改动："批A②"文控字段确定性抽取（`services/api/app/ai_task_runner.py` +94，10-05 16:09）、"批A④"同文件重传结构化缓存＋取消重放（`medical_writing_synopsis_import.py` +144，10-05 21:54）、翻译忠实度门重设计/422 人话化/stale-running 回收（`writing_reference_translation_batch.py` +221，10-05 22:00）、`writing_reference_repository.py` +8；相配红测亦未提交（`tests/test_mw_synopsis_reupload_cache.py`、`test_mw_translation_stale_running_reclaim.py`、`test_mw_translation_failure_reason_r27.py`…含 1 个 `.wip`）。CLOSURE_REPORT 的"九提交资产清单"**未覆盖这批**；"反例全部先红后绿（每片红测实拍在历次提交与 result 记录）"对这批修复**不成立**（红测本体不在任何提交里）。
- **缺口 2（门状态）**：HEAD 上全库门 FAIL（见 1.3），其中新 pyflakes undefined ×2 属 **HEAD 提交本体**（`medical_writing_repository.py:3510-3511`，冻批功能的字符串注解；运行时因 `from __future__ import annotations`＋函数内局部 import 无险，但门红未清）；其余 70 条失败含工作树未提交状态引起的清单/指纹漂移类（前端清单 71≠87、legacy mutation guard 路由分类缺项等）。LOOP 未声称全库门绿（列为 NEXT_GATE），不能算隐瞒，但**"修复已收口"的对外口径必须扣掉这两块**。

---

## ⑥ 基准轮涉密纪律 —— 仓库侧通过；/tmp 缓存侧与声明不符（有水分）

- **benchmark_real_protocols 未被 git 跟踪** ✓：`git ls-files runs/benchmark_real_protocols` 为空；`.gitignore:38` 命中该目录（含 MANIFEST.json 与两份 briefing/rubric）；MANIFEST 以**指针引用**原文路径（`/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/...`），briefer 明确"绝不复制进本仓库、绝不提交 GitHub"。
- **runs/ 无成型方案/IB 大段原文泄漏** ✓：以 /tmp 提取件为对照抽样 30 条 30–80 字原文句子（协议 15＋IB 15），对全仓文本文件（含 .txt）与 loop 目录＋benchmark 内全部 96 个 docx 做逐字匹配：**0 命中**。评审报告中成型方案的引用均为页码/章节定位＋极短摘要（唯一整句为方案标题，属对照必需）。
- briefing_tester.md（3.3KB）为 IB/公开信息的摘要级提炼，明示"你不知道方案的最终设计"（反拟合设计），未见成段原文；rubric_reviewer.md 为方法学量表。
- **不符项（重点）**：`/tmp/rux_protocol.txt`（205,343B/5,609 行＝方案 V1.3 全文）与 `/tmp/rux_ib.txt`（958,055B/42,740 行＝IB 第 15 版 203 页全文）**截至本次审计仍存在**（mtime 10-06 20:23），与 `r8-C/review.md`"收尾时 /tmp 提取件已删除（涉密缓存不留）"、`r11-B`"仅 /tmp、审后已删"、`r11-C`"/tmp/rux_qa/ 收尾已删除"、`r12-B`"仅存 /tmp、审后删除"的表述**不符**。文件在仓库外（未入 git、未进 GitHub），但属实物资质缓存未按声明清理——建议由 owner 授权后清除（本审计为只读，未处置）。
- 另：未发现任何成型方案/IB 原文进入任何提交（历史检索 0）。

---

## discrepancies（逐条）

1. **"closed=21" 不可复现**：逐条重建=20（第 1–10 轮 19 条＋第 11 轮 P1-45），与 CLOSURE_REPORT"closed 19条（17+P0-06+P0-18）"口径吻合；差 1 条无留痕约定。影响：低（记账）。
2. **"开放 P0/P1=0" 不成立**：至少含 ⑥幂等继承死路（R12 新立案 P1）、【V1】占位（12 轮 P1）、P0-27/P1-48上纸/P0-03/P0-25（挂账）＋基准轮评审立案的 P1 族（r11-B 7 项、r12-B 7 项）。影响：中（对外表述风险）。
3. **"回归 0" 需限定口径**：抽查 2 点口径成立（r12 导出未重复，实为 1/2）；全库门口径不成立（FAIL，70 条未匹配）。影响：中。
4. **第 1 轮"14分钟关闭17条"档案不存在**，且与 r1 记录（关闭 1 条、16 条明示未复跑；"17"实为开放计数）冲突。影响：中（来源不明的数字，禁止引用）。
5. **r11/r12 零截图**；r12 唯一新缺陷无截图、无只读 GET 归档（`retest_r12_shots/` 空、`retest_r12_material/` 无 job 证据文件）。影响：中（末两轮主结论缺一手视觉证据）。
6. **R6-A 独立报告缺失**（`r6-A/` 仅 13 张截图），P0-24 反例仅靠提交信息＋单张截图；P0-24 复测探针亦无截图。影响：低-中。
7. **/tmp 两份涉密提取件未删**（协议全文 205KB、IB 全文 958KB，10-06 20:23 留存至今），与四份报告"审后已删/涉密缓存不留"不符。影响：中-高（舆情/合规性质，仓库外）。
8. **第 1–5 轮部分修复未提交**（含忠实度门重设计、重传缓存、取消重放、stale 回收等，及相配红测；1 个 `.wip`），账本"九提交"未覆盖，红先后绿对这些片不成立；`git clean/reset` 即丢。影响：中-高（可恢复性/可审计性）。
9. **全库门在 HEAD 为红**（70 条未匹配＋selftests blocked＋pyflakes 新 undefined ×2＋sentinel 1；部分失败与工作树未提交状态相关）。影响：中（已列 NEXT_GATE，未隐瞒）。
10. **计数 ±1 两处**（受试者 78→79、rescue 11→10）。影响：低。
11. **r12-B"页眉无版本信息"与解包不符**（页眉含版本号"草案-1"，缺的是日期）。影响：低（评审侧笔误）。
12. **收尾小项**：`frontend/runs/...impl_slice1/…png` 误落副本（untracked）；loop 窗口无磁盘清理执行记录（仅沿袭纪律）。影响：低。

---

## 末行总裁决

**可信度：中**——主体证据（20 条关闭项、逐轮 probe/drill/docx/截图、九提交与三处深查）扎实且多数可独立复现，但三处实质问题（"开放P0/P1=0/closed=21"与记录不符、/tmp 涉密全文缓存未按声明清理、第 1–5 轮部分修复未提交且全库门在 HEAD 为红）使其达不到"高"；未见任何伪造证据或系统状态被测试行为污染的迹象。

---

*审计边界声明：本报告为只读复核产物；除本文件外未改动任何文件与系统状态；/tmp 涉密文件仅读取元数据（大小/行数/首行），未复制内容；所有结论均可按文中路径与命令复核。*
