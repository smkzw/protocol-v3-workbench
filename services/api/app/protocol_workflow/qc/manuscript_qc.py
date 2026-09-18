"""Run the R03 quality checks over a saved working manuscript.

Deliberately scoped to what the typed document projection can actually
support today: version identity consistency, internal citation resolution
and signature-control status.  Findings are attached to the save/edit
receipt as advisory QC results; they never block a working draft, never
claim medical adequacy, and never pass merely because the document exists.
"""
from dataclasses import dataclass, field as data_field
from typing import Any, Mapping

from app.protocol_workflow.qc.r03 import (
    R03Citation,
    R03CitationMaterial,
    R03CitationTarget,
    R03VersionMaterial,
    R03VersionPoint,
    check_internal_citations,
    check_version_consistency,
    signature_control_status,
)


@dataclass
class _Citations:
    citations: list = data_field(default_factory=list)
    targets: list = data_field(default_factory=list)


def _collect_document_text(document: Mapping[str, Any]) -> tuple[str, list[dict], dict[str, str]]:
    """Concatenate paragraph/table text, collect targets, and map markers→ids."""
    parts: list[str] = []
    targets: list[dict] = []
    marker_map: dict[str, str] = {}
    for block in document.get('semantic_blocks', []):
        kind = block.get('block_kind')
        content = block.get('content') or ''
        if kind == 'paragraph':
            parts.append(content)
        elif kind == 'table':
            import json
            try:
                value = json.loads(content)
            except (TypeError, ValueError):
                continue
            table = value.get('table') if isinstance(value, dict) else None
            if not isinstance(table, Mapping):
                continue
            for row in table.get('rows', []):
                for cell in row.get('cells', []):
                    parts.append(cell.get('text') if isinstance(cell, Mapping) else str(cell))
            for note in table.get('notes', []):
                if isinstance(note, Mapping) and note.get('note_id'):
                    note_id = str(note['note_id'])
                    targets.append({'target_id': note_id, 'kind': 'table_note',
                                    'description': note.get('text', '')})
                    marker_map[note.get('marker') or note_id] = note_id
    return '\n'.join(parts), targets, marker_map


def _version_material(document: Mapping[str, Any]) -> R03VersionMaterial | None:
    """Version four-point identity from block-level table cells, when projected."""
    version_rows = document.get('version_identity') if isinstance(document.get('version_identity'), Mapping) else None
    if not version_rows:
        return None
    def _point(source, name):
        return R03VersionPoint(
            title=source.get('title', ''), protocol_number=source.get('protocol_number', ''),
            version_number=source.get('version_number', ''), version_date=source.get('version_date', ''))
    locations = {name: _point(value, name) for name, value in version_rows.items()
                 if name != 'current' and isinstance(value, Mapping)}
    return R03VersionMaterial(current=_point(version_rows.get('current', {}), 'current'),
                              current_locations=locations)


def run_manuscript_qc(document: Mapping[str, Any]) -> dict:
    """Advisory QC summary bound to a working-draft receipt."""
    text, note_targets, marker_to_id = _collect_document_text(document)
    version_result = check_version_consistency(_version_material(document))
    citation_targets = [R03CitationTarget.model_validate(target) for target in note_targets]
    # The projection always runs over a saved document: an empty citation
    # scope on a real document is a legitimately completed zero-citation
    # projection, never an absent one.  In-text markers map through each
    # note's display marker to its registered id; an unresolvable marker
    # stays a citation entry so the checker reports it as dangling.
    import re
    markers = set(marker_to_id.values())
    markers.update(re.findall(r'注[0-9a-zA-Z]{1,4}', text))
    citations = [R03Citation(text=marker, target_id=marker_to_id.get(marker, marker))
                 for marker in sorted(markers)]
    material = R03CitationMaterial(projection_completed=True, citations=tuple(citations),
                                   targets=tuple(citation_targets))
    citation_result = check_internal_citations(material)
    signature = signature_control_status(text)
    findings = []
    for check_name, result in (('version_consistency', version_result), ('internal_citations', citation_result)):
        for finding in (result.findings or []):
            findings.append({'check': check_name, 'code': finding.code,
                             'location': finding.location, 'message': finding.message})
    passed = not findings
    return {'scope': 'working_draft_advisory', 'passed': passed, 'findings': findings,
            'signature_control': signature,
            'not_covered': ['医学一致性', '统计复算', '文献准确性', 'Word渲染']}


def _finding(code, location, message):  # pragma: no cover - shape mirror helper
    return {'code': code, 'location': location, 'message': message}
