# 25研究有界放量·分波计划（waves plan，2026-09-27）

## 一、数据来源与核对（本轮亲跑）

- 25研究清单：`g6_shortlist_proposal.json` 的 `selected`（恰25条，每条自带 `nct_id`/`rank`/`brief_title`），proposal_hash=086a2a3fb1ddd0bc。
- failed项数：`g6_k3_574_mapping.json` 的 `studies`（仅7研究在K3批内有历史条目）。与25研究交集只有3个：NCT02176291=1、NCT03283670=7、NCT03113968=45，**合计53** = 映射文件 `failed_retryable_items_in_selected_scope: 53` ✓（本轮脚本求和复核一致）。
- 范围红线：映射中 replacement_pool 的4个研究（NCT03185819=384、NCT03446846=73、NCT03352453=63、NCT02376257=1，合计521项）**不在本轮25研究放量范围**，按红线3不派发、历史保留。
- 其余22个入选研究在K3批内无历史条目（failed项数=0），属新译。

## 二、分组原则

1. **波1=恢复锚定波**：先派有存量failed项的3个研究（它们已有文档与条目在库，走nct_ids范围限定重试通道，上一波样本NCT02176291已重判confirmed作锚）；53项体量小、可整波核对。
2. **波2-4=新译波**：其余22研究按G6 rank顺序均分（8+7+7），每波≤8研究。
3. 每波之间核对上波结果再放下一波；无进展即停（红线3）。
4. 总计 3+8+7+7=25 研究，4组（≤4组上限）。

## 三、派发组

### 波1（恢复锚定，3研究，存量failed项53）

| nct_id | G6 rank | failed项数 | 简题 |
|---|---|---|---|
| NCT02176291 | 10 | 1 | Incomplete Response in Late-Life Depression（样本，已重判confirmed） |
| NCT03283670 | 18 | 7 | Inhaled Nitrous Oxide for TRD |
| NCT03113968 | 22 | 45 | ELEKT-D: ECT vs. Ketamine |

`NCT02176291 NCT03283670 NCT03113968`

### 波2（新译，8研究，存量failed项0）

| nct_id | G6 rank | 简题 |
|---|---|---|
| NCT03915613 | 1 | Brain Insulin Resistance in Mood Disorders |
| NCT02461927 | 2 | Ketamine for Rapid Treatment of MDD |
| NCT02181231 | 3 | Buprenorphine with TRD in Older Adults |
| NCT03505905 | 4 | Neurosteroid Intervention for Menopausal Depression |
| NCT05193318 | 5 | KAP for Depression in Abstinent Opioid Users |
| NCT02418195 | 6 | miRNAs, Suicide, and Ketamine |
| NCT04821271 | 7 | TS-161 in Treatment-Resistant Depression |
| NCT06309277 | 8 | Single and Multiple Oral Dose Study |

`NCT03915613 NCT02461927 NCT02181231 NCT03505905 NCT05193318 NCT02418195 NCT04821271 NCT06309277`

### 波3（新译，7研究，存量failed项0）

| nct_id | G6 rank | 简题 |
|---|---|---|
| NCT02473289 | 9 | Sirukumab Efficacy and Safety Study |
| NCT03053362 | 11 | THINC-it Vortioxetine |
| NCT03697603 | 12 | Brexpiprazole in MDD |
| NCT02674529 | 13 | Neural Responses Induced by Antidepressants |
| NCT00088699 | 14 | Rapid Antidepressant Effects of Ketamine |
| NCT03726658 | 15 | Zelquistinel in MDD |
| NCT02660528 | 16 | Tocilizumab Augmentation in TRD |

`NCT02473289 NCT03053362 NCT03697603 NCT02674529 NCT00088699 NCT03726658 NCT02660528`

### 波4（新译，7研究，存量failed项0）

| nct_id | G6 rank | 简题 |
|---|---|---|
| NCT03079297 | 17 | Rapid Antidepressant Effects of Leucine |
| NCT03559192 | 19 | JNJ-67953964 in Treatment-Resistant Depression |
| NCT03181529 | 20 | Psilocybin in Major Depressive Disorder |
| NCT02553915 | 21 | Omega-3 Fatty Acids for MDD with High Inflammation |
| NCT02192099 | 23 | GLYX13-C-202 Open Label Extension |
| NCT04244253 | 24 | OPC-64005 Phase 2 in MDD |
| NCT02458690 | 25 | eIMPACT Modernized Collaborative Care |

`NCT03079297 NCT03559192 NCT03181529 NCT02553915 NCT02192099 NCT04244253 NCT02458690`

## 四、核对清单（每波放行前）

- 上波全部研究达到终态（或明确fail-closed上报），无进行中悬挂；
- 上波产生的fidelity_blocked项进入医学门队列（不晋级），confirmed/overturned证据落档；
- 模型调用经编排器（oMLX按需启停），不触碰live 8910/医学监查；
- 任何一波无进展即停，不盲目放下一波。
