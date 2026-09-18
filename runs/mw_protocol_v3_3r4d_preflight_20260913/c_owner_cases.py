import json
from app.protocol_workflow.registries.chapters import load_chapter_registry
from app.protocol_workflow.registries.dependency_graph import build_dependency_graph, build_fact_labeled_impact_plan
from app.protocol_workflow.registries.applicability import RulePredicate, FactPredicate
from test_dependency_graph import _registry, _chapter, _conditional_rule

def scenario(base_requirement, shared):
    rules = [_conditional_rule('rule:a', triggers=('trigger.a',), when_active=('payload.x',))]
    if shared: rules.append(_conditional_rule('rule:b', triggers=('trigger.b',), when_active=('payload.x',)))
    doc=load_chapter_registry(_registry([_chapter('v2_t_a',facts=((('payload.x','required'),) if base_requirement else (('plain.x','required'),)),conditional_rules=tuple(rules))]))
    declarations=[]
    for i,rule in enumerate(doc.chapters[0].contract.conditional_applicability_rules):
        declarations.append(RulePredicate(rule_id=rule.conditional_applicability_rule_id,source_rule_sha256=rule.material_sha256(),predicates=(FactPredicate(fact_path='trigger.'+('a' if i==0 else 'b'),expected=True),),source_contract_sha256=doc.chapters[0].contract.material_sha256(),conditional_fact_paths=('payload.x',)))
    before={'payload.x':1};after={'payload.x':2}
    if shared: before['trigger.a']=True;after['trigger.a']=True
    plan=build_fact_labeled_impact_plan(build_dependency_graph(doc),facts_before=before,facts_after=after,rules=tuple(declarations))
    return {'base_requirement':base_requirement,'shared':shared,'confirmation':plan.entries[0].confirmation,'rules':[{'id':r.rule_id,'after':r.state_after} for r in plan.entries[0].rule_plans]}
print(json.dumps([scenario(True,False),scenario(False,True)],ensure_ascii=False,indent=2))
