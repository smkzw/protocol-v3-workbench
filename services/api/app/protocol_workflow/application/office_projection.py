"""Honest, read-only projection of the saved Word working copy.

This module does not create a second editable manuscript.  It extracts the
actual DOCX snapshot with stable XML locators and reports only checks that can
be supported by literal content.  Paraphrased, structured, and numeric-only
matches stay review clues instead of being called consistent.
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

# A number is only a useful clue when it appears in a paragraph whose subject
# is also recognisable.  These tokens never upgrade a clue to ``located``;
# exact fact text is still required for that stronger result.
CRITICAL_FACT_CONTEXT = {
    'framing.investigational_product': ('研究药物', '试验药物', '受试药'),
    'framing.indication': ('适应症', '疾病', '患者'),
    'picos.population_summary': ('人群', '患者', '试验参与者'),
    'picos.intervention_summary': ('干预', '治疗', '给药', '试验药物'),
    'picos.comparator_summary': ('对照', '安慰剂', '阳性药'),
    'picos.primary_endpoint': ('主要终点', '主要疗效', '评价指标'),
    'statistics.sample_size.planned_n': ('样本量', '例', '试验参与者'),
    'framing.structured_design.allocation_ratio': ('分配', '随机', '比例'),
    'statistics.non_inferiority.margin': ('非劣效', '界值', '界限'),
}


def project_office_snapshot(content: bytes, confirmed_facts: Mapping, *,
                            snapshot_sha256: str, study_revision_sha256: str) -> dict:
    parsed = parse_docx(content)
    searchable = [block for block in parsed.blocks
                  if block.role not in {'derived_toc', 'header', 'footer'} and block.text.strip()]
    whole_text = '\n'.join(block.text for block in searchable)
    normalized = _norm_fact_text(whole_text)
    located, semantic_review, uncovered = [], [], []
    for path, label in CRITICAL_FACT_LABELS.items():
        value = confirmed_facts.get(path)
        if value in (None, '', [], {}):
            continue
        if isinstance(value, (dict, list)):
            semantic_review.append({
                'fact_path': path,
                'label': label,
                'reason': '结构化内容需逐项核对，不能由关键词出现推断一致。',
                'locators': [],
            })
            continue
        text = _fact_display_text(value).strip()
        if not text:
            continue
        digits = re.findall(r'\d+(?:\.\d+)?', text)
        exact = [block.locator for block in searchable
                 if _norm_fact_text(text) in _norm_fact_text(block.text)]
        if exact:
            located.append({'fact_path': path, 'label': label, 'locators': exact[:8]})
            continue
        context_tokens = CRITICAL_FACT_CONTEXT.get(path, (label,))
        numeric_clues = [block.locator for block in searchable
                         if digits
                         and any(token in block.text for token in context_tokens)
                         and all(_digit_bounded(block.text, digit) for digit in digits)]
        if numeric_clues:
            semantic_review.append({
                'fact_path': path,
                'label': label,
                'reason': '在相关段落发现相同数字，但数字本身不能证明含义、单位或语境一致。',
                'locators': numeric_clues[:8],
            })
            continue
        if len(_norm_fact_text(text)) >= 4 and _norm_fact_text(text) not in normalized:
            uncovered.append({
                'fact_path': path,
                'label': label,
                'reason': f'未在当前 Word 中直接定位到已确认的{label}表述。',
                'locators': [],
            })
    diagnostics = [{'code': item.code, 'location': item.locator,
                    'message': item.detail} for item in parsed.diagnostics]
    checked = len(located) + len(semantic_review) + len(uncovered)
    status = ('not_checked' if checked == 0 else
              'needs_semantic_review' if semantic_review or uncovered or diagnostics else
              'located_within_checked_scope')
    return {
        'schema_version': 'office-snapshot-reconciliation.v2',
        'snapshot_sha256': snapshot_sha256,
        'study_revision_sha256': study_revision_sha256,
        'parser_version': parsed.parser_version,
        'status': status,
        'located': located,
        'semantic_review': semantic_review,
        'uncovered': uncovered,
        # Read compatibility for older clients.  These aliases do not restore
        # the old claim that a missing numeric occurrence is a contradiction.
        'differences': [],
        'unverified': semantic_review + uncovered,
        'diagnostics': diagnostics,
        'content_block_count': len(searchable),
        'checked_fact_count': checked,
        'coverage_note': '仅报告当前 Word 字节中可确定的直接定位与核对线索；数字巧合、改写表述、图形、域及复杂结构均不自动判为一致。',
    }
