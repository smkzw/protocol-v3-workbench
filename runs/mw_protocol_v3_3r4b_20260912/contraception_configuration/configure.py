import json
from pathlib import Path
from app.protocol_workflow.registries.applicability import FactPredicate,RulePredicate,ApplicabilityRuleCatalog
from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog,build_direct_fact_catalog
from app.protocol_workflow.registries.chapters import load_chapter_registry,lint_registry
from scripts.qc.protocol_v3.assemble_chapter_registry import assemble_registries
from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
b=Path('config/medical_writing/protocol_v3/templates/tp_ma_07_v2');out=Path('runs/mw_protocol_v3_3r4b_20260912/contraception_configuration');flag='picos.risk.pregnancy_contraception';contracts=[]
for node in ['v2_n_5_2','v2_n_5_3']:
 p=b/f'chapter_contracts/{node}.json';raw=json.loads(p.read_text());raw['contract_version']=raw['chapter_skill_version']='3.4.1'
 if not any(x['fact_path']==flag for x in raw['substantive_content']['fact_requirements']):raw['substantive_content']['fact_requirements'].append(dict(fact_path=flag,obligation='optional',rationale='复用共享结构化妊娠/避孕适用性决定与理由；不推定通用期限。'))
 r=raw['conditional_applicability_rules'][0]
 if node=='v2_n_5_3':
  r['condition']='项目明确确认妊娠/避孕措施适用';r['rationale']='仅控制避孕期限及对应表格单元格；其他生活方式范围、时点、例外和处理措施始终独立保留。';r['required_when_active_fact_paths']=['population.lifestyle.contraception_duration'];r['required_when_active_claim_types']=[]
 else:r['rationale']+=' 适用性从共享对象applicable原生布尔读取并保留reason，不从文本或人群性别单独推断。'
 c=ChapterContractV2.model_validate_json(json.dumps(raw));contracts.append(c);p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
 p=b/f'chapter_skills/{node}.json';raw=json.loads(p.read_text());raw['skill_version']='3.4.1';raw['prompt_contract']['instructions']+=' 妊娠/避孕适用性复用共享applicable与reason决定，不推定通用期限或简单从性别判断；纳排引用已确认资格事实，生活方式措施独立，只有明确适用时要求避孕期限。';p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
p=b/'applicability_rules.json';raw=json.loads(p.read_text())
for c in contracts:
 r=c.conditional_applicability_rules[0];rid=r.conditional_applicability_rule_id;assert rid in raw['pending_rule_ids'];raw['pending_rule_ids'].remove(rid)
 x=RulePredicate(rule_id=rid,source_rule_sha256=r.material_sha256(),source_contract_sha256=c.material_sha256(),predicates=(FactPredicate(fact_path=flag,members=('applicable',),expected=True),),conditional_fact_paths=r.required_when_active_fact_paths,conditional_object_cells=('lifestyle:contraception',) if c.semantic_node_id=='v2_n_5_3' else ())
 raw['rules'].append(x.model_dump(mode='json'))
s=json.dumps(raw,ensure_ascii=False,indent=2)+'\n';ApplicabilityRuleCatalog.model_validate_json(s);p.write_text(s)
reg=load_chapter_registry(assemble_registries(b/'chapter_contracts',b/'chapter_skills',[Path(f'tests/fixtures/protocol_v3/chapter_content_v2/batch{i}.json') for i in range(1,9)]));p=b/'fact_bindings.json';old=FactBindingCatalog.model_validate_json(p.read_text());cat=build_direct_fact_catalog(reg,declarations=old.bindings);cat=cat.model_copy(update={'bindings':tuple(x.model_copy(update={'value_type':'object','required_members':{'applicable':'boolean','reason':'string'}}) if x.fact_path==flag else x for x in cat.bindings)});p.write_text(cat.model_dump_json(indent=2)+'\n');report=lint_registry(b,reg,require_complete=True);(out/'lint.json').write_text(report.model_dump_json(indent=2)+'\n');print(report.status,len(report.findings))
