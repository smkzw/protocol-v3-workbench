"""Honest, read-only projection of the saved Word working copy.

This module does not create a second editable manuscript.  It extracts the
actual DOCX snapshot with stable XML locators and reports only checks that can
be supported by literal content.  Paraphrased or structured facts stay
unverified instead of being called consistent.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.application.manuscript_edits import (
    _digit_bounded, _fact_display_text, _norm_fact_text,
)


CRITICAL_FACT_LABELS = {
    'framing.investigational_product': '研究药物',
    'framing.indication': '适应症',
    'picos.population_summary': '目标人群',
    'picos.intervention_summary': '干预措施',
    'picos.comparator_summary': '对照',
    'picos.primary_endpoint': '主要终点',
    'statistics.sample_size.planned_n': '计划样本量',
    'framing.structured_design.allocation_ratio': '分配比例',
    'statistics.non_inferiority.margin': '非劣效界值',
}


def project_office_snapshot(content: bytes, confirmed_facts: Mapping, *,
                            snapshot_sha256: str, study_revision_sha256: str) -> dict:
    parsed = parse_docx(content)
    searchable = [block for block in parsed.blocks
                  if block.role not in {'derived_toc', 'header', 'footer'} and block.text.strip()]
    whole_text = '\n'.join(block.text for block in searchable)
    normalized = _norm_fact_text(whole_text)
    located, differences, unverified = [], [], []
    for path, label in CRITICAL_FACT_LABELS.items():
        value = confirmed_facts.get(path)
        if value in (None, '', [], {}):
            continue
        if isinstance(value, (dict, list)):
            unverified.append({'label': label, 'reason': '结构化内容需逐项语义核对'})
            continue
        text = _fact_display_text(value).strip()
        if not text:
            continue
        digits = re.findall(r'\d+(?:\.\d+)?', text)
        matching = [block.locator for block in searchable
                    if (_norm_fact_text(text) in _norm_fact_text(block.text)
                        or (digits and all(_digit_bounded(block.text, digit) for digit in digits)))]
        if matching:
            located.append({'label': label, 'locators': matching[:8]})
        elif digits:
            differences.append({'label': label,
                'message': f'未在当前 Word 中定位到已确认的{label}数值。'})
        elif len(_norm_fact_text(text)) >= 4 and _norm_fact_text(text) not in normalized:
            unverified.append({'label': label, 'reason': '可能使用了改写表述，需人工核对'})
    diagnostics = [{'code': item.code, 'location': item.locator,
                    'message': item.detail} for item in parsed.diagnostics]
    status = 'differences' if differences else (
        'checked_with_unverified_items' if unverified or diagnostics else 'consistent_within_checked_scope')
    return {
        'schema_version': 'office-snapshot-reconciliation.v1',
        'snapshot_sha256': snapshot_sha256,
        'study_revision_sha256': study_revision_sha256,
        'parser_version': parsed.parser_version,
        'status': status,
        'located': located,
        'differences': differences,
        'unverified': unverified,
        'diagnostics': diagnostics,
        'content_block_count': len(searchable),
        'checked_fact_count': len(located) + len(differences) + len(unverified),
        'coverage_note': '仅核对可从当前 Word 字节确定定位的关键事实；改写表述、图形、域及复杂结构仍需人工核对。',
    }
