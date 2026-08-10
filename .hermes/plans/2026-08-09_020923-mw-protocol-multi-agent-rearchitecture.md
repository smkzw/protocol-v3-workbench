# Protocol 多 Agent 重构 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

> **Execution authority:** 上行是规划 Skill 的兼容头；实际派发、会商、等待、
> fallback 与验收必须在执行时通过最新版全局 Section 12、workflow guard 和
> route manifest，不能把该兼容头解释为绕过当前执行合同。

**Goal:** 按 design-v1.2 建成 Protocol 专属、AI-first、证据可追溯、可生成可提交定稿并通过 Microsoft Word 原生验收的多 Agent 医学写作工作流。

**Architecture:** 应用自有的 StudyDefinition v3、SemanticDocumentRevision、事件、证据、章节合同与不可变产物构成权威控制面；编排内核、存储、编辑器与 Word 回执生产者都通过 PoC 和 adapter 锁定。迁移采用 strangler、项目级 feature flag、shadow read-only 和可回滚切换，不改写旧 immutable rows。

**Tech Stack:** Python/FastAPI/Pydantic、React 19/Vite、当前 TipTap/ProseMirror 对照基线、StoragePort（SQLite/PostgreSQL 候选）、OrchestratorPort（typed facade/LangGraph/MAF 候选）、PoC 后锁定的编辑器与 Word 回执生产者、python-docx 与受控 OOXML、Open XML SDK、Microsoft Word 原生回执。

---

状态：READY_FOR_USER_PLAN_APPROVAL  
计划日期：2026-08-09  
设计基线：design-v1.2  
设计文件：plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md  
设计 SHA-256：321169afc9f33f572b803661b6c6eeb598304267fcb33cdf7de4faf0b00ad0d8  
Ⅱ/Ⅲ期母版 SHA-256：a28e95d738ffad9199eee44a965164d89a04022dbcac7ea01a999bde5cf34f5e  

**DC-018（随本计划待批准的 design-v1.2 澄清）：** design-v1.2 已批准的是
应用自有权威图、可替换调度器和 LangGraph 首选方向；LangGraph 不是事实源，
须通过 P2-G2 才成为 selected adapter。若 PoC 失败，typed facade 只能用于
非发布证明，生产路线须另交 design amendment。用户批准本计划即同时批准此
澄清；实施后将其写入独立不可变 decision record，不长期只靠本计划覆盖设计正文。

## 1. 本计划的授权边界

本计划只规划 Protocol。它不把 CSR、独立 Synopsis 工作流、CTMS、预算、
电子签署或组织会签纳入本图。

- Protocol Summary 是 TP-MA-07 正文“1.方案摘要”，受同一 StudyDefinition
  和 SemanticDocumentRevision 管理。
- Standalone Synopsis 只在 Protocol 四层定稿门通过后提供独立导出窗口；
  它不能独立编辑或创造事实。
- CSR 保持范围外，未来另做需求、事实权威、Agent/Skill、章节合同和验收设计。
- 当前 r17/r18 证据、运行库和旧 immutable rows 保持只读；不得为新实现修补
  或重跑旧任务。
- 医学监查并发工程不在允许写入范围。
- 用户批准本计划前，不执行 Phase 0，不改产品，不启动服务、下载、OCR、
  翻译、模型调用或 Word automation。

## 2. 当前事实基线

### 2.1 已确认状态

- 最新真实 Protocol P0 验收是 NOT_CLEAN，clean streak=0。
- r17 停在 awaiting_corpus_admission 90%，PICOS、全文、DOCX 和 Word 均未到达。
- 一键批量准入曾复活已拒绝的 44 字资格标准引言，且没有
  objectives/endpoints 实质证据。
- 历史 D017 产物虽有 106 个 heading、28 页，但正文约 2,627 字符、
  2 表、0 图，属于骨架失败样例。
- 现有 TP-MA-07 语义树有 124 个节点、110 个叶节点；约 76 个叶节点
  没有确定性章节投影。
- 现有 StudyDefinition 是 medical_writing_study_definition_v2。
- 现有全文生成由 services/api/app/medical_writing_full_draft.py 承担，
  固定 FULL_DRAFT_CHUNK_SIZE=8，校验仍以统一 prompt、长度、占位符和
  evidence span 形态为主。
- 通用 DurableJob 尚无设计要求的 ExecutionReservation unknown_outcome 语义；
  但 `medical_writing_authoring_journey.py` 的 prefill、Paddle OCR 中断处理和
  translation downstream transition 已有局部正确模式，应抽取推广，不能误称
  全仓完全没有，也不能把局部实现冒充统一覆盖。
- 现有前端主文件 frontend/src/App.jsx 约 16,002 行，WritingPage 与编辑器仍
  内嵌其中；MedicalWritingAuthoringJourneySetup.jsx 约 4,161 行。
- 现有 Word receipt 数据合同和 repository 已存在，但历史
  evidence/mw_docx_release_gate_20260727/run_word_native_gate.py 只是一次性
  AppleScript 证据脚本，不是可恢复、可审计、可作为产品节点的回执生产者。
- 当前 workbench 不是 Git repository。实施前必须先建立不可变 source-only
  manifest 和隔离实施区；默认不得在 live workbench 原地 `git init`。
- Ⅰ期模板资产并非缺失，至少存在 TP-MA-05 非肿瘤Ⅰ期、TP-MA-06 肿瘤Ⅰ期
  和 CMSS-SOP-MD-5101-T02-00 候选；缺口是当前权威版本、适用域与双模板
  分流尚未裁定。
- 前端同时存在 package-lock.json、pnpm-lock.yaml 与 pnpm-workspace.yaml；
  package.json 没有 test script，Vitest 未声明。任何 `.test.jsx` 在工具链门
  通过前都不能计为已执行测试。
- 当前 3,878 条公司语料的 semantic_node_id 与 M11 anchor 映射均为 0；
  v2→v3 迁移必须输出 mapped/quarantined/unmapped 对账，不能默认自动成功。

### 2.2 现有资产的保留方式

| 现有资产 | 处理 |
|---|---|
| packages/contracts/workbench_contracts/models.py | 保留旧合同；v3 新合同放独立模块并从 __init__.py 导出 |
| medical_writing_protocol_template.py | 作为节点提取与兼容来源，不继续承载全部新章节合同 |
| medical_writing_research_pipeline.py | 先只读 adapter；Agent①通过新 gate 替代其状态权威 |
| medical_writing_full_draft.py | 旧链保留；新 Agent③经 feature flag strangler |
| medical_writing_repository.py / sqlite_runtime_store.py | 旧读 adapter；shadow 时绝对只读 |
| ai_role_runtime_settings.py / ai_execution_policy.py / ai_gateway.py | 复用配置能力；新增 Protocol NodeExecutionContract 和 reservation 层 |
| TipTap/ProseMirror 现有编辑能力 | 作为编辑器 PoC 基线，不预先认定满足 D011/D012 |
| medical_writing_document_exporter.py | 通过 adapter 复用 exporter，不在早期大改 6,000+ 行文件 |
| medical_writing_word_verification_repository.py | 迁移为新 Word receipt port 的兼容实现 |
| Open XML SDK validator | 保留结构门，但不能替代 Word 原生门 |
| 旧 Journey/Pipeline/Durable Job 状态 | 只做兼容投影，不再成为新链事实源 |

### 2.3 仓库清洁化分类（2026-08-09 只读测量）

“清洁环境”不等于删除历史。当前 `runs/` 约 26 GB、`records/` 约 2.8 GB、
`logs/` 约 182 MB；它们远大于源码，并含 r17/D017、Word PoC、r42 和医学监查
证据。后续实施使用 source-only 隔离区，原 workbench 继续充当只读证据库。

| 类别 | 当前路径/对象 | Phase 0 处理 |
|---|---|---|
| 直接复用 | `medical_writing_protocol_template.py`、`writing_reference*.py`、`chapter_translation_pipeline.py`、`medical_writing_document_exporter.py`、`medical_writing_word_verification_repository.py`、现有 OpenXML 源码/发布二进制及许可、前端表格/xref/durable 原语 | 以 adapter/回归测试保留，不原地重写 |
| 迁移后退役 | `models.py`、`main.py`、`App.jsx`、`styles.css`、Journey/Repository/ResearchPipeline/FullDraft/v2 UI | feature flag 与 shadow 通过前不得删；新功能不得继续堆入巨型文件 |
| 当前权威/永久回归 | design-v1.2、D001–D017、D017 supersession、TP-MA 模板、r17 报告、Word PoC、失败 corpus | byte/hash 固定，旧证据只读 |
| 历史过程归档 | `runs/`、`records/`、`logs/`、`evidence/`、`archives/`、`source_backups/`、`backups/`、嵌套 `implementation/workbench/` | 建索引和路径映射；不复制到隔离源码区，不在 Phase 0 硬删 |
| 可再生清理候选 | `.DS_Store`、非归档 `__pycache__`/`*.pyc`、`.pytest_cache`、`.ruff_cache`、`.vite`、`frontend/dist`、`frontend/.npm-cache`、`.playwright-cli`、`screenlog.0`、OpenXML `bin/Release`/`obj` | 先精确保护 manifest、占用检查、空环境重建；缓存外对象先外部 quarantine，再移出 live；保留发布二进制 |
| 待裁定/隔离 | 根目录 `--indications`、`REPORT.md`、`design-qa.md`、`cms_alignment_worker.md`、`test_worker01_gating.py`、空 `medical_writing_durable_jobs.sqlite3`、双 lockfile | 先引用/hash/来源对账；移动到带映射的 quarantine，不凭“看起来旧”删除 |
| 受保护范围外 | medical monitoring 源码、测试及其多 GB 运行证据 | Protocol 清理任务不得移动或删除 |

当前 `frontend/.npm-cache` 约 188 MB、`frontend/node_modules` 约 151 MB；
`.venv` 约 81 MB 但现有 Python requirements 未闭合。只有新隔离环境可从锁定
依赖重建并通过回归后，才允许清理旧 `.venv`/`node_modules`。

## 3. 实施原则与停止条件

1. 每个编号任务是一个可审阅 work package，并执行“写失败测试→确认失败→
   最小实现→确认通过→检查点”。110 个章节合同以正向医学义务、Word 对象和
   独立复核为完成标准，不设置诱发形式化填表的任意分钟级时间盒。
2. Worker 不能关闭自己的任务。每个 Phase 由 fresh-context verifier 根据
   文件、测试、数据库/事件或真实渲染证据验收。
3. Phase 0 的源码恢复边界失败时停止全部实施。Word receipt producer PoC
   失败时，Phase 1–5 可在显式 `NO_RELEASE` 状态继续；Phase 6–8、
   Final Gate Layer 4 和发布保持阻断，不得降低“可提交定稿”定义或承诺上线。
4. Phase 1 的存储 PoC 未锁定前，领域合同不得依赖 PostgreSQL 私有语义。
5. Phase 2 的 LangGraph PoC 未通过，可用 typed facade 继续非发布证明；正式
   生产路线必须形成 design amendment 并获用户批准，不得为“用了 LangGraph”
   而破坏 exactly-once semantic effect，也不得静默改变已批准设计。
6. Phase 3 的 110/110 non-vacuous registry、DAG 和失败 corpus 未通过，
   Agent③不可启用。
7. E0–E3 未通过，Agent②、Agent③不得消费资料链。
8. D1 未通过，正文不得生成。
9. W1 未通过，Agent④不得给 clean。
10. Q1 与 Word 原生门未通过，不得生成 SubmissionEvidencePackage 或标记
    可提交定稿。
11. 所有 retry、resume、fallback 和 restart 都先查 logical work key；
    unknown_outcome 不得自动重派。
12. 不使用 sleep/固定间隔 controller 轮询；长节点依赖 lease heartbeat 和
    runner hard wait。
13. 每个阶段只写其声明路径。跨模块修改必须在计划中新增影响项并再次审阅。
14. 当前 workbench 缺少 Git；Phase 0 只在 live 目录生成只读 manifest，随后
    复制到隔离实施区。若发现正式上游则使用其 worktree；否则只在隔离副本
    初始化本地 Git。除非用户另行明确指定，live workbench 不创建 `.git`。

## 4. 目标目录与模块边界

以下为拟新增路径；PoC 结论可能改变 adapter 实现，但不能改变领域合同。

    packages/contracts/workbench_contracts/protocol_v3.py
    services/api/app/protocol_workflow/
        __init__.py
        errors.py
        application/
        ports/
        artifacts/
        api/router.py
        canonical/
        storage/
        events/
        runtime/
        registries/
        legacy/
        graph/
        agent1/
        agent2/
        agent3/
        agent4/
        agent5/
        word/
    config/medical_writing/protocol_v3/
        role_registry.json
        skill_registry.json
        templates/tp_ma_07_v1/
        templates/phase1_candidates/
        severity_policy.json
    frontend/src/features/medical-writing/protocol-workbench/
    tests/fixtures/protocol_v3/
    tests/protocol_v3/
    pocs/protocol_v3/
    scripts/qc/protocol_v3/
    deploy/medical_writing_local/protocol_v3/

新包不直接 import main.py 的全局单例；composition root 只在
services/api/app/main.py 和新 router 适配层完成。

## 5. Phase 与硬门总览

| Phase | 交付 | 硬门 |
|---|---|---|
| 0 | 隔离源码区、仓库清洁化、可复现工具链、失败 corpus、Word producer PoC | H0–H6 / P0-CORE / P0-WORD |
| 1 | v3 canonical kernel、repository/event/outbox/reservation、存储决策 | P1-G1 |
| 2 | typed facade / LangGraph / MAF 对照 PoC 与编排锁定 | P2-G2 |
| 3 | TP-MA-07 110/110 Chapter/Skill Contracts；Ⅰ期权威与双模板分流 | P3-G3 |
| 4 | Agent①与 E0–E3 | E0/E1/E2/E3 |
| 5 | Agent②、PICOS-M-A-Opr、推荐卡、Protocol Summary | D1 |
| 6 | Agent③、章节锁/影响传播、A+C、编辑器和选区 AI | W1/UI1 |
| 7 | Agent④、Word 回流、四层门、SubmissionEvidencePackage、Synopsis 导出 | Q1/F1 |
| 8 | shadow、项目级切换、真实 E2E、发布与回滚 | R1 |

