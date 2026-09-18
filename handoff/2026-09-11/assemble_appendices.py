"""Assemble reference appendices from actual files. Writes only this handoff folder."""
from pathlib import Path
import json, hashlib, datetime
HERE=Path(__file__).resolve().parent
W=HERE.parents[1]
U=W.parent/"plan-upgrade-20260905"
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def link(p,label=None): return f"[{label or p.name}](<{p.resolve()}>)"
state=json.loads((HERE/"current_state_verification.json").read_text())
doc=HERE/"HANDOFF_PROTOCOL_V3_20260911.md"
s=doc.read_text()
assert "\n## 14." not in s
s+="\n## 14. 权威文档与逐文件证据索引\n\n### 14.1 当前权威文件：9月11日实测哈希\n\n原文件只读。本次以下7项均与9月8日暂停权威哈希一致；新Agent仍须在实际开工时读最新全局AGENTS。\n\n| 文件 | SHA-256 |\n|---|---|\n"
for r in state["authority_checks"]:
 p=Path(r["path"]); s+=f"| {link(p,str(p))} | {r['sha256']} |\n"
supp=[
(Path("/Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07_研究流程图示例.svg"),"c08dc55324b92ed45e283335c1e28a7955993cd42f687c0ca1395c4730c0372c","支持SVG，example-only"),
(Path("/Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07 临床试验方案（2期或3期）_AI修订追踪版_20260905.docx"),"cc352adc4a2363a14eabc143a0298c9ad25fcacf43442724dc44738b4ee1e319","修订历史，不替代清洁版"),
(Path("/Users/smkzw/Documents/康哲项目资料/SOP/CMSS-SOP-MD-5101_GCP2026_ICHE6R3_修订版_DOCX/CMSS-SOP-MD-5101-R03-00  临床研究方案QC表_修订版.docx"),"5a5affebd36979cb06e9de239accc163f954c186afcdf3668f23d054400519e9","3R.5来源；文件名中R03-00后有两个空格"),
(Path("/Users/smkzw/Documents/康哲项目资料/SOP/CMSS-SOP-MD-5101_GCP2026_ICHE6R3_修订版_DOCX/CMSS-SOP-MD-5101-T02-00 I期临床研究方案模板_修订版.docx"),"fb89e3eb539e17485274f0c6c4add78527fe596c8c0a20b82e448b94fa7676db","3R.6推荐候选，尚待用户选择")]
s+="\n### 14.2 补充模板来源\n\n| 文件及意义 | 当天SHA-256 | 与既有记录 |\n|---|---|---|\n"
checks=[]
for p,expected,note in supp:
 h=sha(p) if p.exists() else None
 checks.append({"path":str(p),"sha256":h,"expected_sha256":expected,"match":h==expected})
 s+=f"| {link(p)}：{note} | {h} | {'一致' if h==expected else '不一致/需核对'} |\n"
(HERE/"supplementary_authority_checks.json").write_text(json.dumps(checks,ensure_ascii=False,indent=2)+"\n")
refs=[
("当前附加Plan","plans/mw_protocol_v3_review_amendment_20260905.md"),
("状态索引（历史表与当前指针分开）","plans/mw_protocol_v3_execution_tracking_20260905.md"),
("Trellis执行规范",".trellis/spec/protocol-v3.md"),
("当前Task3R.3 PRD",".trellis/tasks/09-06-protocol-v3-3r3/prd.md"),
("当前Task3R.3 design",".trellis/tasks/09-06-protocol-v3-3r3/design.md"),
("当前Task3R.3 implement",".trellis/tasks/09-06-protocol-v3-3r3/implement.md"),
("当前Task3R.3 checkpoint",".trellis/tasks/09-06-protocol-v3-3r3/checkpoint.md"),
("完整工程review（含已被修复/撤回历史）","reviews/mw_protocol_v3_engineering_review_20260905.md"),
("前端专门发现","reviews/mw_protocol_v3_frontend_readonly_findings_20260906.md"),
("全仓旧链失败处置","reviews/mw_protocol_v3_legacy_collection_disposition_20260905.md"),
("P1R scoped integration",".trellis/tasks/09-05-protocol-v3-p1r-integration/checkpoint.md"),
("1R.2功能与未收束状态",".trellis/tasks/09-05-protocol-v3-1r2/checkpoint.md"),
("1R.3集成验收",".trellis/tasks/09-05-protocol-v3-1r3/checkpoint.md"),
("1R.4持久化与兼容验收",".trellis/tasks/09-05-protocol-v3-1r4/checkpoint.md"),
("1R.6模型与probe验收",".trellis/tasks/09-05-protocol-v3-1r6/checkpoint.md"),
("3R.1来源核对","reviews/mw_protocol_v3_3r1_codex_source_checks_20260906.md"),
("3R.4依赖准备（不是已实现图）","reviews/mw_protocol_v3_3r4_dependency_preparation_20260906.md"),
("8月12日暂停","runs/MW_PROTOCOL_V3_TASK21_NO_LOSS_PAUSE_20260812_0708.md"),
("8月Phase1功能门","reviews/codex_mw_protocol_v3_p1g1_functional_gate_20260812_review.md"),
("原始多Agent设计","plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md"),
("原始设计决定","plans/mw_system_rearchitecture_design_decisions_20260808.md")]
s+="\n### 14.3 状态、review、来源准备与历史设计\n\n| 用途 | 路径 |\n|---|---|\n"
for title,rel in refs:
 s+=f"| {title} | {link(W/rel,rel)} |\n"
