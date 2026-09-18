"""Scratch reproduction: all_facts confirmation coupling vs scoped confirmation binding.

Read-only against source; uses the real canonical primitives
(bind_decision_inputs / current_input_validity / DecisionInputRef) exactly as
service.py:572-575 and service.py:904-908 call them.
"""
from app.protocol_workflow.canonical.decision_inputs import (
    DecisionInputRef, bind_decision_inputs, current_input_validity,
)

BOOKKEEPING = ("research.input_context", "research.regimen_producer")

# Facts at dose-adoption time (study-bound producer read them all).
facts_v1 = {
    "framing.study_phase": "II",
    "intervention.product_identity": {"name": "DrugA"},
    "intervention.dose_regimen": {"schedules": [{"step": 1, "dose": "10 mg"}]},
    "picos.intervention_dose_regimen.comparator_regimen": {"name": "Pbo"},
    "population.inclusion_modules": {"modules": ["adult"]},
    "research.input_context": {"source_intake_sha256": "a" * 64},
    "research.regimen_producer": {"workflow_run_id": "run:1"},
}

# Current producer refs, exactly as built by agent2/study_definition.py:37-44.
producer_refs = (
    DecisionInputRef(fact_path="intervention.dose_regimen"),
    DecisionInputRef(fact_path="research.input_context"),
    DecisionInputRef(fact_path="research.regimen_producer"),
    DecisionInputRef(fact_path="clinical-read-set", scope="all_facts",
                     excluded_fact_paths=BOOKKEEPING),
)
read_set_binding = bind_decision_inputs(producer_refs, facts_v1, "9"*64)

# -- Part A: the defect. Later endpoint/sample-size card adds its facts. -----
facts_v2 = dict(facts_v1)
facts_v2["statistics.sample_size.reproducible_result"] = {"n": 240}
facts_v2["endpoints.primary_efficacy"] = {"endpoint": "PFS"}
dose_basis_unchanged = all(
    facts_v2[p] == facts_v1[p] for p in
    ("intervention.dose_regimen", "research.input_context", "research.regimen_producer")
)
print("A1 dose basis unchanged:", dose_basis_unchanged)
print("A2 today's binding validity after endpoint+sample-size adoption:",
      current_input_validity(read_set_binding, facts_v2))

# -- Part B: proposed confirmation binding (server-declared scope). ----------
# Scope table materialized into refs: relevant paths individually bound +
# catch-all all_facts excluding bookkeeping and classified-irrelevant paths.
RELEVANT = ("intervention.dose_regimen", "intervention.product_identity",
            "picos.intervention_dose_regimen.comparator_regimen", "framing.study_phase",
            "population.inclusion_modules", "research.input_context",
            "research.regimen_producer")
IRRELEVANT = ("statistics.sample_size.reproducible_result", "endpoints.primary_efficacy")
def confirmation_refs(irrelevant):
    return tuple(DecisionInputRef(fact_path=p) for p in RELEVANT) + (
        DecisionInputRef(fact_path="clinical-read-set", scope="all_facts",
                         excluded_fact_paths=tuple(sorted(set(BOOKKEEPING + irrelevant)))),)
confirmation_binding = bind_decision_inputs(confirmation_refs(IRRELEVANT), facts_v1, "9"*64)

def show(label, facts, binding):
    print(f"   {label}: read_set={current_input_validity(read_set_binding, facts)}"
          f"  confirmation={current_input_validity(binding, facts)}")

print("B1 after later endpoint/sample-size adoption:")
show("   ", facts_v2, confirmation_binding)

print("B2 equal-value rewrite of an irrelevant path (no noise):")
facts_v3 = dict(facts_v2)
facts_v3["statistics.sample_size.reproducible_result"] = {"n": 240}
show("   ", facts_v3, confirmation_binding)

print("B3 value change of irrelevant classified path (later card revises its own fact):")
facts_v4 = dict(facts_v2)
facts_v4["statistics.sample_size.reproducible_result"] = {"n": 300}
show("   ", facts_v4, confirmation_binding)

print("B4 removal of irrelevant classified path:")
facts_v5 = {k: v for k, v in facts_v2.items() if k != "endpoints.primary_efficacy"}
show("   ", facts_v5, confirmation_binding)

print("B5 relevant path change (study phase flips):")
facts_v6 = dict(facts_v2)
facts_v6["framing.study_phase"] = "III"
show("   ", facts_v6, confirmation_binding)

print("B6 member change inside the adopted regimen value:")
facts_v7 = dict(facts_v2)
facts_v7["intervention.dose_regimen"] = {"schedules": [{"step": 1, "dose": "20 mg"}]}
show("   ", facts_v7, confirmation_binding)

print("B7 UNKNOWN new key (not classified at adoption time):")
facts_v8 = dict(facts_v2)
facts_v8["population.renal_adjustment"] = {"crcl": "<30"}
show("   ", facts_v8, confirmation_binding)

print("B8 relevant path removed:")
facts_v9 = {k: v for k, v in facts_v2.items() if k != "intervention.product_identity"}
show("   ", facts_v9, confirmation_binding)

print("B9 source materials updated (research.input_context):")
facts_v10 = dict(facts_v2)
facts_v10["research.input_context"] = {"source_intake_sha256": "b" * 64}
show("   ", facts_v10, confirmation_binding)
