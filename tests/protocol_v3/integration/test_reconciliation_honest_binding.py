"""Honest reconciliation binding (audit G2/F06).

The reconciliation view must read the *current* confirmed facts, must never
call an unchecked document consistent, and must reopen acknowledged
differences when the study version changes underneath them.
"""
import pytest

from test_manuscript_edit_control import seed_working_document
from test_mounted_api_integration import PROJECT, SD_ID


def _edit(service, operation, block_id, new_text, claimed='wording_only'):
    current = service.current(PROJECT, SD_ID)
    return service.edit(PROJECT, SD_ID,
        {'intervention.dose_regimen': '计划入组100例，给药剂量为100mg，每21天为一个治疗周期。',
         'framing.structured_design': '随机双盲'}, intent={
        'operation_id': operation, 'actor_id': 'user:example',
        'expected_revision': current['expected_revision'],
        'expected_document_sha256': current['expected_document_sha256'],
        'edits': [{'semantic_block_id': block_id,
                   'block': {'content': new_text}, 'claimed_class': claimed}]})


@pytest.fixture()
def doc_service(tmp_path):
    from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
    from app.protocol_workflow.application.manuscript_documents import ManuscriptDocumentService
    from datetime import datetime, timezone as _tz
    db = tmp_path / 'product.sqlite'
    service = ManuscriptDocumentService(
        build_unit_of_work_factory({'backend': 'sqlite', 'path': str(db)}),
        clock=lambda: datetime.now(_tz.utc))
    seed_working_document(service, {})
    return service


FACTS = {'intervention.dose_regimen': '计划入组100例，给药剂量为100mg，每21天为一个治疗周期。',
         'framing.structured_design': '随机双盲'}


def test_fact_drift_after_study_change_is_a_difference(doc_service):
    """F06/RC-07: the study dose moves 100 → 200 while the manuscript text
    still says 100 — the view must surface a stale-fact difference, not a
    green light."""
    _edit(doc_service, 'operation:edit:seed', 'blk:design',
          '本研究采用随机双盲设计，计划入组100例，给药剂量为100mg，每21天为一个治疗周期。')
    facts_now = {'intervention.dose_regimen': '计划入组200例，给药剂量为200mg，每21天为一个治疗周期。',
                 'framing.structured_design': '随机双盲'}
    view = doc_service.reconciliation(PROJECT, SD_ID, facts_now,
                                      study_revision_sha256='sha:study:S2')
    assert view['schema_version'] == 'manuscript-reconciliation.v2'
    assert view['status'] == 'differences', 'fact drift must not read as consistent'
    item = next(item for item in view['items'] if item['semantic_block_id'] == 'blk:design')
    assert item['stale_fact_paths'], 'the drifted fact path must be flagged'


def test_resolution_on_old_study_does_not_close_new_difference(doc_service):
    """F06/RC-08: an acknowledgement recorded on S1 reopens once the study is
    S2 — the same text cannot stay clean across a study change."""
    _edit(doc_service, 'operation:edit:seed', 'blk:design',
          '本研究采用随机双盲设计，计划入组100例，给药剂量为100mg，每21天为一个治疗周期。')
    doc_service.resolve_reconciliation(PROJECT, SD_ID, intent={
        'operation_id': 'operation:reconcile:s1', 'actor_id': 'user:example',
        'expected_revision': 2, 'semantic_block_id': 'blk:design', 'decision': 'accepted',
        'study_revision_sha256': 'sha:study:S1'})
    facts_s2 = {'intervention.dose_regimen': '计划入组200例，给药剂量为200mg，每21天为一个治疗周期。',
                'framing.structured_design': '随机双盲'}
    view = doc_service.reconciliation(PROJECT, SD_ID, facts_s2,
                                      study_revision_sha256='sha:study:S2')
    item = next(item for item in view['items'] if item['semantic_block_id'] == 'blk:design')
    assert item['resolved'] is False, 'an S1 acknowledgement cannot close an S2 difference'
    assert view['status'] == 'differences'


def test_resolution_on_current_study_still_closes(doc_service):
    _edit(doc_service, 'operation:edit:seed', 'blk:design',
          '本研究采用随机双盲设计，计划入组100例，给药剂量为100mg，每21天为一个治疗周期。')
    doc_service.resolve_reconciliation(PROJECT, SD_ID, intent={
        'operation_id': 'operation:reconcile:s2', 'actor_id': 'user:example',
        'expected_revision': 2, 'semantic_block_id': 'blk:design', 'decision': 'accepted',
        'study_revision_sha256': 'sha:study:S2'})
    view = doc_service.reconciliation(PROJECT, SD_ID, FACTS,
                                      study_revision_sha256='sha:study:S2')
    item = next(item for item in view['items'] if item['semantic_block_id'] == 'blk:design')
    assert item['resolved'] is True


def test_unchecked_document_is_never_consistent(doc_service):
    """F06/RC-06: with no machine-checkable signals the view says
    `not_checked` and reports honest coverage — a UI cannot render this as
    verified-consistent."""
    view = doc_service.reconciliation(PROJECT, SD_ID, FACTS,
                                      study_revision_sha256='sha:study:S2')
    assert view['status'] == 'not_checked'
    assert view['checked_block_count'] == 0
    assert view['content_block_count'] >= 1
    assert '未经机器核对' in view['coverage_note']


def test_new_unverified_addition_is_not_blessed_consistent(doc_service):
    """A checked block keeps its own scope; blocks never touched by edits stay
    outside the checked set — the top status may be scope-consistent but the
    coverage counts still show the unchecked remainder."""
    _edit(doc_service, 'operation:edit:seed', 'blk:followup',
          '参与者按计划接受研究治疗，并如实记录全部伴随用药与合并治疗。')
    view = doc_service.reconciliation(PROJECT, SD_ID, FACTS,
                                      study_revision_sha256='sha:study:S2')
    assert view['status'] in ('differences', 'consistent_within_checked_scope')
    assert view['checked_block_count'] < view['content_block_count'], \
        'blocks without edit clues were not machine-checked and count as such'
