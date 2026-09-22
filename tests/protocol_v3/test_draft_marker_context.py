"""Real shared consumers must distinguish study conduct from drafting work."""
from types import SimpleNamespace

import pytest

from services.api.app.ai_task_runner import AiTaskRunner
from services.api.app.medical_writing_full_draft import FULL_DRAFT_ARTIFACT_SCHEMA
from services.api.app.medical_writing_content_quality import MedicalWritingContentQualityDetector


@pytest.mark.parametrize('text,expected', [
    ('未提供书面知情同意者不进入筛选。', False),
    ('未提供书面知情同意的人员不得参加本研究。', False),
    ('若受试者未提供书面知情同意书，则不进入筛选。', False),
    ('如试验参与者未提供书面知情同意，则不得入组。', False),
    ('若受试者未提供书面知情同意书，则不进入筛选；样本量待医学经理确认后写入。', True),
    ('若受试者未提供书面知情同意书，则待医学经理确认后写入。', True),
    ('数据将在生物统计人员确认后锁定。', False),
    ('数据库由生物统计人员确认后锁定。', False),
    ('样本量待医学经理确认后写入。', True),
    ('主要终点的具体数值未提供。', True),
    ('筛选期时长将在本方案正式文本中规定。', True),
    ('试验参与者待随访期间记录相关信息。', False),
    ('未提供书面知情同意者不进入筛选；样本量待医学经理确认后写入。', True),
    ('数据将在生物统计人员确认后锁定；主要终点尚待医学经理明确。', True),
])
def test_draft_markers_match_actual_writing_instruction_in_both_consumers(text, expected):
    findings = MedicalWritingContentQualityDetector()._scan_text(
        document=SimpleNamespace(project_id='probe', document_id='probe', version='V1'),
        section=SimpleNamespace(section_id='sec', heading='研究设计'),
        block={'block_id': 'b'}, text=text, location_kind='paragraph',
        source_locator='synthetic:b', content_revision=0,
    )
    assert any(f.rule_code == 'unresolved_draft_marker' for f in findings) == expected
    errors = AiTaskRunner._validate_protocol_full_draft_output(None, {
        'full_draft': {'sections': [{'section_id': 'sec', 'proposal_text': text, 'evidence_span_ids': ['e1']}]},
        'evidence_spans': [{'span_id': 'e1'}], 'needs_medical_confirmation': True,
    }, [], {'section_ids': ['sec'], 'minimum_body_chars': 1})
    assert any('unresolved drafting markers' in e for e in errors) == expected


def test_true_draft_marker_after_legitimate_clause_preserves_cell_location():
    text = '未提供书面知情同意者不进入筛选；样本量待医学经理确认后写入。'
    findings = MedicalWritingContentQualityDetector()._scan_text(
        document=SimpleNamespace(project_id='probe', document_id='probe', version='V1'),
        section=SimpleNamespace(section_id='sec', heading='研究设计'),
        block={'block_id': 'table'}, text=text, location_kind='table_cell',
        source_locator='synthetic:table:1:2', content_revision=4,
        table_id='t1', cell_id='c2', row_index=1, cell_index=2,
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.matched_text == '待医学经理确认'
    assert text[finding.match_start:finding.match_end] == finding.matched_text
    assert finding.cell_id == 'c2' and finding.source_locator == 'synthetic:table:1:2'
    assert finding.content_revision == 4


def test_current_adoption_accepts_conduct_clauses_without_bypassing_body_checks():
    """Actual adoption method with fake repository; no product model invoked."""
    from unittest.mock import patch
    from test_medical_writing_full_draft import FullDraftServiceTests

    harness = FullDraftServiceTests()
    harness.setUp()
    try:
        text = ('未提供书面知情同意者不进入筛选。数据将在生物统计人员确认后锁定。'
                '研究者应记录每次访视的实际日期以及检查结果。'
                '所有检查结果按方案规定的方法评估，并记录与研究相关的临床观察。'
                '如有方案偏离，应说明具体情况及原因，保留相关原始记录。')
        with patch(
            'services.api.app.medical_writing_full_draft.company_template_semantic_node_map',
            return_value={
                'cms_background': 'semantic:test:research-background',
                'cms_objectives_endpoints': 'semantic:test:objectives-endpoints',
            },
        ):
            completed, artifact = harness._completed_artifact()
        assert artifact['schema_version'] == FULL_DRAFT_ARTIFACT_SCHEMA
        artifact['sections'][0]['proposal_text'] = text
        with patch.object(harness.full, 'read_artifact', return_value=artifact):
            result = harness.full.adopt(harness.repo.project_id, completed)
        assert 'sec_1' in result['adopted_section_ids']
        assert harness.repo.working['sec_1'].content_blocks[1]['text'] == text
    finally:
        harness.tearDown()
