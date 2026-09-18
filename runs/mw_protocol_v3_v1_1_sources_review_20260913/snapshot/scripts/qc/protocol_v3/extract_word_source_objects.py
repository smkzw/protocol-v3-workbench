"""Source-bound Word object inventory. Does not run Word or certify rendering."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from pocs.protocol_v3.word_receipt.producers.base import inspect_docx_ooxml
from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
TOKEN = r'(?:"([^\"]+)"|(\S+))'


def reference_target(instruction: str) -> tuple[str, str | None]:
    """Keep external documents with a local fragment distinct from internal refs."""
    match = re.match(r'^\s*(REF|PAGEREF)\s+' + TOKEN, instruction, re.I)
    if match:
        return 'internal', match.group(2) or match.group(3)
    if not re.match(r'^\s*HYPERLINK\b', instruction, re.I):
        return 'field', None
    fragment = re.search(r'\\l\s+' + TOKEN, instruction, re.I)
    # A positional address (including a quoted Windows/file path) points to
    # another document even when Word also supplies a \\l bookmark fragment.
    address = re.match(r'^\s*HYPERLINK\s+' + TOKEN, instruction, re.I)
    value = (address.group(1) or address.group(2)) if address else None
    external = bool(value and not value.startswith('\\'))
    target = (fragment.group(1) or fragment.group(2)) if fragment else None
    return ('external_document_anchor' if target else 'external') if external else 'internal', target


def map_objects(inspection: dict, ownership: dict, contracts: list[dict], styles: set[str]) -> dict:
    """Map every observed object; never filter missing reference targets."""
    bookmarks = []
    by_name: dict[str, list[dict]] = {}
    for item in inspection['bookmarks']:
        record = {
            'source_id': f"{item['part']}#bookmark:{item['bookmark_id']}",
            'name': item['name'], 'part': item['part'],
            'kind': 'derived_toc' if item['name'].startswith('_Toc') else 'source_bookmark',
            'owner_node_id': ownership.get((item['part'], item['bookmark_id'])),
            'target_sha256': item['target_sha256'],
        }
        bookmarks.append(record)
        by_name.setdefault(item['name'], []).append(record)
    fields = []
    findings = []
    for index, item in enumerate(inspection['fields']):
        kind, target = reference_target(item['instruction'])
        record = {
            'source_id': f"{item['part']}#field:{index}", 'part': item['part'],
            'kind': kind, 'field_type': item['instruction'].split(' ', 1)[0].upper(),
            'instruction_sha256': hashlib.sha256(item['instruction'].encode()).hexdigest(),
            'result_sha256': hashlib.sha256(item['result'].encode()).hexdigest(),
            'target_name': target,
        }
        if kind == 'internal':
            matches = by_name.get(target, []) if target else []
            record['resolution'] = 'resolved' if len(matches) == 1 else 'missing' if not matches else 'ambiguous'
            record['target_source_ids'] = [x['source_id'] for x in matches]
            record['target_node_ids'] = sorted({x['owner_node_id'] for x in matches if x['owner_node_id']})
            if record['resolution'] != 'resolved':
                findings.append({'code': 'source_reference_' + record['resolution'], 'location': record['source_id']})
        elif kind.startswith('external'):
            record['resolution'] = 'external_not_verified'
        fields.append(record)
    requirements = []
    for contract in contracts:
        rules = contract['word_rules']
        record = {'node_id': contract['semantic_node_id'], 'styles': [], 'bookmarks': [],
                  'textual_reference_declarations': list(rules['required_cross_references'])}
        for style in rules['required_styles']:
            record['styles'].append({'style_id': style, 'exists': style in styles})
            if style not in styles:
                findings.append({'code': 'required_style_missing', 'location': record['node_id'], 'target': style})
        for name in rules['required_bookmarks']:
            record['bookmarks'].append({'name': name, 'exists': name in by_name,
                                        'source_ids': [x['source_id'] for x in by_name.get(name, [])]})
            if name not in by_name:
                findings.append({'code': 'required_bookmark_missing', 'location': record['node_id'], 'target': name})
        requirements.append(record)
    return {'bookmarks': bookmarks, 'fields': fields, 'contract_requirements': requirements, 'findings': findings}


def build_inventory(source: Path, template_root: Path) -> dict:
    template = json.loads((template_root / 'template.json').read_text())
    tree = json.loads((template_root / 'node_tree.json').read_text())
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    if actual != template['source']['sha256'] or actual != tree['source']['sha256']:
        raise ValueError('source hash differs from current template/node tree')
    nodes = tree['outlined_tree']['nodes']
    by_index = {x['body_child_index']: x['id'] for x in nodes}
    ownership = {}
    with ZipFile(source) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
        owner = 'v2_front_block'
        for index, element in enumerate(root.find(W + 'body')):
            owner = by_index.get(index, owner)
            for bookmark in element.iter(W + 'bookmarkStart'):
                ownership[('word/document.xml', bookmark.get(W + 'id'))] = owner
        styles = {s.get(W + 'styleId') for s in ET.fromstring(archive.read('word/styles.xml')).iter(W + 'style')}
    contracts = [ChapterContractV2.model_validate_json(p.read_text()).model_dump(mode='json')
                 for p in sorted((template_root / 'chapter_contracts').glob('*.json'))]
    inspection = inspect_docx_ooxml(source)
    result = map_objects(inspection, ownership, contracts, styles)
    # The shared inspector returns completed objects. Preserve XML remnants
    # as observations instead of silently treating its inventory as XML QA.
    observations = []
    with ZipFile(source) as archive:
        for part in inspection['story_parts']:
            xml = ET.fromstring(archive.read(part))
            starts = [x.get(W + 'id') for x in xml.iter(W + 'bookmarkStart')]
            ends = [x.get(W + 'id') for x in xml.iter(W + 'bookmarkEnd')]
            observed = sum(x['part'] == part for x in inspection['bookmarks'])
            if observed != len(starts):
                raise ValueError(f'bookmark inventory incomplete in {part}')
            orphan_ends = [x for x in ends if x not in set(starts)]
            if orphan_ends or len(ends) != len(starts):
                observations.append({'code': 'source_bookmark_end_remnants', 'part': part,
                                     'start_count': len(starts), 'end_count': len(ends),
                                     'orphan_end_ids': orphan_ends,
                                     'scope': 'source_observation_not_generated_document_acceptance'})
    result['source_xml_observations'] = observations
    result.update(schema_version='protocol-word-source-objects.v1', template_id=template['template_id'],
                  source_sha256=actual, scope='source_mapping_only_not_native_word_or_generated_document_acceptance',
                  native_word_invoked=False, story_parts=inspection['story_parts'],
                  counts={'bookmarks': len(result['bookmarks']), 'fields': len(result['fields']), 'contracts': len(contracts)})
    result['table_sources'] = [
        {'source_id': f"word/document.xml#body:{t['body_child_index']}",
         'owner_node_id': t['owner_node_id'], 'rows': t['row_count'], 'columns': t['column_count']}
        for t in tree['tables']
    ]
    result['source_inputs'] = {
        str(p.relative_to(template_root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [template_root/'template.json', template_root/'node_tree.json', *sorted((template_root/'chapter_contracts').glob('*.json'))]
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--template-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build_inventory(args.source, args.template_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n')


if __name__ == '__main__':
    main()
