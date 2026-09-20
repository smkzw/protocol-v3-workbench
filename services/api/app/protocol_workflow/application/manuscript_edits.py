"""Manuscript edit classification: explainable reconciliation clues (R3/B03).

The client's claimed edit class is never trusted, but since requirements-v2
the classifier no longer gates saving — every edit persists and the ruling
travels with it as a reconciliation clue for the explicit snapshot check.
Signals stay deterministic and explainable: confirmed-fact value presence
with digit boundaries, and negation flips; they can never prove full
semantic equivalence, which the reconciliation stage supplements.
"""
import hashlib
import re
from typing import Any, Mapping

from app.protocol_workflow.canonical.hashing import canonical_json

_NEGATORS = ('不', '非', '无', '未')


def _digit_bounded(text: str, needle: str) -> bool:
    """A number fact counts as present only at digit boundaries (B03).

    '100' remains present in '100mg' but not in '1000mg', so a 100→1000 dose
    change is detected instead of hidden by substring containment.
    """
    if not needle:
        return False
    if needle.isdigit():
        return re.search(rf'(?<![0-9.]){re.escape(needle)}(?![0-9])', text) is not None
    return needle in text


def _negated(text: str, needle: str) -> bool:
    """True when every occurrence of *needle* sits behind a negator."""
    at = text.find(needle)
    while at >= 0:
        prefix = text[max(0, at - 2):at]
        if not any(negator in prefix for negator in _NEGATORS):
            return False
        at = text.find(needle, at + 1)
    return needle in text


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
    """Re-derive the edit class from content and confirmed facts (clue only).

    Returns ``{'edit_class', 'affected_fact_paths', 'reason'}``.  Since R3 the
    result never blocks saving; it marks whether the explicit reconciliation
    stage should compare this snapshot against the confirmed design.  Signals:
    a confirmed fact value that disappears with digit boundaries, or whose
    negation flips (随机→不随机), marks the edit fact_or_uncertain.  These
    signals cannot prove full semantic equivalence — pure additions stay
    wording when claimed, flagged for the semantic check.
    """
    if claimed_class not in (None, 'wording_only', 'format_only',
                             'structure_or_word_object', 'fact_or_uncertain'):
        raise ValueError('manuscript_edit_class_invalid')
    affected = []
    negation_flips = []
    signals = []
    old_norm, new_norm = old_text or '', new_text or ''
    for path, value_text in _fact_value_strings(confirmed_facts):
        if not value_text:
            continue
        in_old, in_new = _digit_bounded(old_norm, value_text), _digit_bounded(new_norm, value_text)
        if in_old and not in_new:
            affected.append(path)
            signals.append({'fact_path': path, 'value_text': value_text,
                            'present_in_old': True, 'negated_in_old': _negated(old_norm, value_text)})
        elif in_old and in_new and _negated(old_norm, value_text) != _negated(new_norm, value_text):
            negation_flips.append(path)
            signals.append({'fact_path': path, 'value_text': value_text,
                            'present_in_old': True, 'negated_in_old': _negated(old_norm, value_text)})
    if affected:
        return {'edit_class': 'fact_or_uncertain', 'affected_fact_paths': tuple(sorted(set(affected))),
                'signals': signals,
                'reason': '编辑改变了已确认研究事实的表述，显式核对时需与已确认设计比对。'}
    if negation_flips:
        return {'edit_class': 'fact_or_uncertain', 'affected_fact_paths': tuple(sorted(set(negation_flips))),
                'signals': signals,
                'reason': '编辑改变了事实表述的否定形式（如随机→不随机），显式核对时需比对。'}
    if new_norm.strip() == old_norm.strip():
        return {'edit_class': 'format_only', 'affected_fact_paths': (), 'signals': [],
                'reason': '内容未变化。'}
    return {'edit_class': 'wording_only' if claimed_class == 'wording_only' else 'fact_or_uncertain',
            'affected_fact_paths': (), 'signals': [],
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
        if not isinstance(table, Mapping):
            # Unknown table shape: fall back to the raw payload so fact
            # strings stay detectable instead of silently reading empty (B02).
            return _text_of(block.get('content'))
        cells = []
        for row in table.get('rows', []):
            for cell in row.get('cells', []):
                if isinstance(cell, Mapping):
                    # Current schema stores text; historical drafts may carry
                    # value. Read whichever exists — never force one shape.
                    cells.append(_text_of(cell.get('text', cell.get('value'))))
                else:
                    cells.append(_text_of(cell))
        for note in table.get('notes', []) or []:
            if isinstance(note, Mapping):
                cells.append(_text_of(note.get('text', note.get('value'))))
        return ' '.join(cells)
    return _text_of(block.get('content'))


def edit_intent_sha256(project_id: str, document_id: str, *, operation_id: str,
                       expected_revision: int, edits: list[dict]) -> str:
    return hashlib.sha256(canonical_json([project_id, document_id, operation_id,
        expected_revision, edits]).encode()).hexdigest()


def _fact_display_text(value) -> str:
    """Flatten a confirmed-fact value (str | number | list | dict) to text."""
    if value is None:
        return ''
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return '；'.join(filter(None, (_fact_display_text(item) for item in value)))
    if isinstance(value, Mapping):
        return '；'.join(filter(None, (_fact_display_text(item) for item in value.values())))
    return str(value)


def _norm_fact_text(text: str) -> str:
    """Whitespace/punctuation-insensitive comparison key for fact drift."""
    return ''.join(char for char in (text or '').strip() if char.isalnum())