不写日历承诺。每个 Phase 只有前一硬门通过后才能开始；未通过时修复当前
门或回到设计决策，不并行堆叠未验证产品层。

# Phase 0 — 隔离源码区、仓库清洁化、失败 corpus 与 Word 可行性

除 Task 0.1 明示的外部 bootstrap/snapshot 路径外，Task 0.1 完成后的所有相对
`Create/Modify/Test` 路径均解析到唯一的 `protocol-v3-workbench-<task_id>`；
原 live workbench 仅以 read-only evidence root 挂接。任何工具把相对路径解析回
live 都必须 fail closed。

### Task 0.1：建立 source-only 可恢复实施边界

**Objective:** 在不改变 live workbench 仓库语义、不纳入 runtime、凭证、真实
资料、环境目录或旧证据库的前提下，建立可审计的隔离实施区。

**Files:**
- Create outside live: /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-bootstrap-<task_id>/build_source_baseline.py
- Create outside live: /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-bootstrap-<task_id>/verify_source_baseline.py
- Create outside live: /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-bootstrap-<task_id>/test_source_baseline.py
- Create outside live: /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-snapshots/<task_id>/
- Create after verification: /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-<task_id>/
- Create after copy inside isolated workspace: scripts/qc/protocol_v3/build_source_baseline.py
- Create after copy inside isolated workspace: scripts/qc/protocol_v3/verify_source_baseline.py
- Create after copy inside isolated workspace: tests/protocol_v3/test_source_baseline.py
- Create only inside isolated workspace: .gitignore

**Micro-steps:**

- [ ] 在 live workbench 运行 `git rev-parse --show-toplevel`；若发现正式上游，
  停止复制路线并使用上游隔离 worktree。
- [ ] workflow guard 先生成唯一 `<task_id>`；bootstrap、snapshot、isolated workspace
  三个目标都必须预先断言不存在，禁止复用旧目录或覆盖。
- [ ] 所有 bootstrap 文件写到 live workbench 外；Task 0.1 对 live 的允许动作只有
  stat/read/hash。创建任何 live 文件即 fail closed。
- [ ] 写失败测试：manifest 只允许根 AGENTS/README/pytest 配置、
  packages/contracts、services/api/app、frontend/src、frontend/tests、tests、
  scripts、tools、config、deploy、本实施计划、design-v1.2、D001–D017，
  以及 `pocs/protocol_v3/` 下扩展名为
  `.py/.mjs/.jsx/.json/.md/.yaml/.yml/.toml/.cs/.csproj/.lock/.txt` 的源码、
  tests、fixtures 和 decision 文本。
- [ ] 明确拒绝 secrets、SQLite/WAL/SHM、runtime、node_modules、dist、cache、
  logs、runs、records、evidence、archives、`pocs/**/results/**`、PoC DOCX/PDF
  和真实临床原文。
- [ ] inventory test 将本计划所有 `pocs/` Create/Test 路径与复制 manifest 对账；
  漏任何计划内源码失败，多入任何 results/binary 也失败。
- [ ] 在外部 bootstrap 目录运行其 test_source_baseline.py；先验证缺实现失败，
  再实现 allowlist、SHA-256、size、mtime、mode、symlink 和 path traversal 检查。
- [ ] 生成 source tar、manifest.json、manifest.sha256；在临时目录解包并重算 hash。
- [ ] 从验证后的 tar 创建唯一 task-id 隔离目录；live 证据仅通过只读 absolute locator
  和 hash catalog 访问，不复制整个历史树。
- [ ] 若无正式上游，只在隔离目录初始化本地 Git 并提交 baseline；不配置 remote。
- [ ] 复制 bootstrap 脚本/测试到隔离 workspace 的计划路径，再运行
  `python3 -m pytest tests/protocol_v3/test_source_baseline.py -q`。
- [ ] 对 live workbench 断言 `.git` 不存在、没有新增文件且 baseline 前后 hash 未变化。

**Checkpoint:** baseline commit（若有）、tar hash、文件计数、排除项和隔离路径
只写入隔离 workspace 的 `runs/mw_protocol_v3_phase0_baseline.md`；live 不写。

### Task 0.2：只读分类仓库并建立 hygiene inventory

**Objective:** 给每个活动文件一个可解释去向，在保留证据与回滚能力的同时，
让后续构建只发生在清洁源码区。

**Files:**
- Create: config/medical_writing/protocol_v3/repository_hygiene_rules.json
- Create: scripts/qc/protocol_v3/classify_repository.py
- Create: scripts/qc/protocol_v3/verify_repository_hygiene.py
- Create: tests/protocol_v3/test_repository_hygiene.py
- Create outside live: /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-snapshots/<task_id>/repository_hygiene_inventory.json

**Micro-steps:**

- [ ] 枚举 path、type、size、mtime、SHA、symlink、生产 import/route、测试引用、
  checkpoint 引用和保护 owner；“静态无引用”不能单独触发删除。
- [ ] 输出 `reuse`、`migrate_then_retire`、`authority_regression`、
  `historical_archive`、`regenerable`、`quarantine`、`protected_out_of_scope` 七类。
- [ ] `runs/records/logs/evidence/archives/source_backups/backups` 只生成 current/cold
  索引和引用关系；本任务不移动或删除任何内容。
- [ ] 嵌套 `implementation/workbench/` 先逐文件 hash，与 canonical records 合并
  的候选关系只记录不执行；未完成前标 `quarantine_blocked`。
- [ ] 未分类路径、同名 hash 冲突、未知 owner、immutable locator 引用都阻断 mutator。
- [ ] 本任务完成后重算 live hash；必须与 Task 0.1 完全一致。

**本任务无 mutator。** 所有清理/移动推迟到 Task 0.5，且必须先通过 Task 0.3、
Task 0.4 和 H0/H1/H2/H4/H5/H6。

### Task 0.3：锁定可复现 Python/前端测试工具链

**Objective:** 新环境能从声明依赖重建并真实执行全部纳入计划的测试，避免
未运行的 `.test.jsx` 被计为绿色。

**Files:**
- Create: services/api/requirements-protocol-v3.in
- Create: services/api/requirements-protocol-v3.lock
- Create: scripts/qc/protocol_v3/verify_toolchain_rebuild.py
- Create: scripts/qc/protocol_v3/run_frontend_checks.py
- Create: config/medical_writing/protocol_v3/toolchain_manifest.json
- Create: frontend/tests/protocol_v3_test_inventory.mjs
- Modify after decision: frontend/package.json
- Modify conditionally when npm selected: frontend/package-lock.json
- Modify conditionally when pnpm selected: frontend/pnpm-lock.yaml
- Quarantine conditionally when npm selected: frontend/pnpm-lock.yaml
- Quarantine conditionally when npm selected: frontend/pnpm-workspace.yaml
- Quarantine conditionally when pnpm selected: frontend/package-lock.json
- Test: tests/protocol_v3/test_toolchain_manifest.py
- Test: tests/protocol_v3/test_frontend_check_wrapper.py

**Micro-steps:**

- [ ] 从生产 import、当前 `.venv`、现有 requirements 和许可证生成 prod/dev/OCR/
  model extras 清单；当前 `.venv` 在闭合前保持只读证据。
- [ ] 对 npm/package-lock 与 pnpm lock/workspace 分别做 clean install、build 和
  existing test inventory；决策记录固定唯一 package manager/lockfile。
- [ ] 若保留现有 `.test.jsx`，核验并固定兼容的开源 Vitest、DOM 环境和 React
  test dependencies，增加 `test:unit`；否则全部转换为可被 Node 直接执行的 `.mjs`。
- [ ] inventory 测试扫描所有 `.test.jsx/.test.mjs`，未被命令收集时失败。
- [ ] `run_frontend_checks.py` 只从冻结 toolchain manifest 读取 package manager、
  lock hash 和 scripts；后续 Phase 禁止直接调用 npm/pnpm。
- [ ] 在全新、排除 `.venv/node_modules/cache` 的目录重建 Python/前端依赖，
  执行最小 backend import、frontend build 和 unit tests。
- [ ] 只有重建成功后，旧 `.venv` 和 `frontend/node_modules` 才进入可清理清单；
  清理失败不影响已验证隔离环境。

**Gate H4–H6：** 唯一依赖锁、唯一前端包管理器、wrapper 覆盖全部测试；新
`protocol_workflow` 包和 Phase 0 工具单纯 import 不得触发 `main.py`、创建
DB/目录或启动 worker，worker 只能由显式 lifespan 启停。旧 `main.py` 的既有
副作用作为迁移风险保留，Phase 8 接线前不得把它引入新 package 测试。

### Task 0.4：冻结权威、可变源码基线与不变对象

**Objective:** 区分“允许按计划修改的源码”与“永远不得被新链改写的旧证据”。

**Files:**
- Create: scripts/qc/protocol_v3/build_frozen_authority_manifest.py
- Create after user approval: plans/mw_protocol_multi_agent_rearchitecture_design_clarification_dc018.md
- Create: tests/fixtures/protocol_v3/mutable_source_baseline.json
- Create: tests/fixtures/protocol_v3/immutable_protected_assets.json
- Create: tests/fixtures/protocol_v3/protected_path_rules.json
- Create outside live: /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-snapshots/<task_id>/immutable_protected_assets.json
- Test: tests/protocol_v3/test_frozen_authority_manifest.py

**Micro-steps:**

- [ ] `mutable_source_baseline` 固定当前产品源码 hash，后续只允许计划声明 diff。
- [ ] 把本计划顶部 DC-018 原文写入独立 decision record，固定 design-v1.2 hash、
  本计划批准 hash、澄清范围和用户批准时间；不得重写原 design-v1.2。
- [ ] `immutable_protected_assets` 至少逐项纳入
  `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`、
  `plans/mw_system_rearchitecture_design_decisions_20260808.md`
  （SHA-256 `04d99dd3cb239c49f5de52d1b0fe0fdd959007def509e0931907614894eb816a`）、
  `runs/MW_PROTOCOL_REARCHITECTURE_DESIGN_READY_FOR_USER_REVIEW_20260809.md`、
  `runs/MW_PROTOCOL_DESIGN_D017_SCOPE_SUPERSESSION_20260809.md`、
  `runs/role_acceptance/mw_protocol_p0_20260805_round17_engineer_cursor_full_protocol_semantic_span_selection.md`、
  `evidence/mw_docx_release_gate_20260727/`、全部 TP-MA/CMSS-SOP 模板候选、
  `runtime/` 和旧 immutable SQLite/JSONL。
- [ ] medical monitoring owner 的 deny-mutation 规则至少覆盖
  `services/api/app/monitoring_*`、`tests/test_monitoring_*`、
  `runs/execution/monitoring_*`、`records/**/monitoring*` 及其实际解析出的依赖；
  不能只靠目录名模糊匹配。
- [ ] 每个 protected rule 固定 absolute locator/pattern、resolved paths、hash、owner、
  allowed=`read_only` 和 reference count；未分类、无 owner 或 pattern 未解析即失败。
- [ ] 对 SQLite 同时记录 logical table counts、schema、integrity_check 与文件 hash；
  WAL/SHM 物理差异不得冒充逻辑差异。
- [ ] comparator 对未知源码 diff、旧 row/表写入或受保护路径变化 fail closed。
- [ ] 用临时副本验证 comparator 能发现一条 row 变化和一个未声明源码变化。
- [ ] 运行 `python3 -m pytest tests/protocol_v3/test_frozen_authority_manifest.py -q`。

### Task 0.5：执行可恢复的必要 hygiene

**Objective:** 在保护清单和可复现重建全部通过后，清理确定性缓存并把确需移出
live 根目录的早期过程文件放入 workbench 外的可恢复 quarantine。

**Files:**
- Create: scripts/qc/protocol_v3/apply_repository_hygiene.py
- Create: scripts/qc/protocol_v3/evidence_locator_resolver.py
- Create: tests/protocol_v3/test_repository_hygiene_mutator.py
- Create outside live: /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-quarantine-<task_id>/PATH_MAP.json
- Create outside live: /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-quarantine-<task_id>/objects/

**Preconditions:** H0、H1、H2、H4、H5、H6 已通过；用户批准本实施计划；
immutable_protected_assets 无 unresolved；quarantine 目标预先不存在。

**Micro-steps:**

- [ ] mutator 启动时重新检查 8910/8911/5173/5174 监听、相关进程以及
  SQLite/WAL/SHM/目标文件占用；任何占用都使对应目标跳过并记录 blocker。
- [ ] `.DS_Store`、非归档 `__pycache__`/pyc、`.pytest_cache`、`.ruff_cache`、
  `.vite` 只有在规则明确、无引用且隔离环境已重建后才可直接删除。
- [ ] `frontend/dist`、`.playwright-cli`、`screenlog.0`、deploy logs、
  `frontend/.npm-cache`、OpenXML `bin/Release`/`obj` 先 copy→hash verify→PATH_MAP；
  只有确认不是唯一运行/发布证据且 resolver 可还原 locator 后才移出 live。
- [ ] 旧 `.venv`/`frontend/node_modules` 只有在新隔离环境完成同版本全基线且
  rollback rehearsal 通过后，才可整体移到外部 quarantine；不得直接删除，
  不得在旧系统仍被使用时移动。
- [ ] 根目录早期报告/worker、空 DB、lockfile 和嵌套 workbench 默认不动；只有
  inventory 明确 `quarantine_approved`、无 immutable locator 依赖时才使用同一流程。
- [ ] `runs/records/logs/evidence/archives/runtime/source_backups/backups` 和医学监查
  路径本任务禁止移动/删除；它们只从隔离源码区排除。
- [ ] 每个 move 使用 source hash、destination hash、old/new locator、owner、reason
  和恢复命令；目标同名不同 hash 时 fail closed，绝不覆盖。
- [ ] 执行后验证 source allowlist hash、protected byte/logical manifest、医学监查
  deny-mutation 和 live locator resolver；任一差异立即按 PATH_MAP 恢复并失败。
- [ ] 本计划批准只授权上述 manifest 内目标；新增类别、硬删非再生历史或移动
  受保护对象需要单独审阅和用户授权。

**H0–H6 predicates：**

