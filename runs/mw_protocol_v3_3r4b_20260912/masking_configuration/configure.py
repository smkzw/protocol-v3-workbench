import json
from pathlib import Path
from app.protocol_workflow.registries.applicability import FactPredicate,RulePredicate,ApplicabilityRuleCatalog
from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog,build_direct_fact_catalog
from app.protocol_workflow.registries.chapters import load_chapter_registry,lint_registry
from scripts.qc.protocol_v3.assemble_chapter_registry import assemble_registries
from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
b=Path('config/medical_writing/protocol_v3/templates/tp_ma_07_v2');pre='framing.structured_design.';features=pre+'masking_features'
p=b/'chapter_contracts/v2_n_4_5.json';raw=json.loads(p.read_text());old=raw['conditional_applicability_rules'];Path('runs/mw_protocol_v3_3r4b_20260912/masking_configuration/superseded_rules.json').write_text(json.dumps(old,ensure_ascii=False,indent=2)+'\n')
raw['contract_version']=raw['chapter_skill_version']='3.4.0'
raw['substantive_content']['fact_requirements'] += [dict(fact_path='diagram.randomized',obligation='optional',rationale='复用已确认随机设计结构化布尔，不以文字猜测。'),dict(fact_path=features,obligation='required',rationale='结构化对象：blinding_applied、emergency_unblinding_required、unblinded_personnel_present为明确布尔；前者包含部分设盲，后两项按实际程序确认，不因部分设盲默认需要紧急揭盲。')]
def rule(suffix,facts,claims=()):
 return dict(conditional_applicability_rule_id='applicability:v2_n_4_5:'+suffix,triggering_fact_paths=['diagram.randomized'] if suffix=='active' else [features],condition={'active':'已确认随机化设计','blinding':'已确认存在部分或全部设盲','emergency':'设盲且实际设计需要紧急揭盲程序','personnel':'设盲且明确存在非盲工作人员'}[suffix],rationale='源body-child364–369按实际适用性；开放设计仍需偏倚控制理由与分配安排，不能虚构揭盲。',required_when_active_fact_paths=[pre+x for x in facts],required_when_active_claim_types=list(claims))
raw['conditional_applicability_rules']=[rule('active',['randomization_procedure','allocation_ratio']),rule('blinding',['masking_maintenance','accidental_unblinding','unblinding_records'],['unblinding_procedure']),rule('emergency',['emergency_unblinding']),rule('personnel',['unblinded_personnel'])]
c=ChapterContractV2.model_validate_json(json.dumps(raw));p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
p=b/'chapter_skills/v2_n_4_5.json';raw=json.loads(p.read_text());raw['skill_version']='3.4.0';raw['prompt_contract']['instructions']+=' 随机化与设盲分别判断；部分设盲不自动等于需紧急揭盲。开放设计仍须说明偏倚控制、理由和实际分配安排。仅按明确masking_features选择维护、意外揭盲、记录、紧急揭盲及非盲人员措施。';p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
p=b/'applicability_rules.json';raw=json.loads(p.read_text());rid=old[0]['conditional_applicability_rule_id'];assert rid in raw['pending_rule_ids'];raw['pending_rule_ids'].remove(rid)
for r in c.conditional_applicability_rules:
 suffix=r.conditional_applicability_rule_id.rsplit(':',1)[1]
 preds=[FactPredicate(fact_path='diagram.randomized',expected=True)] if suffix=='active' else [FactPredicate(fact_path=features,members=('blinding_applied',),expected=True)]
 if suffix in ('emergency','personnel'):preds.append(FactPredicate(fact_path=features,members=(('emergency_unblinding_required' if suffix=='emergency' else 'unblinded_personnel_present'),),expected=True))
 cells={'active':('randomization:procedure','randomization:ratio'),'blinding':('masking:maintenance','unblinding:records'),'emergency':('unblinding:emergency',),'personnel':()}[suffix]
 x=RulePredicate(rule_id=r.conditional_applicability_rule_id,source_rule_sha256=r.material_sha256(),source_contract_sha256=c.material_sha256(),predicates=tuple(preds),conditional_fact_paths=r.required_when_active_fact_paths,conditional_claim_types=r.required_when_active_claim_types,conditional_evidence_admission_types=('unblinding_procedure',) if suffix=='blinding' else (),conditional_object_cells=cells)
 raw['rules'].append(x.model_dump(mode='json'))
s=json.dumps(raw,ensure_ascii=False,indent=2)+'\n';ApplicabilityRuleCatalog.model_validate_json(s);p.write_text(s)
p=Path('tests/fixtures/protocol_v3/chapter_content_v2/batch3.json');raw=json.loads(p.read_text());raw['fact_vocabulary']=sorted(set(raw['fact_vocabulary'])|{features,'diagram.randomized'});p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
reg=load_chapter_registry(assemble_registries(b/'chapter_contracts',b/'chapter_skills',[Path(f'tests/fixtures/protocol_v3/chapter_content_v2/batch{i}.json') for i in range(1,9)]));p=b/'fact_bindings.json';old=FactBindingCatalog.model_validate_json(p.read_text());cat=build_direct_fact_catalog(reg,declarations=old.bindings);cat=cat.model_copy(update={'bindings':tuple(x.model_copy(update={'value_type':'object'}) if x.fact_path==features else x for x in cat.bindings)});p.write_text(cat.model_dump_json(indent=2)+'\n')
report=lint_registry(b,reg,require_complete=True);Path('runs/mw_protocol_v3_3r4b_20260912/masking_configuration/lint.json').write_text(report.model_dump_json(indent=2)+'\n');print(report.status,len(report.findings))
