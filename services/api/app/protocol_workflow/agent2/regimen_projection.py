"""Lossless per-administration views from an explicitly classified regimen.

The caller must bind role assignments to this exact regimen version. This pure
view neither assigns roles nor confirms them, computes protocol dose limits, or
alters canonical facts. Empty role lists are not declarations of inapplicability.
"""
from copy import deepcopy
from app.protocol_workflow.canonical.hashing import exact_payload_sha256


def project_bound_regimen_roles(regimen, binding):
    """Read a stored role mapping only against its original compound value."""
    if binding.get('regimen_sha256') != exact_payload_sha256(regimen):
        raise ValueError('regimen_role_binding_changed')
    return project_regimen_roles(regimen, binding['assignments'])


def project_regimen_roles(regimen, role_assignments):
    roles = ('investigational', 'comparator', 'background')
    result = {role: [] for role in roles}
    targets = set()
    for schedule_index, schedule in enumerate(regimen['schedules']):
        for step_index, step in enumerate(schedule['steps']):
            for product_index, product in enumerate(step['products']):
                target = f'{schedule_index}/{step_index}/{product_index}'
                targets.add(target)
                role = role_assignments.get(target)
                if role not in roles:
                    raise ValueError('regimen_product_role_unresolved')
                result[role].append({
                    'target': target, 'period_id': schedule['period_id'], 'arm_id': schedule['arm_id'],
                    'kind': step['kind'], 'timing': step['timing'], 'frequency': step['frequency'],
                    'route': step['route'], 'name': product['name'], 'dose': deepcopy(product['dose']),
                    'volume': deepcopy(product.get('volume')), 'references': deepcopy(step['references']),
                })
    if set(role_assignments) - targets:
        raise ValueError('regimen_product_role_target_unknown')
    return result
