import json
from pathlib import Path
from app.protocol_workflow.registries.applicability import FactPredicate,RulePredicate,ApplicabilityRuleCatalog
from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog,build_direct_fact_catalog
from app.protocol_workflow.registries.chapters import load_chapter_registry,lint_registry
from scripts.qc.protocol_v3.assemble_chapter_registry import assemble_registries
from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2,EvidenceSourceRequirement
b=Path('config/medical_writing/protocol_v3/templates/tp_ma_07_v2');flags=['intervention.background_therapy_applicable','design.rescue_treatment_planned']
p=b/'chapter_contracts/v2_n_3_1_2_4.json';raw=json.loads(p.read_text());raw['contract_version']=raw['chapter_skill_version']='3.4.0';r=raw['conditional_applicability_rules'][0];r['triggering_fact_paths']=flags;r['rationale']='源body-child318、324要求补救/背景治疗处置与分析一致；复用干预布尔状态而非群体汇总指标文字。该条件只控制专属crosscheck，其他相关ICE定义、策略、理由和群体指标始终保留。'
raw['substantive_content']['fact_requirements'] += [dict(fact_path=f,obligation='optional',rationale='结构化原生布尔，复用已确认项目干预状态；未知由条件执行层阻止生成。') for f in flags]
c=ChapterContractV2.model_validate_json(json.dumps(raw));p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
p=b/'chapter_skills/v2_n_3_1_2_4.json';raw=json.loads(p.read_text());raw['skill_version']='3.4.0';raw['prompt_contract']['instructions']+=' 背景与补救治疗的跨合同复核使用明确项目状态；两者不适用不能免除停药等其他相关ICE的定义、策略、理由及其与分析的兼容说明。群体汇总指标不是条件布尔。';p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
r=c.conditional_applicability_rules[0];p=b/'applicability_rules.json';raw=json.loads(p.read_text());rid=r.conditional_applicability_rule_id;assert rid in raw['pending_rule_ids'];raw['pending_rule_ids'].remove(rid)
evidence=EvidenceSourceRequirement(source_roles=('project_primary',),admission_claim_types=('estimand_cross_contract_consistency',),allowed_locator_kinds=('body','table'),require_context_window=True,minimum_quality_score=0.9)
x=RulePredicate(rule_id=rid,source_rule_sha256=r.material_sha256(),source_contract_sha256=c.material_sha256(),predicates=tuple(FactPredicate(fact_path=f,expected=True) for f in flags),mode='any',conditional_fact_paths=r.required_when_active_fact_paths,conditional_claim_types=r.required_when_active_claim_types,active_evidence_requirements=(evidence,));raw['rules'].append(x.model_dump(mode='json'));s=json.dumps(raw,ensure_ascii=False,indent=2)+'\n';ApplicabilityRuleCatalog.model_validate_json(s);p.write_text(s)
p=Path('tests/fixtures/protocol_v3/chapter_content_v2/batch2.json');raw=json.loads(p.read_text());raw['fact_vocabulary']=sorted(set(raw['fact_vocabulary'])|set(flags));p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
reg=load_chapter_registry(assemble_registries(b/'chapter_contracts',b/'chapter_skills',[Path(f'tests/fixtures/protocol_v3/chapter_content_v2/batch{i}.json') for i in range(1,9)]));p=b/'fact_bindings.json';old=FactBindingCatalog.model_validate_json(p.read_text());p.write_text(build_direct_fact_catalog(reg,declarations=old.bindings).model_dump_json(indent=2)+'\n')
report=lint_registry(b,reg,require_complete=True);Path('runs/mw_protocol_v3_3r4b_20260912/ice_crosscheck_configuration/lint.json').write_text(report.model_dump_json(indent=2)+'\n');print(report.status,len(report.findings))
