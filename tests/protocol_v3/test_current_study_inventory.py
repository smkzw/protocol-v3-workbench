"""Discover existing study identities before creating a competing aggregate."""
from test_repository_backends import store, _study
from app.protocol_workflow.canonical.study_definition import study_revision_hash


def test_current_inventory_keeps_one_latest_revision_per_study(store):
    project = 'project:inventory'
    with store.factory() as uow:
        uow.study_definition_cas_repository.save_with_expected_revision(project, _study(project_id=project, study_id='study:b'), 0)
        first = uow.study_definition_cas_repository.save_with_expected_revision(project, _study(project_id=project, study_id='study:a'), 0)
        uow.study_definition_cas_repository.save_with_expected_revision(project,
            _study(project_id=project, study_id='study:a', revision=2, previous=study_revision_hash(first)), 1)
        uow.study_definition_cas_repository.save_with_expected_revision('project:other',
            _study(project_id='project:other', study_id='study:elsewhere'), 0)
    found = store.inspect(lambda uow: uow.study_definition_repository.list_current(project))
    assert [(s.study_definition_id, s.revision) for s in found] == [('study:a', 2), ('study:b', 1)]
    assert store.inspect(lambda uow: uow.study_definition_repository.list_current('project:absent')) == ()
    assert store.inspect(lambda uow: uow.study_definition_repository.get_at_revision(project, 'study:a', 1)).revision == 1
