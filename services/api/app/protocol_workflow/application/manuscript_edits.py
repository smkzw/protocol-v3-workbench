"""Controlled manuscript edits: server-side EditClass reclassification.

The client's claimed edit class is never trusted. Before a block edit is
applied, the server re-derives the classification from the confirmed facts:
if the replaced text carried a confirmed fact value that the new text no
longer carries (or introduces a conflicting value for), the edit is
FACT_OR_UNCERTAIN — it cannot be applied as wording; it returns a fact
proposal for the StudyDefinition confirmation path instead. Local working
drafts (PROPOSED) may take wording edits directly through the same CAS
discipline as the original save.
"""
import hashlib
from typing import Any, Mapping

from app.protocol_workflow.canonical.hashing import canonical_json


def _text_of(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return canonical_json(value)


def _scalar_texts(value: Any) -> list[str]:
    """Leaf scalars of a fact value, plus number+unit pairings in both spacings.

    A structured fact (e.g. a compound regimen object) must be searchable by
    its leaf values — matching its raw JSON serialization would never find
    "100 mg" in prose and would let dose changes pass as wording.
    """
    if value is None or isinstance(value, (bool,)):
        return []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, str):
        return [value] if value.strip() else []
    texts: list[str] = []
    if isinstance(value, Mapping):
        scalars = []
        for child in value.values():
            child_texts = _scalar_texts(child)
            texts.extend(child_texts)
            if child_texts:
                scalars.append(child_texts)
        # Pair adjacent number+unit leaves ("100", "mg") in common spacings so
        # prose forms of the same value are detected; extra pairings only
        # widen detection, they cannot silence it.
        for group in scalars:
            if len(group) >= 2:
                for a, b in zip(group, group[1:]):
                    texts.append(f'{a}{b}')
                    texts.append(f'{a} {b}')
        return texts
    if isinstance(value, list):
        for child in value:
            texts.extend(_scalar_texts(child))
        return texts
    return []


def _fact_value_strings(facts: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Flatten confirmed facts to (fact_path, searchable string) pairs."""
    flattened = []
    for path, value in facts.items():
        for text in _scalar_texts(value):
            flattened.append((path, text))
    return flattened


def reclassify_edit(*, old_text: str, new_text: str, confirmed_facts: Mapping[str, Any],
                    claimed_class: str | None = None) -> dict:
    """Re-derive the edit class from content and confirmed facts.

    Returns ``{'edit_class', 'affected_fact_paths', 'reason'}``.  Anything not
    provably wording/format is FACT_OR_UNCERTAIN — the safe default (design
    §14).  A fact "touch" means a confirmed fact value string present in the
    old text disappeared from the new text, or a different confirmed value of
    the same fact appeared; pure additions of new text are uncertain by
    default, never silently accepted as wording.
    """
    if claimed_class not in (None, 'wording_only', 'format_only',
                             'structure_or_word_object', 'fact_or_uncertain'):
        raise ValueError('manuscript_edit_class_invalid')
    affected = []
    old_norm, new_norm = old_text or '', new_text or ''
    for path, value_text in _fact_value_strings(confirmed_facts):
        if value_text in old_norm and value_text not in new_norm:
            affected.append(path)
    if affected:
        return {'edit_class': 'fact_or_uncertain', 'affected_fact_paths': tuple(sorted(set(affected))),
                'reason': '编辑改变了已确认研究事实的表述，需要通过研究事实确认流程处理。'}
    if new_norm.strip() == old_norm.strip():
        return {'edit_class': 'format_only', 'affected_fact_paths': (),
                'reason': '内容未变化。'}
    return {'edit_class': 'wording_only' if claimed_class == 'wording_only' else 'fact_or_uncertain',
            'affected_fact_paths': (),
            'reason': '' if claimed_class == 'wording_only'
            else '无法证明该编辑不触及研究事实；按事实相关处理。'}


def block_content_text(block: Mapping[str, Any]) -> str:
    kind = block.get('block_kind')
    if kind == 'paragraph':
        return _text_of(block.get('content'))
    if kind == 'table':
        import json
        try:
            value = json.loads(block.get('content') or '{}')
        except (TypeError, ValueError):
            return ''
        table = value.get('table') if isinstance(value, dict) else None
        if isinstance(table, Mapping):
            cells = []
            for row in table.get('rows', []):
                for cell in row.get('cells', []):
                    cells.append(_text_of(cell.get('value') if isinstance(cell, Mapping) else cell))
            return ' '.join(cells)
    return _text_of(block.get('content'))


def edit_intent_sha256(project_id: str, document_id: str, *, operation_id: str,
                       expected_revision: int, edits: list[dict]) -> str:
    return hashlib.sha256(canonical_json([project_id, document_id, operation_id,
        expected_revision, edits]).encode()).hexdigest()