for i in range(1,9):
 rel=f"reviews/mw_protocol_v3_3r3_batch{i}_content_spec_20260906.md"
 s+=f"| batch{i}逐段来源义务 | {link(W/rel,rel)} |\n"
s+="\n### 14.4 关键代码冻结身份与源码导航\n\n下表是本轮读取当前文件的hash，不是重新验收。3R.3内容文件与checker/assembler的接受范围仍按第7节分别判断。\n\n| 文件 | SHA-256 |\n|---|---|\n"
for rel in ("packages/contracts/workbench_contracts/protocol_v3.py","services/api/app/protocol_workflow/registries/chapters.py","scripts/qc/protocol_v3/lint_chapter_registry.py","scripts/qc/protocol_v3/assemble_chapter_registry.py","tests/fixtures/protocol_v3/chapter_content_v2/batch1.json","tests/protocol_v3/test_chapter_batch1.py"):
 p=W/rel;s+=f"| {link(p,rel)} | {sha(p)} |\n"
paths=set((W/"services/api/app/protocol_workflow").rglob("*.py"))
paths.update(p for p in (W/"frontend/src/features/medical-writing").rglob("*") if p.is_file() and p.suffix in (".jsx",".js",".mjs",".css"))
paths.update([W/"frontend/src/App.jsx",W/"services/api/app/main.py",W/"packages/contracts/workbench_contracts/protocol_v3.py"])
paths=sorted(p for p in paths if "__pycache__" not in str(p))
inventory=[{"path":str(p),"relative":str(p.relative_to(W)),"bytes":p.stat().st_size,"sha256":sha(p)} for p in paths]
(HERE/"source_component_inventory.json").write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+"\n")
nav="# Protocol v3 与现有写作前端：当前文件索引\n\n生成于2026-09-11。作用是源码定位与文件身份，不代表每个函数本轮重新review/运行；包含现有测试/样式文件。后端legacy业务主文件另从services/api/app/medical_writing_*按第5–6节定位。\n\n| 文件 | 字节数 | SHA-256 |\n|---|---:|---|\n"
for r in inventory: nav+=f"| {link(Path(r['path']),r['relative'])} | {r['bytes']} | {r['sha256']} |\n"
(HERE/"SOURCE_COMPONENT_INDEX.md").write_text(nav)
s+=f"\n逐个模块、前端组件、样式/测试文件的可点击路径：{link(HERE/'SOURCE_COMPONENT_INDEX.md')}；机器索引：{link(HERE/'source_component_inventory.json')}。共{len(inventory)}个文件；不把目录/文件存在等同业务已实现。\n"
g=json.loads((HERE/"goal_snapshot.json").read_text())
s+="\n## 15. 当前原生 Goal 原文（逐字保留）\n\n2026-09-11通过正式get_goal只读取得，状态paused。下面仅复制objective，不重新激活、不改写目标。原文中的1R.2续作位置、阶段门泛称，应结合第3节后续用户决定和第4/7节最新状态解释。纯文本文件的UTF-8 SHA-256："+state["goal_utf8_sha256"]+"。\n\n~~~text\n"+g["objective"]+"\n~~~\n"
s+="\n## 16. 给接手 Agent 的首条续作提示\n\n以下是可直接使用的交接提示。由用户在接手任务中明确发送继续后执行，不是本交出任务自动恢复的指令：\n\n~~~text\n请按 HANDOFF_PROTOCOL_V3_20260911.md 接手医学写作子系统 Protocol v3。先完整读取最新全局与项目AGENTS、design-v1.3、Implementation Plan v2、隔离区附加Plan、3R.3 Trellis与2026-09-08无损暂停记录，并核对9月11日交接验证。\n当前在Task3R.3。不要从Goal旧句1R.2或r42翻译失败项重做。R、1R、2R.1、3R.1/3R.2及3R.3 core有各自验收；首批12合同修复未验收，第二批16合同已启动过但未交付。先对账两个logical key及原生session。原model-io日志已在9月11日发现缺失，session数据库记录仍在，不能保证逐条历史完整；确认原生续接可用性，无法原生续接时显式记录恢复血统，从现有产物继续，不伪造日志或重派重复工作。\n完成首批六类内容问题、17行摘要、独立证据组、原48fixture保留与有效负例，运行现有主审内容/组装/多批测试并独立复核。然后继续第二批至第八批、dependency图、R03 QC；到3R.6准备Ⅰ期模板问题卡等我选择。保持Trellis单一执行状态，阶段报告不暂停，不再让我反复说继续。\n用户已批准：纯安全工程及测试不构建，旧阶段断言若不损科学性可评估废弃；1R.4保留功能恢复语义；PyMuPDF个人使用；工程subAgent允许；当前UX上限20点击/5必填自由文本。高风险8类逐卡人审，理由AI预填；最终方案内容与Word格式必须真实验收。\n不碰live、8910、医学监查、plan-upgrade或外部SOP，不清理历史。产品1R.6连通性探针已经SUCCEEDED，不重复。按当前global route和runner，定期重读AGENTS；慢任务同会话长等待，先logical key对账再resume/retry/fallback。持续向完整AI lead研究方案产品推进，不以测试数字替代正文、浏览器、Word及真实项目验收。\n~~~\n"
doc.write_text(s)
print(json.dumps({"doc_bytes":doc.stat().st_size,"doc_lines":len(s.splitlines()),"inventory_files":len(inventory),"supplementary_mismatches":[r for r in checks if not r["match"]]},ensure_ascii=False))