| Gate | Predicate | Evidence | Owner |
|---|---|---|---|
| H0 Inventory | live 全路径已分类，unknown/unowned=0，occupancy 已记录 | repository_hygiene_inventory.json | Phase 0 worker，verifier 验收 |
| H1 Protected | authority/r17/D017/runtime/医学监查绝对路径、hash、owner、逻辑 DB 指纹齐全 | immutable_protected_assets.json | Codex final authority |
| H2 Source | 外部 snapshot 与隔离源码区 allowlist hash 100% 一致，live 无新增/变化 | source manifest/tar hash | fresh verifier |
| H3 Recoverable hygiene | 每个移动 copy/hash/PATH_MAP/resolver/restore 通过，source/protected delta=0 | quarantine manifest + restore rehearsal | fresh verifier |
| H4 Dependency | Python 与唯一前端 lock 可在空环境重建 | toolchain manifest + install logs | toolchain verifier |
| H5 Test discovery | 所有计划内 backend/frontend tests 被唯一命令发现并执行 | test inventory + exit codes | independent test verifier |
| H6 Side effects | 新 package/tool import 不写盘、不启动 worker；lifespan 可确定性关停 | fault-injection report | backend verifier |

### Task 0.6：建立永久失败 corpus 与跨层回归身份

**Objective:** 把历史缺陷变成不可删除、可执行、可定位的负向合同。

**Files:**
- Create: tests/fixtures/protocol_v3/failure_corpus/manifest.json
- Create: tests/fixtures/protocol_v3/failure_corpus/r17_thin_eligibility.json
- Create: tests/fixtures/protocol_v3/failure_corpus/heading_only.json
- Create: tests/fixtures/protocol_v3/failure_corpus/generic_long_body.json
- Create: tests/fixtures/protocol_v3/failure_corpus/empty_protocol_d017.json
- Create: tests/fixtures/protocol_v3/failure_corpus/zero_registry_result.json
- Create: tests/fixtures/protocol_v3/failure_corpus/batch_reject_resurrection.json
- Create: tests/fixtures/protocol_v3/failure_corpus/unknown_outcome.json
- Create: tests/fixtures/protocol_v3/failure_corpus/checkpoint_event_split_brain.json
- Create: scripts/qc/protocol_v3/build_failure_corpus.py
- Test: tests/protocol_v3/test_failure_corpus.py
- Test later: tests/protocol_v3/integration/test_r17_reject_survives_accept_all_restart.py
- Test later: tests/protocol_v3/integration/test_d017_skeleton_fails_word_positive_path.py

**Micro-steps:**

- [ ] 从耐久 r17 报告和保留 service evidence 重建 44 字/无 objectives 最小事实；
  manifest 必须标 `provenance=evidence_reconstructed`，不得声称恢复了已消失的
  `/private/tmp/mw-p0-engineer-r18.fWUe1r` 原始 runtime。
- [ ] 从 D017 骨架提取 106 headings、约 2,627 字符、2 表、0 图、hash 和受控
  片段；不复制整个历史目录。
- [ ] 每个 fixture 固定 failure_code、source_locator、expected_gate、owner、
  provenance 和不可通过理由。
- [ ] 增加短但包含目标 claim、locator、上下文和合法 source role 的正对照，
  避免把长度重新变成代理指标。
- [ ] manifest 缺任何类、改 expected、标 xfail 或删除跨层 identity 时失败。
- [ ] 运行 `python3 -m pytest tests/protocol_v3/test_failure_corpus.py -q`。

### Task 0.7：定义 Word 原生回执 PoC 合同

**Objective:** 先定义机器可判定的原生 Word 成功标准，再比较生产者路径。

**Files:**
- Create: pocs/protocol_v3/word_receipt/README.md
- Create: pocs/protocol_v3/word_receipt/contract.py
- Create: pocs/protocol_v3/word_receipt/fixtures.json
- Create: pocs/protocol_v3/word_receipt/tests/test_receipt_contract.py
- Reuse read-only: evidence/mw_docx_release_gate_20260727/run_word_native_gate.py

**Receipt 最小字段：**

    receipt_id
    source_snapshot_sha256
    input_docx_sha256
    semantic_document_revision
    template_revision
    word_application_version
    os_and_font_environment
    open_without_repair
    field_count_before
    field_count_after
    toc_count
    bookmark_checks
    cross_reference_checks
    saved_docx_sha256
    reopen_pass
    pdf_sha256
    page_evidence
    normalized_ooxml_fingerprint
    edit_reimport_export_lineage
    started_at
    completed_at
    producer_identity
    idempotency_key

**Micro-steps:**

- [ ] 缺 reopen、bookmark/ref、PDF 页面证据或 OOXML 指纹的历史 trace 不得升级。
- [ ] LibreOffice、HTML preview 或仅可下载 DOCX 不能标 microsoft_word verified。
- [ ] source snapshot、template、semantic revision 或 DOCX hash 变化使 receipt stale。
- [ ] 外部编辑必须形成新 immutable artifact/revision，不覆盖源。
- [ ] 页面证据依赖另做许可证核验；现有 PyMuPDF 脚本不能自动成为生产依赖。
- [ ] 运行 `python3 -m pytest pocs/protocol_v3/word_receipt/tests -q`。

### Task 0.8：比较 Word receipt producer 候选

**Objective:** 在目标 macOS 工作站证明至少一条可恢复、可审计的真实 Word
路径；不预先锁定 AppleScript、add-in 或其他 bridge。

**Files:**
- Create: pocs/protocol_v3/word_receipt/producers/base.py
- Create conditionally: pocs/protocol_v3/word_receipt/producers/applescript_bridge.py
- Create conditionally: pocs/protocol_v3/word_receipt/producers/word_addin_bridge/
- Create: pocs/protocol_v3/word_receipt/run_matrix.py
- Create: pocs/protocol_v3/word_receipt/decision.md
- Create at runtime only: pocs/protocol_v3/word_receipt/results/

**代表样本：** TP-MA-07、D017 骨架、CMS-UC-301 完整方案，以及长表、横向
SoA、图表目录、书签、REF/PAGEREF、页眉页脚、分节、批注/修订样本。

**Micro-steps:**

- [ ] 核验 bridge 代码许可证、Word 自动化边界、辅助权限、桌面会话、失败恢复、
  用户已打开文档隔离、数据路径和部署约束。
- [ ] 先执行 dry-run inventory，不修改 Word 文档。
- [ ] 只在任务副本执行 open→update fields/TOC→bookmark/ref→save→close→
  reopen→PDF→page evidence→OOXML fingerprint。
- [ ] 相同 idempotency key 重放复用 receipt，不重复编辑；update 后强停再恢复
  不得重复改变文档。
- [ ] 执行 export→外部 wording-only 编辑→reimport→export，验证 lineage。
- [ ] decision.md 记录每个候选 PASS/FAIL、版本/许可、证据、残余风险、回滚。

**Gate P0-CORE / P0-WORD：**

- `P0-CORE`：H0–H6、双 manifest 和永久 failure corpus 全通过，才可进入 Phase 1。
- `P0-WORD`：至少一个 producer 通过全部合同，失败路径 typed/recoverable，真实
  Word PDF、页面证据和 OOXML 指纹齐备，且源文件未改。
- 若 `P0-WORD` 未通过，标记 `NO_RELEASE_WORD_BLOCKED`；允许 Phase 1–5，
  但 Phase 6–8、Final Gate Layer 4 和发布阻断。
- 不得用人工口头确认或降级合同把 `P0-WORD` 改成 PASS。

# Phase 1 — Canonical 内核、存储、事件与执行纪律

### Task 1.1：新增独立 Protocol v3 合同模块

**Objective:** 将新领域模型从 11,973 行旧 models.py 中分离，保持旧 API 兼容。

**Files:**
- Create: packages/contracts/workbench_contracts/protocol_v3.py
- Modify: packages/contracts/workbench_contracts/__init__.py
- Test: tests/protocol_v3/test_contract_models.py

**最小合同组：**

- ResearchSeed / NormalizedResearchSeed
- SourceAcquisitionPlan / SourceArtifact / EvidenceUnit / MedicalAdmissionUnit
- ClaimEvidenceLink / RecommendationOption / DecisionRecord
- StudyDefinitionV3 / ApplicabilitySnapshot
- ChapterContract / SubstantiveContentContract / SemanticBlock
- SemanticDocumentRevision / ChapterLockSnapshot
- SkillDefinition / NodeExecutionContract / ExecutionReservation
- WorkflowRun / DomainEvent / ProjectionArtifact / SubmissionEvidencePackage

**Micro-steps:**

- [ ] 为所有模型启用 extra=forbid、显式 schema_version、稳定 ID 和 timezone。
- [ ] 写无效状态、部分 identity、坏 SHA、重复 ID、未知 evidence_class 的失败测试。
- [ ] 写 material hash 测试，证明 display progress、更新时间和 journey counter
  不改变 canonical hash。
- [ ] 写 raw→normalized→proposed→confirmed→frozen→superseded/quarantined
  合法/非法转换测试。
- [ ] 运行 python3 -m pytest tests/protocol_v3/test_contract_models.py -q。
- [ ] 运行现有 tests/test_medical_writing_study_schema.py 与
  tests/test_medical_writing_document_session.py，预期无回归。

### Task 1.2：建立稳定错误码

**Objective:** 所有 gate/对象/原因可定位且不依赖自由文本。

**Files:**
- Create: services/api/app/protocol_workflow/errors.py
- Test: tests/protocol_v3/test_error_codes.py

**Micro-steps:**

- [ ] 实现 MW-PRO-GATE-OBJECT-CAUSE 解析器和 typed exception。
- [ ] 枚举 Phase 0–8 已知错误，至少覆盖 E0/E1/E2/E3/D1/W1/Q1/F1、
  CAS、STALE、UNKNOWN_OUTCOME、CHECKPOINT_EVENT_MISMATCH、WORD_RECEIPT_STALE。
- [ ] 测试未知 code、缺 owner、缺 retryability、缺 object_id 均失败。
- [ ] UI public_message 与 audit detail 分离；public_message 不泄露路径、prompt 或凭证。

### Task 1.3：定义 repository、artifact 和 unit-of-work ports

**Objective:** 让临床领域合同不依赖 SQLite/PostgreSQL 私有行为。

**Files:**
- Create: services/api/app/protocol_workflow/ports/repositories.py
- Create: services/api/app/protocol_workflow/ports/artifacts.py
- Create: services/api/app/protocol_workflow/ports/unit_of_work.py
- Create: services/api/app/protocol_workflow/storage/memory.py
- Create: services/api/app/protocol_workflow/artifacts/local_store.py
- Test: tests/protocol_v3/test_repository_contract.py
- Test: tests/protocol_v3/test_artifact_store.py

**Micro-steps:**

- [ ] 定义 get-current、append-event、CAS-save、outbox/inbox、reservation、
  artifact put/get-by-hash 和 read-model ports。
- [ ] 用 in-memory fake 跑 repository contract tests。
- [ ] artifact 相同 content hash 重放返回同一 identity；不同内容创建 revision。
- [ ] 禁止 Agent/harness 直接获得 repository 实例；只允许 application service。
- [ ] 运行对应两个测试文件。

### Task 1.4：实现 canonical reducers 与 CAS

**Objective:** StudyDefinition v3 成为唯一事实源，SemanticDocumentRevision
成为唯一文字/结构/版式工作版本。

**Files:**
- Create: services/api/app/protocol_workflow/canonical/hashing.py
- Create: services/api/app/protocol_workflow/canonical/study_definition.py
- Create: services/api/app/protocol_workflow/canonical/decisions.py
- Create: services/api/app/protocol_workflow/canonical/document.py
- Test: tests/protocol_v3/test_study_definition_reducer.py
- Test: tests/protocol_v3/test_semantic_document_reducer.py
- Test: tests/protocol_v3/test_decision_cas.py

**Micro-steps:**

- [ ] 写相同 decision_id+snapshot_hash+expected revision 重放只返回原记录的测试。
- [ ] 写 stale expected revision、相同 key 不同 payload、冻结事实覆盖的失败测试。
- [ ] 实现 pure reducer；数据库只保存 reducer 的事件与投影。
- [ ] Protocol Summary、SoA、表图、正文块只引用 fact revision，不复制事实权威。
- [ ] 测试自由文本变更若触及受保护事实，必须产出 fact proposal。

### Task 1.5：实现 domain event、transactional outbox/inbox

**Objective:** event 与 artifact 是业务权威；checkpoint 只代表执行位置。

**Files:**
- Create: services/api/app/protocol_workflow/events/models.py
- Create: services/api/app/protocol_workflow/events/store.py
- Create: services/api/app/protocol_workflow/events/outbox.py
- Create: services/api/app/protocol_workflow/events/inbox.py
- Create: services/api/app/protocol_workflow/events/unit_of_work.py
- Test: tests/protocol_v3/test_event_outbox_atomicity.py
- Test: tests/protocol_v3/test_event_replay.py

**Micro-steps:**

- [ ] 写 event committed/checkpoint missing 的注入测试；resume 从 event 重建。
- [ ] 写 checkpoint completed/event missing 的注入测试；必须 quarantine。
- [ ] 写 outbox 已发但回写前崩溃测试；inbox key 阻止重复 semantic effect。
- [ ] 写未知 event schema/upcaster 测试；必须 quarantine。
- [ ] replay 后 canonical hash 与原投影一致。

### Task 1.6：实现 ExecutionReservation

**Objective:** 把模型、CLI、下载、导出等长副作用统一到 completed/failed/
unknown_outcome 纪律。

**Files:**
- Create: services/api/app/protocol_workflow/runtime/reservations.py
- Create: services/api/app/protocol_workflow/runtime/idempotency.py
- Test: tests/protocol_v3/test_execution_reservations.py

**Micro-steps:**

- [ ] 先把 `medical_writing_authoring_journey.py` prefill、Paddle OCR outcome
  unknown 和 translation downstream transition 的局部正确语义固化为对照测试。
- [ ] 写 completed 相同 input hash 复用测试。
- [ ] 写 timeout/no transport receipt→unknown_outcome 测试。
- [ ] 写 restart 对 unknown_outcome 不重派测试。
- [ ] 写 same-session/provider recovery 找回 output 后完成同一 reservation 的测试。
- [ ] 写显式 retry decision 创建新 attempt、保留旧 reservation 的测试。
- [ ] 写 fallback 不携带上一 provider scratchpad/raw sensitive payload 的测试。

