import json
from pathlib import Path
from app.protocol_workflow.registries.applicability import FactPredicate,RulePredicate,ApplicabilityRuleCatalog
from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog,build_direct_fact_catalog
from app.protocol_workflow.registries.chapters import load_chapter_registry,lint_registry
from scripts.qc.protocol_v3.assemble_chapter_registry import assemble_registries
from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2,EvidenceSourceRequirement
b=Path('config/medical_writing/protocol_v3/templates/tp_ma_07_v2');p=b/'chapter_contracts/v2_n_4_2.json';raw=json.loads(p.read_text());old=raw['conditional_applicability_rules'];out=Path('runs/mw_protocol_v3_3r4b_20260912/design_rationale_configuration');(out/'superseded_rules.json').write_text(json.dumps(old,ensure_ascii=False,indent=2)+'\n')
raw['contract_version']=raw['chapter_skill_version']='3.4.0'
spec=[('noninferiority','design.noninferiority_applicable','framing.structured_design.noninferiority_margin_decision',['noninferiority_margin_decision']),('placebo','design.placebo_control_applicable','framing.structured_design.placebo_decision',[])]
raw['conditional_applicability_rules']=[]
for name,flag,detail,claims in spec:
 raw['substantive_content']['fact_requirements'].append(dict(fact_path=flag,obligation='optional',rationale='结构化原生布尔，由已确认假设/对照事实给出；未知不默认不适用，不新增用户自由文本。'))
 raw['conditional_applicability_rules'].append(dict(conditional_applicability_rule_id='applicability:v2_n_4_2:'+name,triggering_fact_paths=[flag],condition='已确认存在非劣效假设' if name=='noninferiority' else '已确认存在安慰剂对照',rationale='源body-child355对照与设计按实际项目选择；不把示例升级为全部设计义务，保留所有基础对照/假设论证。',required_when_active_fact_paths=[detail],required_when_active_claim_types=claims))
c=ChapterContractV2.model_validate_json(json.dumps(raw));p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
p=b/'chapter_skills/v2_n_4_2.json';raw=json.loads(p.read_text());raw['skill_version']='3.4.0';raw['prompt_contract']['instructions']+=' 仅在存在已确认非劣效假设时给出界值决定与论证；安慰剂决定按实际对照适用性。普通优效设计不得索要非劣效界值；任何设计均保留对照与假设依据。';p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
p=b/'applicability_rules.json';raw=json.loads(p.read_text());rid=old[0]['conditional_applicability_rule_id'];assert rid in raw['pending_rule_ids'];raw['pending_rule_ids'].remove(rid)
for r,(_,flag,detail,claims) in zip(c.conditional_applicability_rules,spec):
 ev=(EvidenceSourceRequirement(source_roles=('project_primary',),admission_claim_types=('noninferiority_margin_decision',),allowed_locator_kinds=('body','table'),require_context_window=True,minimum_quality_score=0.93),) if claims else ()
 x=RulePredicate(rule_id=r.conditional_applicability_rule_id,source_rule_sha256=r.material_sha256(),source_contract_sha256=c.material_sha256(),predicates=(FactPredicate(fact_path=flag,expected=True),),conditional_fact_paths=(detail,),conditional_claim_types=tuple(claims),active_evidence_requirements=ev)
 raw['rules'].append(x.model_dump(mode='json'))
s=json.dumps(raw,ensure_ascii=False,indent=2)+'\n';ApplicabilityRuleCatalog.model_validate_json(s);p.write_text(s)
p=Path('tests/fixtures/protocol_v3/chapter_content_v2/batch3.json');raw=json.loads(p.read_text());raw['fact_vocabulary']=sorted(set(raw['fact_vocabulary'])|{x[1] for x in spec});p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
reg=load_chapter_registry(assemble_registries(b/'chapter_contracts',b/'chapter_skills',[Path(f'tests/fixtures/protocol_v3/chapter_content_v2/batch{i}.json') for i in range(1,9)]));p=b/'fact_bindings.json';old=FactBindingCatalog.model_validate_json(p.read_text());cat=build_direct_fact_catalog(reg,declarations=old.bindings);flags={x[1] for x in spec};cat=cat.model_copy(update={'bindings':tuple(x.model_copy(update={'value_type':'boolean'}) if x.fact_path in flags else x for x in cat.bindings)});p.write_text(cat.model_dump_json(indent=2)+'\n')
report=lint_registry(b,reg,require_complete=True);(out/'lint.json').write_text(report.model_dump_json(indent=2)+'\n');print(report.status,len(report.findings))
