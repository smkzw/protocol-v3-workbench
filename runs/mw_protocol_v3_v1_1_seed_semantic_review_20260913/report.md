先读最新 AGENTS.md，并核对本次审阅的输入目录与可写边界。输入应与本 prompt 同目录。正在定位审阅包、可写边界和绑定源。已定位审阅包。接下来读取绑定清单、实际结果和可写范围。正在核验源 hash，并解析实际 24 项候选与引用结构。源文件 hash 已对齐。接下来拆出全部 24 项候选，并核对 compiled input 与 identity 的字节差。24 项候选已齐。接着解析 compiled units 与 DOCX XML，做 locator 级对账，不只核对 quote 字符串。接下来在 scratch 写对账脚本：按 locator 核对 quote，并独立解析 DOCX XML，不只信 compiled units。正在 scratch 写独立对账脚本：locator 走 XML、核对 quote/raw，并抽出邻接上下文。15 处 quote 差异需逐条看：先分清是空白/格式，还是 locator 或语义问题。15 处并非 locator 错误，而是从整段截句。接下来核对截句是否丢掉关键上下文，并核对剂量期别标注。剂量期别标注已能在邻接标题对上。接着核对“交叉/盲态”用词、截句丢掉的入排与揭盲上下文，以及 4.0 ml 写法。证据已齐。正在把 24 项覆盖表、可复验 locator 和下游归组写入 `report.md`。独立来源语义审阅已完成。报告：`runs/mw_protocol_v3_v1_1_seed_semantic_review_20260913/report.md`。只写了该目录的 `report.md` 和 `reviewer_scratch/`；原 DOCX、compiled input、outcome 的 hash 未变。未关 Trellis，未做医学/监管或产品验收。

**总判断：** 24 项、49 条引用的 locator 都能在全文 units 和 DOCX XML 对上（34 条整句、15 条真子串）。主干数字（MG-K10、III 期、注射液/皮下、CSU、600→300 mg Q4W 两期两臂、1:1、H1 背景、12–75 岁/≥30 kg）被该历史方案支持。问题不在“引用字符串找不到”，而在把**同一方案的互补成分拆成可点选清单**，并有几处 candidate/reason 补了源没有的词。

**实质问题（可复验）：**
- `anticipated_dose[3]` 写「交叉给药」——源无此设计；继续治疗期是全员转用 MG-K10，不是交叉。
- `anticipated_dose[2]` reason「维持盲态」是推断；正文写明末例完成双盲治疗后揭盲。
- `anticipated_dose[1]` reason 把所引写法说成 `4.0mL`，实际所引是 `4.0ml`。
- `comparator[2]` 截掉「继续治疗期可调背景」和补救治疗，却写成「两组均持续使用」。
- `populations[1]` 丢掉「签署知情同意书时」；`populations[5]` 加上「与成人同期/慢性荨麻疹」，第二引用是其他研究暴露论证。
- 样本量、分层、1:1、规格被塞进人种/对照/途径字段。

源内**没有**互斥剂量、互斥适应症或互斥期别。150 mg/Q2W/哮喘/AD 未进入本试验剂量候选，这一点是对的。

**下游：** 八字段只是资料入口。AI 应先给出一条完整参考建议卡（药物+III期+H1 控制不佳的 CSU+两期两臂给药整表+12–75 岁人群骨架），用户主要确认是否采用该历史参考包；不要让用户在 24 项里单点拼装。终点、时段、排除、补救、揭盲、226 例应进别的设计决策。候选 confidence 不是医学准入。