### Task 1.7：建立 Role、Skill、Harness Registry

**Objective:** 四类产品 AI 与 Agent App/CLI 都通过版本化、最小输入的
NodeExecutionContract 运行。

**Files:**
- Create: config/medical_writing/protocol_v3/role_registry.json
- Create: config/medical_writing/protocol_v3/skill_registry.json
- Create: services/api/app/protocol_workflow/registries/loader.py
- Create: services/api/app/protocol_workflow/runtime/harness.py
- Create: services/api/app/protocol_workflow/runtime/adapters/direct_api.py
- Create: services/api/app/protocol_workflow/runtime/adapters/local_omlx.py
- Create conditionally: services/api/app/protocol_workflow/runtime/adapters/codex_app.py
- Create conditionally: services/api/app/protocol_workflow/runtime/adapters/omp_cli.py
- Test: tests/protocol_v3/test_registry_loading.py
- Test: tests/protocol_v3/test_harness_policy.py

**Micro-steps:**

- [ ] 映射 LLM、OCR AI、Translation AI、OCR/Translation Support AI；
  thinking 仅 LLM/Support 可配置。
- [ ] 当前用户目标 profile 记录为：LLM/Support=`deepseek-v4-flash` effort=max，
  OCR=`PaddleOCR-vl-1.6` 官方服务，Translation=`dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX`；
  凭证不进 registry，实际 identity 以运行时 receipt 为准。
- [ ] OCR/翻译仍遵循执行时最新版共享 workload gate。若 declared product role 与
  gate effective model 不一致，fail closed 并先完成 gate/role policy 对账；不得
  静默用 GLM-OCR 冒充 PaddleOCR，或绕过 lease/heartbeat。
- [ ] 每个 Skill 固定 typed I/O、allowed tools/paths、evidence gate、
  side effects、error codes、prompt/tool versions 和 test set。
- [ ] 验证 provider/region/sensitivity allowlist，禁止凭证进入 prompt/checkpoint。
- [ ] Codex/OMP/CLI adapter 只收 artifact refs 和最小片段，输出 typed artifact。
- [ ] 移除新链中的 max_turns=1；等待按当前全局 runner 合同执行。
- [ ] adapter 首次使用必须先做连通性探针，失败后才按 manifest fallback。

### Task 1.8：目标存储 PoC 与锁定

**Objective:** 比较 PostgreSQL 与现有 SQLite adapter，不让数据库选择污染领域合同。

**Files:**
- Create: pocs/protocol_v3/storage/contract_suite.py
- Create: pocs/protocol_v3/storage/sqlite_adapter.py
- Create conditionally: pocs/protocol_v3/storage/postgres_adapter.py
- Create: pocs/protocol_v3/storage/decision.md
- Create after selection: services/api/app/protocol_workflow/storage/selected.py
- Create after PostgreSQL selection: services/api/app/protocol_workflow/storage/postgres.py
- Create after PostgreSQL selection: deploy/medical_writing_local/protocol_v3/migrations/
- Test: tests/protocol_v3/test_selected_storage_contract.py

**PoC matrix：**

- migration accuracy；
- CAS/concurrent writers；
- transaction+outbox；
- event replay/checkpoint isolation；
- backup/restore；
- crash recovery；
- encryption/secret placement；
- local/private deployment；
- rollback to pre-switch snapshot。

**量化阈值（选择前冻结，不因结果改 expected）：**

- 8 个独立 writer、1,000 个 Decision/CAS 操作、10,000 个 DomainEvent：
  lost update=0、重复 semantic effect=0、hash-chain break=0；
- 同一 repository contract 在 memory、SQLite、PostgreSQL 候选上结果一致；
- migration logical count/hash=100%，所有不能映射对象进入显式 quarantine；
- committed event RPO=0，10×当前 Protocol 参考规模的 backup→restore→replay
  在 15 分钟内完成，canonical hash 完全一致；
- 本地 CAS p95 ≤500 ms；若不能满足，决策记录必须解释真实用户影响；
- 未安装 driver/migration stack 不是 PostgreSQL PASS，部署复杂度和回滚必须实测。

### Task 1.9：建立 application service、Agent⑤控制面与 v3 API 骨架

**Objective:** 让 Agent⑤通过唯一 command/query 面统筹任务、版本、Gate、异常卡和
用户交互，但永远不能直接改临床事实、降低 Gate 或替代 Agent④。

**Files:**
- Create: services/api/app/protocol_workflow/application/commands.py
- Create: services/api/app/protocol_workflow/application/queries.py
- Create: services/api/app/protocol_workflow/application/service.py
- Create: services/api/app/protocol_workflow/agent5/coordinator.py
- Create: services/api/app/protocol_workflow/agent5/run_manifest.py
- Create: services/api/app/protocol_workflow/agent5/exception_cards.py
- Create: services/api/app/protocol_workflow/api/schemas.py
- Create: services/api/app/protocol_workflow/api/router.py
- Create: frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs
- Test: tests/protocol_v3/test_application_service.py
- Test: tests/protocol_v3/test_agent5_authority_boundary.py
- Test: tests/protocol_v3/test_protocol_v3_api_contract.py

**Micro-steps:**

- [ ] mutation 一律要求 project_id、expected_revision、idempotency_key、actor 和
  reason/DecisionRecord；GET/query 在 read-only store 上无写副作用。
- [ ] Agent⑤只拆解任务、调度已注册 Skill、聚合 Gate/版本/证据和生成问题卡。
- [ ] 写 Agent⑤尝试直接修改 StudyDefinition、改 severity、跳 Gate 的失败测试。
- [ ] 建立 `/api/projects/{project_id}/protocol-workflow` skeleton、OpenAPI schema、
  project isolation 和 stable error envelope。
- [ ] Phase 4–7 每个新能力必须同任务补 endpoint/client contract；Phase 8 不是首次接线。

### Task 1.10：实现 v2→v3 dry-run migration、quarantine 与单向 cutover

**Files:**
- Create: services/api/app/protocol_workflow/legacy/migration_inventory.py
- Create: services/api/app/protocol_workflow/legacy/migration_map.py
- Create: services/api/app/protocol_workflow/legacy/quarantine.py
- Create: services/api/app/protocol_workflow/legacy/cutover_state.py
- Create: services/api/app/protocol_workflow/legacy/mutation_route_inventory.py
- Create: services/api/app/protocol_workflow/legacy/mutation_guard.py
- Create: config/medical_writing/protocol_v3/v2_v3_mapping.json
- Test: tests/protocol_v3/test_v2_v3_migration_dry_run.py
- Test: tests/protocol_v3/test_v2_v3_migration_idempotency.py
- Test: tests/protocol_v3/test_legacy_read_parity.py
- Test: tests/protocol_v3/test_legacy_mutation_guard.py

**Micro-steps:**

- [ ] 逐字段/表/identity 映射 StudyDefinition v2、Journey、working copies、
  corpus/evidence、decisions、documents 与 artifact lineage。
- [ ] dry-run 输出 source_count、mapped、quarantined、unmapped、hash 和原因；
  3,878 条未映射语料不得静默丢弃或伪造 semantic node。
- [ ] 重复 migration 使用同一 key 不产生新对象；source revision 变化才建新 lineage。
- [ ] cutover 状态固定 `LEGACY_ACTIVE→SHADOW_READ_ONLY→NEW_CANONICAL`；进入
  NEW_CANONICAL 后 legacy 永久只读。
- [ ] 枚举全部旧 `/medical-writing` mutation route 及底层 service mutator；
  NEW_CANONICAL 项目在 route 和 service 两层均返回稳定 fail-closed error。
- [ ] 回滚只关闭新 command 接入并保留/重放新事件；恢复 legacy 事实写入需要
  单独逆迁移设计、对账和用户专门授权，不能由 feature flag 自动完成。

### Task 1.11：建立安全与跨项目隔离矩阵

**Files:**
- Create: config/medical_writing/protocol_v3/security_policy.json
- Create: tests/protocol_v3/security/test_prompt_injection_is_data.py
- Create: tests/protocol_v3/security/test_url_and_path_policy.py
- Create: tests/protocol_v3/security/test_cross_project_artifact_isolation.py
- Create: tests/protocol_v3/security/test_checkpoint_and_secret_leak.py
- Create: tests/protocol_v3/security/test_fallback_payload_minimization.py

**Micro-steps:**

- [ ] 恶意文档/网页/Protocol 中的指令只能作为证据文本，不能改变 workflow/Skill。
- [ ] 拒绝未允许 schema、loopback/metadata/private-network SSRF、path traversal、
  symlink escape 和跨项目 hash/ID 访问。
- [ ] prompt、checkpoint、trace、fallback 和 SubmissionEvidencePackage 扫描凭证、
  不必要原文、provider scratchpad 与本地敏感路径。
- [ ] provider/region/sensitivity policy 在调用前 fail closed；fallback 仅携带最小
  typed artifact refs 和必要片段。

**Gate P1-G1：**

- canonical/repository/event/reservation tests 全通过；
- application service/API、Agent⑤ authority boundary、migration/security tests 全通过；
- selected storage 决策记录含量化结果、许可证、版本、失败证据与回滚；
- legacy store 未写；
- artifact/event replay 可重建相同 hash；
- P0-CORE 仍有效；P0-WORD 失败时保持 `NO_RELEASE_WORD_BLOCKED`；
- 未通过则停留在 repository abstraction，不开始 Phase 2。

# Phase 2 — OrchestratorPort 对照 PoC 与编排锁定

design-v1.2 将 LangGraph 作为首选可替换调度器，同时又要求 PoC。实施解释为：
产品领域图和恢复合同已经批准，LangGraph 是首选候选而非事实权威；只有 P2-G2
通过后才成为 selected adapter。若失败，可继续 typed facade 证明领域能力，但
生产路线必须形成 design amendment 并经用户批准，不能静默偏离 design-v1.2。

### Task 2.1：定义三条高风险 PoC 流程

**Objective:** 用真实设计难点而非 toy chat 评估编排器。

**Files:**
- Create: pocs/protocol_v3/orchestrator/cases/eligibility.py
- Create: pocs/protocol_v3/orchestrator/cases/objective_estimand_endpoint.py
- Create: pocs/protocol_v3/orchestrator/cases/sample_size.py
- Create: pocs/protocol_v3/orchestrator/fakes.py
- Test: pocs/protocol_v3/orchestrator/tests/test_case_contracts.py

**Micro-steps:**

- [ ] 每个 case 只使用 typed services、immutable artifacts 和 deterministic fakes。
- [ ] 为每个节点定义 precondition、output schema、side effect key、Gate 和 owner。
- [ ] 写 kill-before、kill-after、duplicate resume、concurrent decision 和 old graph
  migration 注入点。
- [ ] 写 branch/project isolation 测试。

### Task 2.2：实现现有 typed facade 对照

**Files:**
- Create: pocs/protocol_v3/orchestrator/typed_facade.py
- Test: pocs/protocol_v3/orchestrator/tests/test_typed_facade.py

**Micro-steps:**

- [ ] 以当前 execution loop 实现三 case。
- [ ] 记录代码量、恢复语义、可观测性、事件/副作用重复和迁移成本。
- [ ] 强制 kill 后重启；确认每个 logical work key 一个有效 artifact lineage。

### Task 2.3：实现 LangGraph 候选

**Files:**
- Create conditionally after license pin: pocs/protocol_v3/orchestrator/langgraph_candidate.py
- Create: pocs/protocol_v3/orchestrator/langgraph_state.py
- Test: pocs/protocol_v3/orchestrator/tests/test_langgraph_candidate.py

**Micro-steps:**

- [ ] 验证当前官方版本、MIT 许可证、checkpoint/interrupt/send/subgraph 行为。
- [ ] graph state 仅保存 IDs、hashes、small typed state；不保存凭证/IB 原文。
- [ ] 所有 side effect 在 idempotent task/reservation 内。
- [ ] 重放时从 event 重建，不信任 checkpoint completion。
- [ ] fresh Agent④ reviewer 使用新 execution identity，不继承 writer scratchpad。

### Task 2.4：实现 MAF 候选

**Files:**
- Create conditionally after license pin: pocs/protocol_v3/orchestrator/maf_candidate.py
- Test: pocs/protocol_v3/orchestrator/tests/test_maf_candidate.py

**Micro-steps:**

- [ ] 核验 MAF 的正式身份、当前官方版本、许可证、维护状态和本地私有化约束；
  不满足可商业使用的开源门时记录 `INELIGIBLE`，不安装、不执行。
- [ ] 若 eligible，以同一 cases、fakes、kill matrix、event/replay 和 reviewer
  isolation 合同实现，不为候选修改 expected。
- [ ] 记录依赖体积、迁移、checkpoint 暴露、可观测性和退出成本。

### Task 2.5：比较并锁定编排器

**Files:**
- Create: pocs/protocol_v3/orchestrator/decision.md
- Create after selection: services/api/app/protocol_workflow/graph/runtime.py
- Test: tests/protocol_v3/test_graph_runtime_contract.py

**Gate P2-G2：**

- 三 case 的 kill/retry/fallback/replay 均无重复 semantic effect；
- old graph/schema 不可迁移时 fail closed；
- event/checkpoint split-brain 可定位、可恢复；
- reviewer isolation 可证明；
- typed facade、LangGraph、eligible MAF 使用同一测试与证据矩阵；
- LangGraph 只有在比 typed facade 明显改善恢复/可维护性且无新不变量破坏时锁定；
- Agent⑤ coordinator 只通过 selected OrchestratorPort 调度，不读取候选私有状态；
- 若 LangGraph 失败，保留 typed facade 继续非发布实现，并提交 design amendment；
  未经用户批准不得把 fallback 宣称为 design-v1.2 生产完成。

# Phase 3 — 110/110 Chapter Contracts、Skills 与适用性

### Task 3.1：从 TP-MA-07 建立不可变模板 registry

**Objective:** 将模板 identity、样式、节点和 Word 对象从 Python 常量中抽离为
版本化数据合同。

