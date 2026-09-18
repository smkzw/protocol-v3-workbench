"""Role views preserve all administrations without guessing roles from names."""
import pytest
from test_clinical_design_worker import prepared_reference
from app.protocol_workflow.agent2.clinical_worker import read_regimen_response


def material():
    prepared,output=prepared_reference()
    return read_regimen_response(prepared,output)['regimen']


def test_role_views_require_explicit_assignments_and_keep_period_arm_and_native_dose():
    from app.protocol_workflow.agent2.regimen_projection import project_regimen_roles
    regimen=material()
    with pytest.raises(ValueError,match='regimen_product_role_unresolved'):
        project_regimen_roles(regimen,{})
    roles={f'{i}/{j}/{k}':'investigational' for i,s in enumerate(regimen['schedules'])
           for j,step in enumerate(s['steps']) for k,_ in enumerate(step['products'])}
    result=project_regimen_roles(regimen,roles)
    assert len(result['investigational'])==8
    assert result['comparator']==[]
    assert result['investigational'][0]['dose']=={'value':200,'unit':'mg'}
    assert type(result['investigational'][0]['dose']['value']) is int
    assert len({(entry['period_id'],entry['arm_id']) for entry in result['investigational']})==4


def test_role_assignments_do_not_merge_switching_arms_or_relabel_by_drug_name():
    from app.protocol_workflow.agent2.regimen_projection import project_regimen_roles
    regimen=material()
    roles={f'{i}/{j}/{k}':('comparator' if i==0 else 'investigational') for i,s in enumerate(regimen['schedules'])
           for j,step in enumerate(s['steps']) for k,_ in enumerate(step['products'])}
    result=project_regimen_roles(regimen,roles)
    assert len(result['comparator'])==2
    assert all(row['name']=='试验药X' for row in result['comparator'])
    assert len(result['investigational'])==6
    with pytest.raises(ValueError,match='regimen_product_role_target_unknown'):
        project_regimen_roles(regimen,{**roles,'999/0/0':'comparator'})


def test_saved_role_assignments_are_rejected_after_regimen_reordering():
    from copy import deepcopy
    from app.protocol_workflow.canonical.hashing import exact_payload_sha256
    from app.protocol_workflow.agent2.regimen_projection import project_bound_regimen_roles
    regimen=material()
    roles={f'{i}/{j}/{k}':'investigational' for i,s in enumerate(regimen['schedules'])
           for j,step in enumerate(s['steps']) for k,_ in enumerate(step['products'])}
    binding={'regimen_sha256':exact_payload_sha256(regimen),'assignments':roles}
    assert len(project_bound_regimen_roles(regimen,binding)['investigational'])==8
    changed=deepcopy(regimen)
    changed['schedules'][0]['steps'].reverse()
    with pytest.raises(ValueError,match='regimen_role_binding_changed'):
        project_bound_regimen_roles(changed,binding)
