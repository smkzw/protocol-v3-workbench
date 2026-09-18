"""Persist full source material once; reopening must not reparse or redatestamp."""
from datetime import datetime,timezone
import pytest
from test_source_identity_product import service,adopt
from test_writing_reference_docx import build_docx,paragraph_xml
from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.agent1.research_seed import prepare_seed_request
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory,build_committed_reservation_repository_factory
from test_template_fact_adoption import _dump


def test_full_source_preparation_recovers_original_bundle_without_source_reads(tmp_path):
    from app.protocol_workflow.agent3.source_preparation import build_source_preparation
    original=build_docx(paragraph_xml('完整来源最后一句'))
    adopted=adopt(service(tmp_path),original)
    seed=prepare_seed_request('合成说明',((adopted.source.source,parse_docx(original)),))
    config={'backend':'sqlite','path':str(tmp_path/'preparation.sqlite')}
    clock=lambda:datetime(2026,9,13,12,tzinfo=timezone.utc)
    def create(source_service,when):
        return build_source_preparation(project_id='project-1',branch_id='main',
            uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            source_service=source_service,clock=when)
    coordinator=create(service(tmp_path),clock)
    run_id=coordinator.start(seed)
    assert coordinator.start(seed)==run_id
    bundle=coordinator.resume(run_id)
    assert bundle.evidence[0].body=='完整来源最后一句'
    assert bundle.evidence[0].extracted_at==clock()
    before=_dump(tmp_path/'preparation.sqlite')
    class UnavailableSources:
        def history(self,*args):raise AssertionError('Recovery must read the original bundle')
    reopened=create(UnavailableSources(),lambda:datetime(2027,1,1,tzinfo=timezone.utc))
    assert reopened.start(seed)==run_id
    restored=reopened.resume(run_id)
    assert restored.payload_json==bundle.payload_json
    assert restored.input_sha256==bundle.input_sha256
    assert _dump(tmp_path/'preparation.sqlite')==before
    with build_unit_of_work_factory(config)() as uow:
        assert uow.study_definition_repository.list_current('project-1')==()
        assert uow.semantic_document_repository.list_current('project-1')==()


def test_source_read_failure_reports_durable_blocked_state_without_silent_reprocessing(tmp_path):
    import pytest
    from app.protocol_workflow.agent3.source_preparation import build_source_preparation,SourcePreparationIncomplete
    config={'backend':'sqlite','path':str(tmp_path/'failed.sqlite')}
    class BrokenSource:
        calls=0
        def history(self,*args):
            self.calls+=1
            raise RuntimeError('synthetic unexpected executor failure')
    broken=BrokenSource()
    owner=build_source_preparation(project_id='project-1',branch_id='main',
        uow_factory=build_unit_of_work_factory(config),
        reservation_repository_factory=build_committed_reservation_repository_factory(config),source_service=broken)
    run=owner.start(prepare_seed_request('合成说明',()))
    assert owner.state(run)['status']=='running'
    with pytest.raises(SourcePreparationIncomplete) as failure:
        owner.resume(run)
    assert failure.value.state['status']=='blocked'
    assert failure.value.state['error_code']
    before=_dump(tmp_path/'failed.sqlite')
    with pytest.raises(SourcePreparationIncomplete):owner.resume(run)
    assert broken.calls==1 and _dump(tmp_path/'failed.sqlite')==before


@pytest.mark.parametrize('missing_source',[False,True])
def test_explicit_source_retry_reuses_run_and_keeps_failed_attempt(tmp_path,missing_source):
    import pytest
    from app.protocol_workflow.agent3.source_preparation import build_source_preparation,SourcePreparationIncomplete
    raw=build_docx(paragraph_xml('恢复后同一原始来源'))
    first=adopt(service(tmp_path),raw)
    seed=prepare_seed_request('合成说明',((first.source.source,parse_docx(raw)),))
    class Intermittent:
        calls=0
        def history(self,*args):
            self.calls+=1
            if self.calls==1:
                if missing_source:return ()
                raise OSError('synthetic temporary read failure')
            return service(tmp_path).history(*args)
        def read_content(self,*args):return service(tmp_path).read_content(*args)
    sources=Intermittent()
    config={'backend':'sqlite','path':str(tmp_path/'retry.sqlite')}
    owner=build_source_preparation(project_id='project-1',branch_id='main',uow_factory=build_unit_of_work_factory(config),
        reservation_repository_factory=build_committed_reservation_repository_factory(config),source_service=sources)
    run=owner.start(seed)
    with pytest.raises(SourcePreparationIncomplete):owner.resume(run)
    bundle=owner.retry(run,retry_decision_id='source-retry:one')
    assert bundle.evidence[0].body=='恢复后同一原始来源'
    assert len(owner.runtime.reservation_attempts(run,'prepare-sources'))==1
    assert len(owner.runtime.reservation_attempts(run+':retry:1','prepare-sources'))==1
    original=owner._output(run)
    assert original['source_preparation_failure']['code']==('chapter_source_not_found' if missing_source else 'chapter_source_read_failed')
    before=_dump(tmp_path/'retry.sqlite')
    assert owner.retry(run,retry_decision_id='source-retry:one')==bundle
    with pytest.raises(ValueError,match='chapter_source_retry_identity_mismatch'):
        owner.retry(run,retry_decision_id='source-retry:different')
    with pytest.raises(ValueError,match='chapter_source_retry_identity_mismatch'):
        owner.retry(run+':retry:1',retry_decision_id='source-retry:different')
    assert sources.calls==2 and _dump(tmp_path/'retry.sqlite')==before


@pytest.mark.parametrize('same_identity',[False,True])
def test_retry_registration_race_preserves_one_child_before_execution(tmp_path,same_identity):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.protocol_workflow.agent3.source_preparation import build_source_preparation,SourcePreparationIncomplete
    from app.protocol_workflow.graph import GraphRunError
    config={'backend':'sqlite','path':str(tmp_path/'race.sqlite')}
    class Unavailable:
        calls=0
        def history(self,*args):
            self.calls+=1
            raise OSError('synthetic unavailable source')
    sources=Unavailable()
    def create():
        return build_source_preparation(project_id='project-1',branch_id='main',
            uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),source_service=sources)
    original=create();run=original.start(prepare_seed_request('合成说明',()))
    with pytest.raises(SourcePreparationIncomplete):original.resume(run)
    barrier=Barrier(2)
    def register(identity):
        owner=create()
        start=owner.runtime.start_run
        def synchronized(*args,**kwargs):
            barrier.wait(timeout=10)
            return start(*args,**kwargs)
        owner.runtime.start_run=synchronized
        try:return owner.start_retry(run,retry_decision_id=identity)
        except ValueError as exc:return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(register,'retry:one'),pool.submit(register,'retry:one' if same_identity else 'retry:two')]
        results=[future.result() for future in futures]
    states=[result for result in results if isinstance(result,dict)]
    assert len(states)==(2 if same_identity else 1),results
    if not same_identity:assert 'chapter_source_retry_identity_mismatch' in results
    assert all(state['status']=='running' and state['retry_run_id']==run+':retry:1' for state in states)
    assert sources.calls==1
    assert len(original.runtime.reservation_attempts(run+':retry:1','prepare-sources'))==0
    assert original._output(run)['source_preparation_failure']['code']=='chapter_source_read_failed'