**Files:**
- Create: config/medical_writing/protocol_v3/templates/tp_ma_07_v1/template.json
- Create: config/medical_writing/protocol_v3/templates/tp_ma_07_v1/node_tree.json
- Create: scripts/qc/protocol_v3/extract_tp_ma_07_registry.py
- Test: tests/protocol_v3/test_tp_ma_07_registry.py

**Micro-steps:**

- [ ] 输入模板 path 和 SHA 固定；hash 不一致即停止。
- [ ] 与 medical_writing_protocol_template.py 当前 124/110 identity 双向比对。
- [ ] 固定 node ID、parent、order、M11 anchor、style、section、bookmark/field 规则。
- [ ] 测试 124 unique nodes、110 unique leaves、无 orphan、顺序稳定。
- [ ] 抽取脚本只生成候选 registry；人工/独立 review 后才标 current。

### Task 3.2：定义 ChapterContract 与 SubstantiveContentContract schema

**Files:**
- Modify: packages/contracts/workbench_contracts/protocol_v3.py
- Create: tests/protocol_v3/test_chapter_contract_schema.py

**Micro-steps:**

- [ ] required/optional/forbidden fact paths。
- [ ] source roles、MedicalAdmissionUnit types、locator/context quality。
- [ ] allowed/qualified/forbidden claims。
- [ ] paragraph/table/SoA/figure/formula/instrument object schema。
- [ ] dependency/impact edges、repair owner、bounded attempts、Word style contract。
- [ ] non-vacuous meta-gate：required fact、required evidence/source role、
  project-specific object/claim obligation 至少一项，且必须有正向 QC。

### Task 3.3：逐叶建立 110 个合同与 chapter-skill manifest

**Files:**
- Create: config/medical_writing/protocol_v3/templates/tp_ma_07_v1/chapter_contracts/<semantic_node_id>.json
- Create: config/medical_writing/protocol_v3/templates/tp_ma_07_v1/chapter_skills/<semantic_node_id>.json
- Create: scripts/qc/protocol_v3/lint_chapter_registry.py
- Test: tests/protocol_v3/test_all_chapter_contracts.py

**Micro-steps per leaf:**

- [ ] 写该叶 required facts/claims/objects 和 forbidden claims。
- [ ] 写允许来源角色、最低 evidence、locator/context。
- [ ] 写适用性、dependency/impact 和 repair owner。
- [ ] 写 Word style/bookmark/cross-reference contract。
- [ ] 写 dedicated skill ID/version、typed input/output、prompt contract 和 errors。
- [ ] 写至少一个 positive、一个 missing-claim、一个 wrong-source、一个 skeleton
  fixture。
- [ ] 运行单叶测试，再加入全 registry lint。

**分批顺序：**

1. 首页/方案摘要/SoA；
2. 目的、estimand、终点、总体设计；
3. 人群/入排/避孕/生活方式；
4. 干预/剂量/随机盲法/合并用药；
5. 终止退出/评估/PK/PD/量表；
6. AE/SAE/AESI/妊娠/特殊安全；
7. 统计全部节点；
8. 监督、伦理、数据、附录、缩略语、参考文献。

### Task 3.4：建立 dependency/impact 图与 cycle gate

**Files:**
- Create: services/api/app/protocol_workflow/canonical/impact_graph.py
- Create: scripts/qc/protocol_v3/render_chapter_dag.py
- Test: tests/protocol_v3/test_chapter_dependency_graph.py

**Micro-steps:**

- [ ] 仅 hard/order edges 参与调度 DAG。
- [ ] cross_consistency 进入 reducer，不形成调度环。
- [ ] unknown edge、hard cycle、missing owner fail closed。
- [ ] high fan-out 变更返回完整 impact set，不能截断。
- [ ] 生成可审查 Mermaid/JSON，但图不是权威；registry 才是权威。

### Task 3.5：Ⅰ期模板权威核验与双模板分流

**Objective:** 使用真实公司Ⅰ期模板，并明确非肿瘤/肿瘤、TP-MA/现行 SOP 的
权威关系；禁止用Ⅱ/Ⅲ期模板或模型臆造Ⅰ期合同。

**Files:**
- Create: config/medical_writing/protocol_v3/templates/phase1_candidates/candidate_manifest.json
- Create: pocs/protocol_v3/template_authority/phase1_decision.md
- Create after authority decision: config/medical_writing/protocol_v3/templates/phase1_non_oncology_v1/
- Create after authority decision: config/medical_writing/protocol_v3/templates/phase1_oncology_v1/
- Test: tests/protocol_v3/test_phase1_template_authority.py
- Test: tests/protocol_v3/test_phase1_template_contracts.py

**已发现候选：**

- `/Users/smkzw/Documents/指导原则及临床试验规范合集/CRP知识库/模板/TP-MA-05 临床试验方案（非肿瘤1期）.docx`，
  SHA-256 `6965f6dbcf86f4a6914e1ee60a74af7b07e7aa820a81694e950214e9d47ff306`；
- `/Users/smkzw/Documents/指导原则及临床试验规范合集/CRP知识库/模板/TP-MA-06 临床试验方案（肿瘤1期）.docx`，
  SHA-256 `a3a8ec75ec804f0105eed65315b844c88fb063af032817b416aaca75ca01a15a`；
- `/Users/smkzw/Documents/康哲项目资料/综合资料/医学部自控文件体系/02 医学开发部/医学科学组/CMSS-SOP-MD-5101-01 临床研究方案撰写操作规程-陈魁/CMSS-SOP-MD-5101-01 临床研究方案撰写操作规程-陈魁-20251113清洁版/CMSS-SOP-MD-5101-T02-00 I期临床研究方案模板.docx`，
  SHA-256 `2d9295636a40f3bbc2837cda842f47da956c49646e5db812bcd626b0a43902db`。

**Micro-steps:**

- [ ] 机械提取文件属性、表头页脚、版本/生效信息、SOP 关系、结构和 leaf count；
  hash 变化即停止。
- [ ] 裁定 TP-MA 与 CMSS-SOP 的当前权威、继承/替代关系，以及非肿瘤和肿瘤
  是否必须保持两棵独立树。
- [ ] 若证据不能唯一裁定，Agent⑤生成问题卡：预选推荐、候选、差异、风险、
  影响和“其他，请输入”，由用户确认；不能用 ASSET_MISSING 掩盖权威歧义。
- [ ] 为每个被批准的完整 Protocol 模板重复 Task 3.1–3.4，要求自身 100% leaf
  contract、Word contract、DAG 和独立复核。
- [ ] CMS-D017 仅是项目对照，不得自动升级为公司模板。
- [ ] 权威/版本未决不阻断Ⅱ/Ⅲ期开发，但阻断Ⅰ期完成声明和Ⅰ期 clean streak。

**Gate P3-G3：**

- TP-MA-07 110/110 non-vacuous；
- 每叶 positive/negative/skeleton tests；
- hard/order DAG 无环；
- applicable/not-applicable 编号、TOC、引用重建测试通过；
- 失败 corpus 全部 fail closed；
- Ⅰ期只有权威选择、适用域、独立树和 100% contracts 全通过才计入覆盖。

# Phase 4 — Agent①：资料、语料与 E0–E3

### Task 4.1：实现 ResearchSeed 归一与 B 型最小引导

**Files:**
- Create: services/api/app/protocol_workflow/agent1/research_seed.py
- Create: frontend/src/features/medical-writing/protocol-workbench/ResearchSeedWizard.jsx
- Modify: frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs
- Test: tests/protocol_v3/test_research_seed_normalization.py
- Test: frontend/src/features/medical-writing/protocol-workbench/ResearchSeedWizard.test.jsx

**Micro-steps:**

- [ ] 八类核心输入全部保存 raw、canonical、candidate、confidence、reason。
- [ ] 模糊中英文、简称、研发代号、拼写变体、多剂量和自然语言对照测试。
- [ ] 默认中国国内多中心。
- [ ] 高置信可自动采用并撤销；多候选预选推荐；低置信/关键冲突 fail closed。
- [ ] 上传 IB/Synopsis 可预填，不要求重复录入。

### Task 4.2：建立 SourceAcquisitionPlan 与三分母

**Files:**
- Create: services/api/app/protocol_workflow/agent1/acquisition_plan.py
- Create: services/api/app/protocol_workflow/agent1/denominators.py
- Test: tests/protocol_v3/test_source_acquisition_plan.py
- Test: tests/protocol_v3/test_competitor_denominators.py

**Micro-steps:**

- [ ] 固定 required discovery、researched competitor、linked Protocol 三分母。
- [ ] 最小来源类只能由 applicability 或用户 reason-coded decision 省略。
- [ ] 无链接、registry-only、paywall、访问受限对象保留在 researched denominator。
- [ ] 分母变更产生旧/新 snapshot、理由、证据和 user DecisionRecord。
- [ ] 下载失败不能作为 competitor/Protocol 重分类理由。

### Task 4.3：发现、竞品相关性与零结果根因

**Files:**
- Create: services/api/app/protocol_workflow/agent1/discovery.py
- Create: services/api/app/protocol_workflow/agent1/competitor_ranking.py
- Create: services/api/app/protocol_workflow/agent1/zero_result_diagnosis.py
- Create: services/api/app/protocol_workflow/legacy/research_pipeline_adapter.py
- Test: tests/protocol_v3/test_e0_discovery_gate.py
- Test: tests/protocol_v3/test_competitor_ranking.py

**Micro-steps:**

- [ ] adapter 复用 condition resolver、CT.gov/China registry 和 triage 服务，
  但新 E0 gate 拥有完成语义。
- [ ] 评分分解时间/状态、靶点/机制、亚组、严重度、线次、人群、剂型剂量、
  phase/design、endpoint、Opr 和来源质量。
- [ ] current regulatory/guideline 规范性优先；旧版降权并保留历史用途。
- [ ] 零结果执行同义词、靶点、亚组、阶段、登记号扩展并记录每次 query/response。
- [ ] 区分网络、认证、归一化、策略、确无公开 Protocol。
- [ ] 任何预期外结果在 UI 有“原因、证据、下一动作”，不能显示空白成功。

### Task 4.4：不可变来源身份、下载与完整性

**Files:**
- Create: services/api/app/protocol_workflow/agent1/source_identity.py
- Create: services/api/app/protocol_workflow/agent1/download_integrity.py
- Test: tests/protocol_v3/test_source_identity.py
- Test: tests/protocol_v3/test_download_integrity.py

**Micro-steps:**

- [ ] logical_source_key 绑定 registry/document version/URL family。
- [ ] 相同 content hash 的镜像、restart、fallback 复用 lineage。
- [ ] 内容变更生成新 revision 并使下游 admission/design/chapter stale。
- [ ] MIME、size、openability、page count、Protocol completeness、HTML 伪装、
  truncation/corruption 全部验证。

### Task 4.5：OCR/解析、翻译与 E1

**Files:**
- Create: services/api/app/protocol_workflow/agent1/ocr_translation.py
- Create: services/api/app/protocol_workflow/agent1/e1_gate.py
- Create: services/api/app/protocol_workflow/legacy/writing_reference_adapter.py
- Test: tests/protocol_v3/test_e1_gate.py
- Test: tests/protocol_v3/test_ocr_translation_lineage.py

**Micro-steps:**

- [ ] 所有 OCR/翻译走当前共享 oMLX gate；调用者不越过其模型/lease/heartbeat。
- [ ] 原生数字文本优先 parse；扫描件才 OCR，逐页覆盖与表格结构必须验证。
- [ ] 翻译验证段落/表格/页码对齐、数字、单位、否定、术语、引用与章节完整。
- [ ] 中文原文产生 translation_not_required_pass，不用空任务冒充。
- [ ] E1 严格验证 linked=integrity=parse_or_ocr=translation_fidelity，
  pending/failed=0。
- [ ] 对所有已调研且存在下载链接的竞品 Protocol，downloaded/complete/
  readable/parsed-or-OCRed/translated-or-not-required/fidelity-pass 分子必须等于
  frozen linked denominator；不能把失败项移入 excluded 来通过 Gate。
- [ ] 重分类必须用户问题卡；质量豁免不存在。
- [ ] 用 deterministic fakes 注入 OCR 缺页、翻译否定反转、表格错位和
  completed_with_blocked。

### Task 4.6：MedicalAdmissionUnit、语义映射与 E3

**Files:**
- Create: services/api/app/protocol_workflow/agent1/admission.py
- Create: services/api/app/protocol_workflow/agent1/semantic_mapping.py
- Create: services/api/app/protocol_workflow/agent1/e3_gate.py
- Test: tests/protocol_v3/test_medical_admission_unit.py
- Test: tests/protocol_v3/test_e3_semantic_coverage.py
- Test: tests/protocol_v3/test_batch_admission_semantics.py

**Micro-steps:**

- [ ] 正向要求 claim_type、fact paths、support/conflict/limit、合法 locator、
  context window、quality、semantic node、source hash。
- [ ] 标题、TOC、页眉页脚、引言、heading-only、脱离上下文短句不能独立覆盖。
- [ ] verdict 绑定 item_id+item_revision+evidence_hash。
- [ ] REJECT 不被 batch 复活；batch 仅幂等采用 latest PASS。
- [ ] 新 evidence/revision 才能重审，旧 verdict 保留。
- [ ] 44 字、长通用、短无目标 claim、无 objectives fixtures 全部失败；
  短但真实且满足正向合同的 fixture 通过。

### Task 4.7：E2 监管/指南时效门与 Agent①子图

**Files:**
- Create: services/api/app/protocol_workflow/agent1/regulatory_currency.py
- Create: services/api/app/protocol_workflow/agent1/subgraph.py
- Create: services/api/app/protocol_workflow/agent1/gates.py
- Create: services/api/app/protocol_workflow/api/research.py
- Modify: frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs
- Test: tests/protocol_v3/test_e2_regulatory_currency.py
- Test: tests/protocol_v3/test_agent1_subgraph.py
- Test: tests/protocol_v3/test_agent1_api_contract.py

**Gate E0–E3：**

- E0 required queries 与零结果根因可复现；
- E1 linked Protocol 全量完整；
- E2 current/effective/supersession/scope 完整；
- E3 所有设计关键 applicable nodes 有正向 admitted evidence；
- EvidenceCorpusPacket 含三分母、coverage、conflict/gap 和全 lineage；
- 未通过时只向明确 owner/用户问题卡升级，不进入 Agent②。

