import json
from pathlib import Path
from pydantic import ValidationError
from app.protocol_workflow.registries.chapters import ChapterSkillInput, ChapterContentPayload, evaluate_chapter_content, load_chapter_registry

OUT=Path(__file__).resolve().parent
r=load_chapter_registry(OUT/'current_assembled_registry.json')
c=next(x.contract for x in r.chapters if x.node_id=='v2_n_11_4_9')
base={'chapter_contract_id':c.chapter_contract_id,'node_id':c.semantic_node_id,'template_id':c.template_id,'template_sha256':c.template_sha256,'word_rules':c.word_rules}
results={}
for name,value in [('boolean_false',False),('boolean_true',True),('string_false','false'),('number',0.5),('structured_value',{'applicable':False})]:
    try:
        ChapterSkillInput(**base,resolved_facts={'statistics.interim.applicable':value})
        results[name]={'accepted':True}
    except ValidationError as e:
        results[name]={'accepted':False,'error_types':[x['type'] for x in e.errors()]}
# Valid clinical scenario: no interim analysis. The checker cannot represent a
# conditional exemption; a truthful not-planned statement still requires its details.
content=ChapterContentPayload.model_validate({'facts':[{'fact_path':'statistics.interim.applicable','value':'false'}],
    'claims':[{'claim_type':'interim_analysis_plan','statement':'本研究不计划期中分析。'}],
    'objects':[{'object_kind':'paragraph','occurrences':1,'text':'本研究不计划期中分析。'}]})
check=evaluate_chapter_content(c,content,subject_id='review:no-interim')
overlaps=[]
for e in r.chapters:
    required={f.fact_path for f in e.contract.substantive_content.fact_requirements if f.obligation.value=='required'}
    for rule in e.contract.conditional_applicability_rules:
        overlap=required & set(rule.required_when_active_fact_paths)
        if overlap:overlaps.append({'node':e.node_id,'rule':rule.conditional_applicability_rule_id,'unconditionally_required_active_paths':sorted(overlap)})
result={'input_type_results':results,'no_interim_check':check.model_dump(mode='json'),'conditional_vs_unconditional_overlap':overlaps,
 'note':'Overlaps are review candidates, not all automatic clinical defects. The no-interim case is concrete; no exemption is executed by current checker.'}
(OUT/'conditional_probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'input_types':results,'no_interim_passed':check.passed,'no_interim_error_codes':check.error_codes(),'overlap_rule_count':len(overlaps)},ensure_ascii=False,indent=2))
