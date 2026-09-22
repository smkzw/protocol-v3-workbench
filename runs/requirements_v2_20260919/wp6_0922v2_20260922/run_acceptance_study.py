#!/usr/bin/env python3
"""Create one isolated acceptance study and start its single durable v0.10 job."""
from __future__ import annotations
import argparse, json, pathlib, urllib.error, urllib.request


def call(base: str, method: str, path: str, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', 'replace')
        raise RuntimeError(f'{method} {path} -> HTTP {exc.code}: {body}') from exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--study', choices=('study_b', 'study_c'), required=True)
    parser.add_argument('--base', default='http://127.0.0.1:5304')
    parser.add_argument('--spec', default=str(pathlib.Path(__file__).with_name('study_bc_acceptance_specs.json')))
    args = parser.parse_args()
    spec = json.loads(pathlib.Path(args.spec).read_text(encoding='utf-8'))[args.study]
    evidence = pathlib.Path(__file__).with_name(args.study + '_journey')
    evidence.mkdir(exist_ok=True)
    project_result = call(args.base, 'POST', '/api/projects', spec['project'])
    project_id = project_result['project']['project_id']
    journey = project_result['authoring_journey']
    (evidence/'01_project.json').write_text(json.dumps(project_result, ensure_ascii=False, indent=2)+'\n')

    for number, (stage, payload) in enumerate((('framing', spec['framing']), ('picos', spec['picos'])), start=2):
        preview = call(args.base, 'POST', f'/api/projects/{project_id}/medical-writing/authoring-journey/impact-preview', {
            'expected_revision': journey['revision'], 'stage': stage, stage: payload,
        })
        commit = call(args.base, 'POST', f'/api/projects/{project_id}/medical-writing/authoring-journey/stages/{stage}/commit', {
            'expected_revision': journey['revision'], 'stage': stage, stage: payload,
            'impact_preview_id': preview['preview_id'], 'actor': 'wp6_product_acceptance',
            'idempotency_key': f'wp6-{args.study}-{stage}-commit-20260922',
        })
        (evidence/f'{number:02d}_{stage}_preview.json').write_text(json.dumps(preview, ensure_ascii=False, indent=2)+'\n')
        (evidence/f'{number:02d}_{stage}_commit.json').write_text(json.dumps(commit, ensure_ascii=False, indent=2)+'\n')
        journey = commit

    missing = list(journey.get('corpus_gate', {}).get('missing_requirements') or [])
    if missing and not journey.get('corpus_gate', {}).get('access_permitted'):
        journey = call(args.base, 'POST', f'/api/projects/{project_id}/medical-writing/authoring-journey/corpus-gate/override', {
            'expected_revision': journey['revision'],
            'reason': '隔离产品验收研究：已确认设计事实可生成带明确来源缺口的工作稿。',
            'acknowledged_missing_requirements': missing,
            'actor': 'wp6_product_acceptance',
            'idempotency_key': f'wp6-{args.study}-corpus-override-20260922',
        })
        (evidence/'04_corpus_override.json').write_text(json.dumps(journey, ensure_ascii=False, indent=2)+'\n')

    definition = journey['study_definition']
    assembly = call(args.base, 'POST', f'/api/projects/{project_id}/medical-writing/protocol-assembly-plan/refresh', {
        'expected_plan_revision': 0,
        'expected_source_definition_id': definition['definition_id'],
        'expected_source_definition_revision': definition['revision'],
        'expected_source_definition_sha256': definition['state_sha256'],
        'actor': 'wp6_product_acceptance',
        'idempotency_key': f'wp6-{args.study}-assembly-refresh-20260922',
    })
    (evidence/'05_assembly_refresh.json').write_text(json.dumps(assembly, ensure_ascii=False, indent=2)+'\n')
    plan = assembly['plan']
    confirmed = call(args.base, 'POST', f'/api/projects/{project_id}/medical-writing/protocol-assembly-plan/confirm', {
        'expected_plan_revision': plan['revision'],
        'expected_plan_sha256': plan['state_sha256'],
        'actor': 'wp6_product_acceptance',
        'idempotency_key': f'wp6-{args.study}-assembly-confirm-20260922',
    })
    (evidence/'06_assembly_confirm.json').write_text(json.dumps(confirmed, ensure_ascii=False, indent=2)+'\n')
    document = call(args.base, 'POST', f'/api/projects/{project_id}/medical-writing/greenfield-document', {
        'protocol_id': spec['framing']['protocol_id'], 'version': spec['framing']['version'],
        'document_title': spec['framing']['document_title'], 'indication': spec['framing']['indication'],
        'study_phase': spec['framing']['study_phase'], 'investigational_product': spec['framing']['investigational_product'],
        'source_study_definition_id': definition['definition_id'],
        'source_study_definition_revision': definition['revision'],
        'source_study_definition_sha256': definition['state_sha256'],
        'template_id': 'cms_protocol_zh_cn',
        'template_version': 'cms_protocol_zh_cn_company_authority_2026_07_19_v2',
        'actor': 'wp6_product_acceptance',
        'idempotency_key': f'wp6-{args.study}-greenfield-20260922',
    })
    (evidence/'07_greenfield.json').write_text(json.dumps(document, ensure_ascii=False, indent=2)+'\n')
    start = call(args.base, 'POST', f'/api/projects/{project_id}/medical-writing/full-drafts', {
        'actor': 'wp6_product_acceptance',
    })
    result = {'study': args.study, 'project_id': project_id, **start}
    (evidence/'08_full_draft_start.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
