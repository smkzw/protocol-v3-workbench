"""Validate an already-persisted response without repeating its model call."""
import json
from pydantic import ValidationError
from .research_seed import PreparedSeedRequest, read_seed_candidates


def validate_seed_response(request: PreparedSeedRequest, record: dict, *, artifact_ref: str) -> dict:
    receipt = record['receipt']
    if request.input_sha256 not in {item['sha256'] for item in receipt['input_artifacts']}:
        raise ValueError('seed_response_input_mismatch')
    raw = {**receipt, 'artifact_ref': artifact_ref}
    errors = []
    try:
        output = json.loads(record['content'])
        if not isinstance(output, dict):
            raise ValueError('seed_output_object_required')
        proposal = read_seed_candidates(request, output)
    except json.JSONDecodeError as exc:
        errors = [{'code': 'seed_invalid_json', 'location': f'line:{exc.lineno}:column:{exc.colno}'}]
    except ValidationError as exc:
        errors = [{'code': 'seed_output_schema_invalid',
                   'location': '.'.join(str(part) for part in error['loc']),
                   'issue': error['type']} for error in exc.errors(include_input=False)]
    except ValueError as exc:
        code = str(exc)
        errors = [{'code': code if code.startswith('seed_') else 'seed_output_schema_invalid'}]
    else:
        return {'valid': True, 'status': proposal['status'], 'proposal': proposal,
                'errors': [], 'raw_response': raw}
    return {'valid': False, 'status': 'needs_structure_correction', 'proposal': None,
            'errors': errors, 'raw_response': raw}