# Phase 5 — Agent②：设计、推荐卡、StudyDefinition v3 与 Protocol Summary

### Task 5.1：实现临床设计 worker

**Files:**
- Create: services/api/app/protocol_workflow/agent2/clinical_worker.py
- Create: config/medical_writing/protocol_v3/skills/clinical_design_v1.json
- Test: tests/protocol_v3/test_clinical_design_worker.py

**Micro-steps:**

- [ ] 输出 typed proposal，不直接写 facts。
- [ ] 覆盖 P/I/C/O/M/A/Opr 临床字段。
- [ ] 竞品细节结论必须 competitor_full_protocol；registry-only 自动降级措辞。
- [ ] 竞品不得覆盖项目/IB 目标药物事实。

### Task 5.2：实现统计/estimand worker

**Files:**
- Create: services/api/app/protocol_workflow/agent2/statistical_worker.py
- Create: config/medical_writing/protocol_v3/skills/statistical_estimand_v1.json
- Test: tests/protocol_v3/test_statistical_design_worker.py

**Micro-steps:**

- [ ] 覆盖 estimand、样本量、alpha、多重性、中期、分析集、缺失、敏感性。
- [ ] 每个假设记录 evidence、公式参数、rounding 与 uncertainty。
- [ ] 缺少效应/方差/脱落依据时给推荐选项，不伪造确定值。

### Task 5.3：实现确定性一致性 reducers

**Files:**
- Create: services/api/app/protocol_workflow/agent2/reducers.py
- Test: tests/protocol_v3/test_design_reducers.py

**Micro-steps:**

- [ ] objective→estimand→endpoint→analysis 闭合。
- [ ] effect assumption→sample size 闭合。
- [ ] visit→assessment window→SoA 闭合。
- [ ] Opr 反向约束中心/样本/访视/周期。
- [ ] 冲突输出 typed issue，不由 worker 私下选择。

### Task 5.4：实现原子推荐卡与一键接受

**Files:**
- Create: services/api/app/protocol_workflow/agent2/recommendations.py
- Create: frontend/src/features/medical-writing/protocol-workbench/DecisionCard.jsx
- Create: frontend/src/features/medical-writing/protocol-workbench/DecisionOverview.jsx
- Test: tests/protocol_v3/test_recommendation_cards.py
- Test: frontend/src/features/medical-writing/protocol-workbench/DecisionOverview.test.jsx

**Micro-steps:**

- [ ] 每张卡只承载一个设计决策，默认推荐已预选。
- [ ] 3–5 选项含理由、evidence_class、支持/冲突证据、影响和“其他，请输入”。
- [ ] 自定义输入先解析和 impact preview，再允许采用。
- [ ] 一键接受仅对 current snapshot 中合法预选执行 CAS；
  unresolved/conflict/low-confidence blocking card 跳过并解释。
- [ ] 重复点击/worker/restart 不产生新 DecisionRecord 或模型调用。

### Task 5.5：生成 StudyDefinition v3、适用性与 Protocol Summary

**Files:**
- Create: services/api/app/protocol_workflow/agent2/study_definition.py
- Create: services/api/app/protocol_workflow/agent2/applicability.py
- Create: services/api/app/protocol_workflow/agent2/protocol_summary.py
- Create: services/api/app/protocol_workflow/agent2/subgraph.py
- Create: services/api/app/protocol_workflow/api/design.py
- Modify: frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs
- Test: tests/protocol_v3/test_study_definition_v3.py
- Test: tests/protocol_v3/test_applicability_snapshot.py
- Test: tests/protocol_v3/test_protocol_summary_projection.py
- Test: tests/protocol_v3/test_agent2_api_contract.py

**Micro-steps:**

- [ ] reducer 只接受 DecisionRecords 和 confirmed evidence。
- [ ] ApplicabilitySnapshot 绑定 facts/rules/version/hash。
- [ ] not-applicable 不进正文/TOC，编号与引用重建。
- [ ] 模板必需节点必须项目特异说明，不允许统一“无/不适用”。
- [ ] Protocol Summary 是 semantic blocks；任何事实差异回到 fact proposal。
- [ ] Standalone Synopsis 此阶段不存在。

**Gate D1：**

- 必需 facts confirmed/frozen；
- 临床/统计/Opr reducers 无 open conflict；
- recommendation evidence_class 与证据可解释；
- applicability 无 unresolved；
- 首页和 Protocol Summary 无占位符/待确认/AI 痕迹；
- current StudyDefinition hash 唯一。

# Phase 6 — Agent③、章节锁、A+C UI 与完整 Word 式编辑

### Task 6.0：编辑器候选 PoC 与能力锁定（必须先执行）

**Objective:** 在任何 ProtocolCanvas、选区锚点或 Word 对象 UI 实现前，冻结
引擎无关合同并选择能够满足 D011/D012 的实现；当前 TipTap 只作为对照组。

**Files:**
- Create: pocs/protocol_v3/editor/capability_matrix.md
- Create: pocs/protocol_v3/editor/candidate_manifest.json
- Create: pocs/protocol_v3/editor/runner.py
- Create: pocs/protocol_v3/editor/adapters/tiptap_baseline.mjs
- Create: pocs/protocol_v3/editor/adapters/candidate_adapter.mjs
- Create: pocs/protocol_v3/editor/decision.md
- Create: pocs/protocol_v3/editor/tests/test_capability_matrix.py
- Create: frontend/tests/protocol_editor_d011_d012_qc.mjs
- Create after selection: frontend/src/features/medical-writing/protocol-workbench/editor/editorEngineAdapter.mjs

**Required capabilities:**

- 样式、字体、字号、颜色、段落、列表、对齐、缩进、行距；
- 复杂表格、合并拆分、重复表头、跨页语义；
- 图片/图表/SoA、题注、公式、脚尾注、引用；
- 页眉页脚、页面/分节、目录、书签、域、交叉引用；
- 查找替换、撤销重做、批注/修订、快捷键、中文 IME；
- 稳定 semantic block IDs、约 110 节点性能、分页与 DOCX round-trip。

**Micro-steps:**

- [ ] candidate manifest 核验开源许可证、商业义务、维护、安全、私有化和数据外传。
- [ ] 所有候选以同一 TP-MA-07/golden OOXML corpus 执行，不用 marketing claim 计分。
- [ ] adapter 固定 `load/capabilities/renderPages/getSelectionIdentity/
  applySemanticTransaction/exportRoundTripFixture/destroy`。
- [ ] selection range 的结构路径/offset 语义必须覆盖中文、emoji、组合字符与 IME；
  `selected_hash` 和 current revision 双重防 stale，禁止空 `block_hash`。
- [ ] 与 P0-WORD producer 的 semantic/OOXML round-trip 对接。
- [ ] 任一 D011/D012 硬能力缺失都使 Task 6.0 FAIL；不得先做大规模 UI 再补偿。

### Task 6.1：建立 dependency-aware writing planner

**Files:**
- Create: services/api/app/protocol_workflow/agent3/planner.py
- Create: services/api/app/protocol_workflow/agent3/packets.py
- Test: tests/protocol_v3/test_writing_planner.py

**Micro-steps:**

- [ ] 从 applicability+hard/order edges 构建 DAG。
- [ ] cycle 在模型调用前失败并定位具体 contracts/edges。
- [ ] 只把强相关节点组成 packet；依赖满足才 fan-out。
- [ ] 每 packet 输入仅含 required facts/evidence/contracts。

### Task 6.2：实现 chapter-skill executor 与 section validator

**Files:**
- Create: services/api/app/protocol_workflow/agent3/executor.py
- Create: services/api/app/protocol_workflow/agent3/section_validator.py
- Create: services/api/app/protocol_workflow/agent3/skeleton_detector.py
- Test: tests/protocol_v3/test_chapter_skill_executor.py
- Test: tests/protocol_v3/test_substantive_content_gate.py

**Micro-steps:**

- [ ] executor 经 reservation+harness 运行，不直接写 document。
- [ ] validator 检查 required claims/objects/fact bindings/source roles。
- [ ] 空标题、空表、模板改写、跨项目通用段、重复和 internal token 失败。
- [ ] 不用总字数替代实质合同。
- [ ] 全部 Phase 0 skeleton fixtures 失败。

### Task 6.3：实现全文 reducer 与局部重跑

**Files:**
- Create: services/api/app/protocol_workflow/agent3/reducer.py
- Create: services/api/app/protocol_workflow/agent3/subgraph.py
- Create: services/api/app/protocol_workflow/legacy/full_draft_adapter.py
- Test: tests/protocol_v3/test_full_document_reducer.py
- Test: tests/protocol_v3/test_local_invalidation.py

**Micro-steps:**

- [ ] 组装章节、SoA、表图、引用、编号与 cross-consistency。
- [ ] packet/chapter adoption 由一个 DecisionRecord+reducer 定义原子或显式分片语义；
  进程中断不能留下未记录的部分采纳。
- [ ] 只失效 dependency 命中的节点。
- [ ] 未受影响 locked 章节 hash 不变。
- [ ] 新链 feature flag 关闭时旧 full draft 行为完全不变。
- [ ] 不删除 medical_writing_full_draft.py，直到 Phase 8 切换稳定。

### Task 6.4：实现 ChapterLockSnapshot、auto-unlock 与 EditClass

**Files:**
- Create: services/api/app/protocol_workflow/canonical/chapter_locks.py
- Create: services/api/app/protocol_workflow/canonical/edit_classification.py
- Test: tests/protocol_v3/test_chapter_locks.py
- Test: tests/protocol_v3/test_edit_classification.py

**Micro-steps:**

- [ ] lock 绑定所有上游/产物/closed finding hashes。
- [ ] 一键接受后 locked_current。
- [ ] 后续 facts/evidence/contract/skill 变更自动解锁完整 impact set。
- [ ] 仅 deterministic 编号/引用/样式可自动重锁。
- [ ] format_only、wording_only、structure_or_word_object、fact_or_uncertain。
- [ ] 不确定默认 fact_or_uncertain。

### Task 6.5：将 WritingPage 从 App.jsx 以 strangler 方式抽离

**Files:**
- Create: frontend/src/features/medical-writing/protocol-workbench/ProtocolWorkspacePage.jsx
- Create: frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceState.mjs
- Create: frontend/src/features/medical-writing/protocol-workbench/protocol-workbench.css
- Modify: frontend/src/App.jsx
- Test: frontend/src/features/medical-writing/protocol-workbench/ProtocolWorkspacePage.test.jsx
- Test: tests/test_frontend_medical_writing_contract.py

**Micro-steps:**

- [ ] 先写 route/feature-flag contract test。
- [ ] 抽离 API calls/state，不改变旧 writing route。
- [ ] feature flag off 使用旧 WritingPage；on 使用新页面。
- [ ] App.jsx 每次只迁移一个 cohesive surface，避免一次性 8,000 行重写。
- [ ] `python3 scripts/qc/protocol_v3/run_frontend_checks.py --unit --build` 与现有
  frontend medical-writing contracts 通过。

### Task 6.6：实现 A+C 页面层次

**Files:**
- Create: frontend/src/features/medical-writing/protocol-workbench/ProtocolOrchestrationPanel.jsx
- Create: frontend/src/features/medical-writing/protocol-workbench/ChapterNavigation.jsx
- Create: frontend/src/features/medical-writing/protocol-workbench/ChapterLockPanel.jsx
- Create: frontend/src/features/medical-writing/protocol-workbench/editor/ProtocolEditorHost.jsx
- Create: frontend/src/features/medical-writing/protocol-workbench/editor/FinalStyleDocumentCanvas.jsx
- Create: frontend/src/features/medical-writing/protocol-workbench/ChapterAiPanel.jsx
- Create: frontend/src/features/medical-writing/protocol-workbench/IssueEvidencePanel.jsx
- Create: frontend/src/features/medical-writing/protocol-workbench/word/WordRoundTripPanel.jsx
- Create: services/api/app/protocol_workflow/api/document.py
- Modify: frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs
- Test: frontend/src/features/medical-writing/protocol-workbench/ProtocolOrchestrationPanel.test.jsx
- Test: frontend/src/features/medical-writing/protocol-workbench/ChapterNavigation.test.jsx
- Test: frontend/src/features/medical-writing/protocol-workbench/editor/FinalStyleDocumentCanvas.test.jsx
- Test: tests/protocol_v3/test_agent3_document_api_contract.py
- Test: frontend/tests/protocol_workspace_ac_qc.mjs

**Micro-steps:**

- [ ] 顶部 A 显示结论、关键卡、异常、真实进度、一键接受。
- [ ] 下方 C：左目录、中最终版式画布、右 AI/证据/QC。
- [ ] 每个章节有自己的 AI 统筹与异常区。
- [ ] 推荐/异常与 semantic block 双向定位。
- [ ] overlay 可开关且绝不进入 Word。
- [ ] 普通审计/身份说明不占持久竖向带；仅 blocker 展开。
- [ ] desktop 是阻断验收；mobile 仅退化烟测，不删除桌面能力。

### Task 6.7：实现选区 AI 与 semantic transaction

**Files:**
- Create: frontend/src/features/medical-writing/protocol-workbench/editor/AiSelectionContextMenu.jsx
- Create: frontend/src/features/medical-writing/protocol-workbench/editor/selectionIdentity.mjs
- Create: services/api/app/protocol_workflow/agent3/selection_ai.py
- Modify: services/api/app/protocol_workflow/api/document.py
- Test: tests/protocol_v3/test_selection_ai.py
- Test: frontend/src/features/medical-writing/protocol-workbench/editor/AiSelectionContextMenu.test.jsx

**Micro-steps:**

- [ ] anchor=block_id+semantic_node_id+range+revision+selected_hash。
- [ ] range 服从 Task 6.0 锁定的结构/offset 合同，中文、emoji、组合字符、IME
  和表格 cell 均有 stale/错位回归。
- [ ] 右键提供润色、改写、扩写、缩写、监管语气、补证据、一致性。
- [ ] 返回 3–5 候选和局部 diff，默认保护数字/单位/术语/引用/书签/格式。
- [ ] stale selection 拒绝采用。
- [ ] fact_or_uncertain 显示 impacted fact paths/章节，转 fact proposal。
- [ ] locked chapter 编辑前产生 auto-unlock event。

