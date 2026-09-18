import json
from pathlib import Path
from app.protocol_workflow.registries.applicability import RulePredicate,FactPredicate,ApplicabilityRuleCatalog
from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog,build_direct_fact_catalog
from app.protocol_workflow.registries.chapters import load_chapter_registry,lint_registry
from scripts.qc.protocol_v3.assemble_chapter_registry import assemble_registries
from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
b=Path('config/medical_writing/protocol_v3/templates/tp_ma_07_v2')
p=b/'chapter_contracts/v2_n_7_2.json';raw=json.loads(p.read_text())
raw['contract_version']=raw['chapter_skill_version']='3.4.0'
r=raw['conditional_applicability_rules'][0]
r['triggering_fact_paths']=['diagram.randomized']
r['condition']='已确认本项目为随机化设计，不限于 D1 随机化'
r['rationale']='随机化设计必须给出实际时点规则；D1 仅为源模板示例。复用流程图已有随机设计状态，不从给药日或非空文字推断。'
c=ChapterContractV2.model_validate_json(json.dumps(raw));p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
p=b/'chapter_skills/v2_n_7_2.json';raw=json.loads(p.read_text());raw['skill_version']='3.4.0';raw['prompt_contract']['instructions']+=' 已确认随机化设计无论是否在D1，均须提供实际随机化时点规则；非D1不等于非随机。'
p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
r=c.conditional_applicability_rules[0]
p=b/'applicability_rules.json';raw=json.loads(p.read_text());rid=r.conditional_applicability_rule_id
assert rid in raw['pending_rule_ids']
x=RulePredicate(rule_id=rid,source_rule_sha256=r.material_sha256(),source_contract_sha256=c.material_sha256(),predicates=(FactPredicate(fact_path='diagram.randomized',expected=True),),conditional_fact_paths=r.required_when_active_fact_paths)
raw['rules'].append(x.model_dump(mode='json'));raw['pending_rule_ids'].remove(rid)
s=json.dumps(raw,ensure_ascii=False,indent=2)+'\n';ApplicabilityRuleCatalog.model_validate_json(s);p.write_text(s)
reg=load_chapter_registry(assemble_registries(b/'chapter_contracts',b/'chapter_skills',[Path(f'tests/fixtures/protocol_v3/chapter_content_v2/batch{i}.json') for i in range(1,9)]))
p=b/'fact_bindings.json';old=FactBindingCatalog.model_validate_json(p.read_text());new=build_direct_fact_catalog(reg,declarations=old.bindings);p.write_text(new.model_dump_json(indent=2)+'\n')
report=lint_registry(b,reg,require_complete=True)
Path('runs/mw_protocol_v3_3r4b_20260912/treatment_randomization_configuration/lint.json').write_text(report.model_dump_json(indent=2)+'\n')
print(report.status,len(report.findings))