**Gate W1/UI1：**

- 全部 applicable nodes 有 source-bound 实质内容；
- required claim/object/fact/evidence 覆盖 100%，skeleton_risk=0；
- 占位符、待确认、日志、prompt、错误码、AI 痕迹=0；
- A+C 全按钮、锁/解锁、选区 AI、保存/reload/restart 可验证；
- editor PoC 满足完整能力合同；
- 不满足时不得进入 Agent④ clean 或称全文完成。

# Phase 7 — Agent④、Word 回流、四层定稿门与交付投影

### Task 7.1：生成完整 coverage digest

**Files:**
- Create: services/api/app/protocol_workflow/agent4/coverage_digest.py
- Test: tests/protocol_v3/test_qc_coverage_digest.py

**Micro-steps:**

- [ ] 每 applicable node→blocks→required claims/objects→facts→evidence/decision 闭合。
- [ ] 附 revision diff、applicability delta、lock history、validators 和未闭合定位。
- [ ] digest 必须先覆盖 registry 110/110；verifier 可分片但 final reducer 不抽样。
- [ ] 故意删除最后一行、重复一行或换 revision，clean 必须失败。

### Task 7.2：实现 fresh-context verifier 与 typed findings

**Files:**
- Create: services/api/app/protocol_workflow/agent4/reviewer.py
- Create: services/api/app/protocol_workflow/agent4/findings.py
- Create: services/api/app/protocol_workflow/agent4/routing.py
- Test: tests/protocol_v3/test_qc_reviewer_isolation.py
- Test: tests/protocol_v3/test_qc_findings.py

**Micro-steps:**

- [ ] reviewer 只收 artifact、criteria、coverage row 和必要证据。
- [ ] writer/reviewer execution identity 不同；P0/P1 final verifier 必须不同 identity。
- [ ] 有多个合格模型时 P0/P1 使用不同 provider/model。
- [ ] finding 含 locator、severity、contract、evidence、impact、owner、acceptance。
- [ ] reviewer 不能直接改 canonical facts。

### Task 7.3：实现 repair loop 与 Q1

**Files:**
- Create: services/api/app/protocol_workflow/agent4/repair.py
- Create: services/api/app/protocol_workflow/agent4/gate.py
- Create: services/api/app/protocol_workflow/agent4/subgraph.py
- Create: services/api/app/protocol_workflow/api/qc.py
- Modify: frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs
- Test: tests/protocol_v3/test_q1_gate.py
- Test: tests/protocol_v3/test_repair_routing.py
- Test: tests/protocol_v3/test_agent4_qc_api_contract.py

**Micro-steps:**

- [ ] 医学/临床→Agent② clinical；统计→statistical；章节→Agent③；
  语言/编号/格式→deterministic 或定点 repair。
- [ ] fixed_verified、duplicate_of、artifact_superseded、design_choice 四类 typed closure。
- [ ] accepted_risk、not_planned、自由文本 superseded、重试上限不能 clean。
- [ ] current artifact P0–P4 open_count 必须 0。
- [ ] 每次 repair 生成新 revision/hash 并独立复核。

### Task 7.4：把 Phase 0 Word producer 接入产品

**Files:**
- Create: services/api/app/protocol_workflow/word/receipt_producer.py
- Create: services/api/app/protocol_workflow/word/receipt_service.py
- Create: services/api/app/protocol_workflow/word/ooxml_fingerprint.py
- Create: services/api/app/protocol_workflow/legacy/word_receipt_adapter.py
- Create: services/api/app/protocol_workflow/api/exports.py
- Test: tests/protocol_v3/test_word_receipt_service.py
- Test: tests/protocol_v3/test_word_native_gate_contract.py

**Micro-steps:**

- [ ] producer 只接受 immutable export artifact。
- [ ] P0-WORD decision/producer/version/contract 任何变化都使旧产品接线 stale；
  未重新通过不得执行 Layer 4。
- [ ] 每一步经 reservation/idempotency，unknown_outcome 不自动重跑。
- [ ] receipt 与 exact source/document/fact revisions 绑定。
- [ ] Word 打开无修复、更新域/目录、书签/引用、保存重开、PDF/页面证据、
  OOXML 指纹全部进入 receipt。
- [ ] 复用现有 MedicalWritingWordVerificationReceipt 时以 adapter 显式迁移，
  不悄悄扩大旧 status 语义。

### Task 7.5：实现 Word 回流与 EditClass

**Files:**
- Create: services/api/app/protocol_workflow/word/importer.py
- Create: services/api/app/protocol_workflow/word/diff.py
- Create: services/api/app/protocol_workflow/word/semantic_merge.py
- Test: tests/protocol_v3/test_word_roundtrip_import.py
- Test: tests/protocol_v3/test_word_fact_change_fail_closed.py

**Micro-steps:**

- [ ] 原 Word 文件与回流文件均 immutable。
- [ ] 识别 wording/format/structure_or_word_object/fact_or_uncertain。
- [ ] 书签丢失、无法映射、严重结构变化或并发冲突 fail closed。
- [ ] 事实变化转 proposal+impact，不直接覆盖 StudyDefinition。
- [ ] merge 生成新 SemanticDocumentRevision 并重新 chapter/cross/Word QC。

### Task 7.6：实现四层 Final Gate 与 SubmissionEvidencePackage

**Files:**
- Create: services/api/app/protocol_workflow/agent5/final_gate.py
- Create: services/api/app/protocol_workflow/agent5/submission_package.py
- Test: tests/protocol_v3/test_submission_evidence_package.py
- Test: tests/protocol_v3/test_four_layer_final_gate.py

**Micro-steps:**

- [ ] Layer1 exact fact/document revision consistency。
- [ ] Layer2 all applicable substantive/source-bound、internal traces=0。
- [ ] Layer3 Agent④ clean、coverage complete、P0–P4 open=0。
- [ ] Layer4 exact Microsoft Word receipt + round-trip。
- [ ] package 冻结 facts/contracts/decisions/QC/receipt/model/tool/hashes。
- [ ] 正文不得嵌入内部日志；审计包与正式 Protocol 分开。

### Task 7.7：实现 Standalone Synopsis 导出窗口

**Files:**
- Create: services/api/app/protocol_workflow/word/standalone_synopsis.py
- Create: config/medical_writing/protocol_v3/templates/standalone_synopsis/template_registry.json
- Create: services/api/app/protocol_workflow/api/standalone_synopsis.py
- Create: frontend/src/features/medical-writing/protocol-workbench/StandaloneSynopsisExport.jsx
- Test: tests/protocol_v3/test_standalone_synopsis_projection.py
- Test: frontend/src/features/medical-writing/protocol-workbench/StandaloneSynopsisExport.test.jsx

**候选投影模板：**

- Ⅰ期 `/Users/smkzw/Documents/康哲项目资料/综合资料/医学部自控文件体系/02 医学开发部/医学科学组/CMSS-SOP-MD-5101-01 临床研究方案撰写操作规程-陈魁/CMSS-SOP-MD-5101-01 临床研究方案撰写操作规程-陈魁-20251113清洁版/CMSS-SOP-MD-5101-T01-00 I期临床研究摘要模板.docx`，
  SHA-256 `12f223a6510f37a53a6d557a26cb5878c5edccb614c12f05981d430f8fe64a66`；
- Ⅱ/Ⅲ期 `/Users/smkzw/Documents/康哲项目资料/综合资料/医学部自控文件体系/02 医学开发部/医学科学组/CMSS-SOP-MD-5101-01 临床研究方案撰写操作规程-陈魁/CMSS-SOP-MD-5101-01 临床研究方案撰写操作规程-陈魁-20251113清洁版/CMSS-SOP-MD-5101-T03-00  II III期临床研究摘要模板.docx`，
  SHA-256 `5fcb37f53bf4456cc38064c64b03a62e8d7e4eb96631f61b32c0945e835189d0`。

**Micro-steps:**

- [ ] 只有 Final Gate 通过时可生成。
- [ ] 输入仅 frozen StudyDefinition、Decision Graph、final Protocol blocks。
- [ ] registry 固定 phase→template hash、字段/semantic mapping、Word styles、
  bookmarks/fields 和 projection contract；权威未核验时该 phase 导出阻断。
- [ ] 不提供独立事实编辑。
- [ ] Protocol 变化后旧 artifact stale。
- [ ] Synopsis 自身 Word artifact 失败只阻断该导出，不改变 Protocol facts。
- [ ] 每个 Synopsis artifact 仍需自身 OpenXML+Microsoft Word receipt，不能复用
  Protocol receipt 冒充。

**Gate Q1/F1：**

- coverage digest 无遗漏；
- current P0–P4 open_count=0；
- reviewer isolation/multi-model 条件满足；
- Word native receipt 与 round-trip 通过；
- SubmissionEvidencePackage hash 闭合；
- 用户人工审阅不作为产品阻断，但产物正文不得出现“待某方确认”。

# Phase 8 — Strangler、shadow、真实 E2E 与发布

### Task 8.1：项目级 feature flags 与 read-only shadow

**Files:**
- Create: services/api/app/protocol_workflow/feature_flags.py
- Create: services/api/app/protocol_workflow/shadow.py
- Create: services/api/app/protocol_workflow/legacy/read_adapter.py
- Create: tests/protocol_v3/test_shadow_read_only.py
- Create: tests/protocol_v3/integration/test_new_canonical_blocks_legacy_mutations.py
- Modify: services/api/app/main.py

**Micro-steps:**

- [ ] 默认所有现有项目走 legacy。
- [ ] 新链按 project allowlist 开启。
- [ ] rollout flag 本身进入 durable CAS/audit registry，不只依赖环境变量。
- [ ] shadow 在 clone store/隔离进程运行；不得 import 会建库、迁移、启动 worker
  或写配置的 `main.py`/constructor/status/recalculate 路径。
- [ ] shadow 只读 legacy inputs，不写任何旧 row/field。
- [ ] 比较 facts、evidence、applicability、chapters、Word artifact 和 gates。
- [ ] 任何 legacy write 监测到即 fail、撤销 flag、保留新链独立 history。
- [ ] 对每个旧 mutation route 执行 NEW_CANONICAL 负向矩阵，断言 HTTP/service
  fail closed、旧 row/logical hash 不变、新链事件不被重复创建。

### Task 8.2：pre-switch snapshot 与回滚演练

**Files:**
- Create: scripts/qc/protocol_v3/create_cutover_snapshot.py
- Create: scripts/qc/protocol_v3/verify_legacy_readability.py
- Create: scripts/qc/protocol_v3/rollback_project_flag.py
- Test: tests/protocol_v3/test_cutover_rollback.py

**Micro-steps:**

- [ ] snapshot 所有相关 stores、schema、logical counts、hash、artifact refs。
- [ ] compatibility writes 只能 additive 且旧链能忽略/读取。
- [ ] 在 `SHADOW_READ_ONLY` 前故意失败，关闭 flag 后 legacy 仍按原权威可操作。
- [ ] 进入 `NEW_CANONICAL` 后故意失败，只暂停新 commands、保持 legacy 只读并
  从新 event/artifact 恢复；不得自动恢复旧链事实写入。
- [ ] 回滚不删除新链 event/artifact history，不回写旧 immutable rows。

### Task 8.3：更新 API/client/release contracts

**Files:**
- Modify: services/api/app/runtime_readiness.py
- Modify: frontend/src/runtimeReadiness.js
- Modify: deploy/medical_writing_local/build_release_bundle.py
- Modify: deploy/medical_writing_local/verify_release.py
- Modify: deploy/medical_writing_local/README.md
- Test: tests/test_runtime_readiness.py
- Test: tests/test_medical_writing_release_verifier.py
- Test: frontend/tests/medical_writing_runtime_readiness_qc.mjs

**Micro-steps:**

- [ ] 增加 Protocol v3 capabilities、graph/storage/schema/template/skill identities。
- [ ] readiness 报告 Word producer 可用性、不是伪造的 word_verified。
- [ ] release bundle 纳入新 contracts/config/frontend/scripts，不纳入 secrets/runtime。
- [ ] 旧 client contract 失败关闭；当前 client 与 backend build 对齐。
- [ ] 不在发布文档硬编码过时 AI provider/model；从 role registry 展示有效 identity。

### Task 8.4：确定性/集成/故障注入全量门

**Files:**
- Create: scripts/qc/protocol_v3/run_release_gate.py
- Create: config/medical_writing/protocol_v3/release_gate.json
- Create: tests/protocol_v3/integration/test_r17_reject_survives_accept_all_restart.py
- Create: tests/protocol_v3/integration/test_d017_skeleton_fails_word_positive_path.py

**Commands:**

    python3 -m pytest tests/protocol_v3 -q
    python3 -m pytest tests/protocol_v3/integration/test_r17_reject_survives_accept_all_restart.py -q
    python3 -m pytest tests/protocol_v3/integration/test_d017_skeleton_fails_word_positive_path.py -q
    python3 -m pytest tests/test_medical_writing_*.py -q
    python3 -m pytest -q
    python3 -m compileall services/api/app packages/contracts
    python3 scripts/qc/protocol_v3/run_frontend_checks.py --unit --build
    node frontend/tests/protocol_workspace_ac_qc.mjs
    node frontend/tests/protocol_editor_d011_d012_qc.mjs
    node frontend/tests/protocol_word_roundtrip_qc.mjs
    node frontend/tests/medical_writing_runtime_readiness_qc.mjs
    python3 scripts/qc/protocol_v3/run_release_gate.py --manifest config/medical_writing/protocol_v3/release_gate.json

**Expected:** 全部 PASS；无 baseline failure 被删除或 xfail；无 runtime 数据写入
冻结清单；无受保护医学监查文件差异。r17 场景必须证明精确
`item_id+item_revision+evidence_hash` REJECT 经 accept-all、restart/resume 后仍为
REJECT 且 DecisionRecord 只有一次；D017 即使 OOXML/Word receipt 为正，也必须
在 W1/F1 fail closed。

### Task 8.5：建立真实 E2E 隔离运行器

**Files:**
- Create: frontend/tests/protocol_v3_e2e/orchestrator.mjs
- Create: frontend/tests/protocol_v3_e2e/scenarios.mjs
- Create: frontend/tests/protocol_v3_e2e/role_contracts/engineer.md
- Create: frontend/tests/protocol_v3_e2e/role_contracts/senior_medical_writer.md
- Create: scripts/qc/protocol_v3/clone_clean_runtime.py
- Create: scripts/qc/protocol_v3/verify_e2e_artifacts.py
- Create: scripts/qc/protocol_v3/run_e2e_matrix.py
- Create: config/medical_writing/protocol_v3/e2e_matrix.json
- Create: config/medical_writing/protocol_v3/severity_policy.json
- Test: tests/protocol_v3/test_e2e_matrix_contract.py
- Test: tests/protocol_v3/test_severity_policy.py

**Micro-steps:**

- [ ] 每轮从 immutable clean baseline clone 独立 runtime，不删除主 runtime 项目。
- [ ] tester 与 role 分开派发；一个 prompt 不混工程师/用户角色。
- [ ] 用户角色 prompt 宽松、真实、批判性，不写成逐项跑分脚本。
- [ ] 用户角色必须 Playwright 真实点击；API 只用于事后证据核对。
- [ ] 产品独立 AI 完整执行检索、下载、OCR/parse、翻译、语料、设计、写作、
  QC、Word，不由 tester 代写正文。
- [ ] 每个预期外结果必须形成 root-cause report，不能只记录“能点通”。
- [ ] 最终 DOCX 必须逐章通读并检查 AI/log/TODO/待确认/空骨架。
- [ ] manifest 固定 tester identity、独立 role、declared/effective harness/model、
  phase/template、适应症、设计、prompt hash、必需 artifacts 和失败处理；不可用
  tester 记 blocked，不得从分母删除。
- [ ] P0=安全/数据完整性/不可恢复或全流程不可用；P1=主流程或可提交性阻断；
  P2=重大医学/统计/证据/Word 错误；P3=需专业人员实质返工的易用性、格式或
  追溯问题；P4=仍可见、应修复的轻微问题。policy version/hash 在轮次前冻结。

### Task 8.6：执行分角色、多模型、I/II/III真实矩阵

**唯一入口：**

    python3 scripts/qc/protocol_v3/run_e2e_matrix.py \
      --manifest config/medical_writing/protocol_v3/e2e_matrix.json \
      --isolated-root /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-e2e-<e2e_run_id>

**Expected:** 只有所有冻结 tester/role/scenario 完成、artifact manifest 齐全且
clean-streak reducer 返回 0 时 exit 0；blocked、缺产物、未 Word verified 或少跑
任何分母均非 0。

运行器必须由 workflow guard 生成唯一 `<e2e_run_id>`，并在启动前断言目标不存在；
不得复用或清空旧 E2E 目录。

**Tester contract:**

- 工程师角色与“懒惰但专业、视觉敏感的资深原生中文医学写作经理”角色
  完全分开。
- 每个 tester/角色至少 3 个不同非肿瘤适应症，覆盖 I/II/III 期和不同研究设计。
- 每轮 prompt、项目、适应症和设计不同。
- 用户角色审查点击数、确认负担、独立 AI 交互、语料科学性、监管中文、
  完整性/一致性、格式、目录/参考文献跳转、Word 可编辑性。
- tester 首次运行先做 harness/connectivity probe；不要因慢而随意 fallback。
- tester 运行期间使用同 session 超长等待；只有 terminal failure/验收失败后
  才 same-session follow-up 或 manifest fallback。
- 实际 tester 集合使用用户批准的 Grok、DeepSeek、Hy3、MiniMax、GLM 等
  角色，但每次派发必须由当时最新版全局 workflow guard/route manifest
  验证 provider/model，不在本计划复制可能过时的路由表。
- 每个模型的工程师和用户角色分别派发、分别建 session；不得让一个 prompt
  同时扮演两种角色。

**Clean streak：**

- 任一 P0/P1/P2/P3/P4 都使该 tester/role 本轮不 clean。
- 修复后使用新项目/新 prompt 重跑。
- 每个 tester 每个 role 连续两轮 open P0–P4=0 才满足上线门。
- 不能用 preparation-only、API-only、空正文或未 Word-verified 的轮次计入。

### Task 8.7：逐项目 cutover 与发布

**Objective:** 先单项目 canary，再扩大；任何失败可恢复到旧链。

**Micro-steps:**

- [ ] 选无生产依赖的 canary project。
- [ ] 保存 pre-switch snapshot 并运行 legacy readability。
- [ ] 开启项目 flag，执行完整真实 Protocol。
- [ ] Codex 复核 API、browser、final DOCX、Word/PDF、SubmissionEvidencePackage。
- [ ] 独立 reviewer 验收 READY 后才扩大项目。
- [ ] 运行 deploy/medical_writing_local/verify_release.py 和 release bundle。
- [ ] 演练关闭 flag、恢复旧链可读；新链历史保留。
- [ ] 若项目已进入 NEW_CANONICAL，所谓回滚只恢复服务可用性与新链事件重放；
  legacy 保持只读，除非另有获批逆迁移。

**Gate R1：**

- 全确定性/集成/故障注入测试通过；
- shadow 无旧 store 逻辑写；
- 每 tester/role 连续两轮 P0–P4=0；
- 完整 I/II/III 非肿瘤 Protocol 均有可提交正文与 Word receipt；
- rollback 演练通过；
- Phase I 权威/独立树/contracts 未通过时，不得声称 I 期上线；冻结矩阵中的
  I 期场景保持 blocked，不能删除后把Ⅱ/Ⅲ期范围冒充全范围 clean。

## 6. API surface 规划

新 API 使用 /api/projects/{project_id}/protocol-workflow 前缀，旧
/medical-writing 路由保持不变直到 cutover。

| Surface | 关键动作 |
|---|---|
| /research-seed | create/normalize/confirm |
| /source-plan | read/freeze/reclassify-by-user-decision |
| /sources | discovery/identity/integrity/processing |
| /gates/e0-e3 | deterministic gate snapshots |
| /recommendations | cards/accept-one/accept-all/custom proposal |
| /study-definition | current/history/CAS proposal |
| /applicability | current/diff |
| /chapters | contract/status/lock/unlock/impact |
| /document | semantic revision/transactions/selection-ai |
| /qc | coverage/findings/repairs/gate |
| /exports | protocol DOCX/PDF/Word receipt/reimport |
| /standalone-synopsis | final-gated projection only |
| /workflow | run/status/interrupt/recover |

所有 mutation 要求 expected_revision、idempotency_key、actor、reason 或
DecisionRecord；GET 不得产生业务写入。

## 7. 测试分层

| 层 | 目的 | 证明 |
|---|---|---|
| Contract | schema/state/hash/error | 非法状态 fail closed |
| Pure reducer | facts/decision/document/impact | 确定性与 CAS |
| Repository contract | memory/SQLite/Postgres | 存储可替换 |
| Fault injection | crash/replay/unknown | 无重复 semantic effect |
| Gate fixtures | r17/骨架/零结果 | 历史缺陷不复发 |
| Graph PoC | kill/resume/migration | 编排不破坏权威 |
| API | client contract/idempotency | 路由安全 |
| Frontend unit | A+C/锁/决策/选区 | 状态投影正确 |
| Browser E2E | 用户真实点击 | 易用性与全按钮 |
| Clinical/QC | full coverage/fresh verifier | P0–P4=0 |
| OOXML/Word | structure/native/round-trip | 可提交交付 |
| Shadow/cutover | read-only/rollback | 迁移可逆 |

## 8. 关键风险、控制与回滚

| 风险 | 前置信号 | 控制 | 回滚 |
|---|---|---|---|
| Word producer 不可靠 | timeout、辅助权限、无法 reopen | Phase 0 先证伪；reservation | Phase 1–5 标 NO_RELEASE，阻断 6–8/发布 |
| 无 Git/源码漂移 | status 不可查 | live manifest+隔离副本 Git | 恢复 pre-implementation tar；live 不建 Git |
| 双事实源 | canvas/summary 与 v3 不同 | reducers、EditClass、CAS | NEW_CANONICAL 后只暂停新链，legacy 不恢复写 |
| checkpoint 重放副作用 | event/checkpoint split | outbox/inbox/reservation | 从 event 重建 |
| E1 死锁 | linked Protocol blocked | 修复/替代链接；用户仅身份重分类 | 保持阻断，不缩分母 |
| Chapter Contract 真空 | required 均为空 | non-vacuous lint | 禁用 Agent③ |
| 空泛长文 | 字数高但 claim/object 缺 | substantive contract | 局部重写 |
| reviewer 抽样 clean | digest row 未审 | 110/110 coverage reducer | Q1 阻断 |
| editor 不满足 Word | section/field/round-trip 缺 | capability PoC | 更换开源候选或原生桥接 |
| old store 被写 | shadow diff | read-only adapter+monitor | 关闭 flag，恢复 snapshot |
| Provider 敏感数据越界 | payload/region policy fail | minimal artifact refs/allowlist | fail closed |
| E2E 伪通过 | 空正文/API-only/no Word | artifact verifier | 该轮不计 clean streak |

## 9. 未决外部依赖与处理

1. **Ⅰ期公司模板权威：** TP-MA-05、TP-MA-06、CMSS-SOP T02 已发现；待裁定
   当前权威、版本替代和非肿瘤/肿瘤双树。Ⅱ/Ⅲ期可继续，Ⅰ期完成声明阻断。
2. **正式源码仓库：** 当前 workbench 无 Git。Phase 0 在 live 生成 source-only
   manifest 并创建隔离实现区；若发现正式 repo，优先用正式 worktree。
3. **Word 自动化权限/目标工作站：** Phase 0 在真实 Microsoft Word 环境验证；
   无权限时不是产品 PASS。
4. **PostgreSQL 可用性：** 仅 PoC 后锁定；没有本地部署能力则继续 repository
   abstraction，不假称完成。
5. **编辑器内核：** 不预选。TipTap 只是 baseline；任何候选必须开源许可合规
   且完整满足 D011/D012。
6. **Harness provider/region policy：** 每次运行使用当前 registry 与全局 route
   policy；计划不保存凭证或硬编码秘密。

## 10. 每个任务的提交与审阅模板

隔离 implementation workspace 建立 Git 基线后，每个任务按以下顺序；live
workbench 保持证据库语义：

1. 只提交该任务的 failing test/fixture；
2. 运行最小测试并保存预期失败；
3. 提交最小实现；
4. 运行最小测试；
5. 运行相邻合同测试；
6. worker 写 compact handoff：sources、diff、tests、failed paths、uncertainty；
7. fresh verifier 先做 spec compliance，再做 code quality；
8. Codex 核对实际 diff、测试、真实 runtime/artifact；
9. 更新 context/runs/reviews/metrics；
10. 原子 commit，消息采用：

    test(protocol-v3): add <contract> failure coverage
    feat(protocol-v3): implement <bounded behavior>
    fix(protocol-v3): close <error-code> invariant

不得把一个 Phase 合并成单个巨大提交；不得为了清绿删除负向 fixture、降级 gate、
改 expected 或标 xfail。

## 11. 计划实施顺序

唯一允许的起点是 Task 0.1。推荐执行序列：

1. 0.1→0.6，H0–H6 / P0-CORE；其中 0.2 只读、0.5 才允许受控 hygiene；
2. 0.7→0.8，P0-WORD；失败则记录 NO_RELEASE，不启动 Phase 6/7/8；
3. 1.1→1.11，P1-G1；
4. 2.1→2.5，P2-G2；
5. 3.1→3.5，P3-G3；
6. 4.1→4.7，E0–E3；
7. 5.1→5.5，D1；
8. 6.0→6.7，W1/UI1；其中 6.0 必须先于任何新 UI 实现；
9. 7.1→7.7，Q1/F1；
10. 8.1→8.7，R1。

Phase 内只有真正独立的测试、adapter 或 UI 组件可以并行；canonical schema、
reducers、storage selection、graph selection、chapter contracts、final gate 和
cutover 必须串行锁定。

## 12. 本计划自身的验收

本计划提交实施前必须：

- 由 fresh-context reviewer 从 r17 失败、design-v1.2、Word producer、事实权威、
  Chapter Contract、迁移/回滚和 E2E 七个面进行反证；
- 修复全部 P0/P1 计划缺口；P2 需有明确 gate/owner；
- 确认所有拟改路径存在或明确为 Create；
- 确认计划没有把 CSR 或独立 Synopsis 工作流带回；
- 确认 PostgreSQL、LangGraph、MAF、编辑器或 Word producer 均保持候选；
  LangGraph 仅是 design-v1.2 首选调度器，P2-G2 后才锁定；
- 确认仓库清理只处理可再生物或可恢复 quarantine，历史证据和医学监查受保护；
- 再由用户批准本计划。

历史 `MW_PROTOCOL_REARCHITECTURE_DESIGN_READY_FOR_USER_REVIEW_20260809.md` 保持
不可变；本计划是其 current supersession。用户批准后，Task 0.1 才在隔离
workspace 新建 plan-approved status run，记录本计划 hash、两轮 challenge、DC-018
和安全停止点，不回写历史 checkpoint。

用户批准前的安全停止点：本文件完成、产品仍冻结、Phase 0 未开始。

## 13. 独立反证闭合记录

- 首轮 verdict：`REJECT / NOT_READY`；修复 live Git、Ⅰ期模板事实、Word 停止线、
  编辑器顺序、前端 runner、API/migration、r17/D017 与 E2E 分母等 P1。
- 二轮 verdict：`REJECT / NOT_READY`；将 hygiene 改为外部 bootstrap、先保护与
  重建、后可恢复 mutator，并消除 npm/pnpm 后续命令分叉。
- 最终 hygiene-only verdict：`READY`，P0=0、P1=0；审阅输入计划 SHA-256
  `e720146fba089fd368c6038f702c06fc7df34e20c4b8757e886daa3ec7dda2f9`。
- Reviewer 为 fresh context，只读检查计划/design/证据；没有参与计划写作，也未
  修改产品或运行系统。

当前安全停止点不变：等待用户批准本详细实施计划；批准后只从 Task 0.1 开始。
