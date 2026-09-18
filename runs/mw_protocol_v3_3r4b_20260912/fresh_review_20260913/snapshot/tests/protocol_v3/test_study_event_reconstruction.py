"""Study reconstruction must use events, not the current aggregate snapshot."""

from app.protocol_workflow.application import study_definition_stream_id
import pytest
from tests.protocol_v3.integration import integration_shared as shared


def test_genesis_event_preserves_facts_needed_for_independent_reconstruction(tmp_path):
    factory = shared.make_factory(tmp_path / "reconstruction.sqlite")
    service = shared.make_service(factory)
    created = service.create_study_definition(shared.create_command(
        project_id="proj:reconstruction", study_definition_id="sd:reconstruction",
        idempotency_key="idem:reconstruction",
    ))
    with factory() as uow:
        events = uow.event_stream_repository.read_events(
            "proj:reconstruction", study_definition_stream_id("sd:reconstruction")
        )
    assert len(events) == 1
    assert events[0].payload["genesis_definition"] == created.definition.model_dump(mode="json")


def test_rebuild_from_events_after_fact_change_matches_saved_revision(tmp_path):
    from app.protocol_workflow.application.reconstruction import reconstruct_study

    factory = shared.make_factory(tmp_path / "fold.sqlite")
    service = shared.make_service(factory)
    created = service.create_study_definition(shared.create_command(
        project_id="proj:fold", study_definition_id="sd:fold", idempotency_key="idem:fold:1",
    ))
    changed = service.apply_decision(shared.apply_command(
        project_id="proj:fold", study_definition_id="sd:fold", idempotency_key="idem:fold:2",
        expected_revision=1, snapshot_sha256=created.revision_sha256,
        decision_record_id="decision:fold:2", fact_updates=dict(shared.NEW_FACT),
    ))
    with factory() as uow:
        events = uow.event_stream_repository.read_events("proj:fold", study_definition_stream_id("sd:fold"))
    outcome = reconstruct_study(events)
    assert not outcome.is_quarantined
    assert outcome.success.canonical_revision_sha256 == changed.revision_sha256
    assert outcome.success.final_state == changed.definition


@pytest.mark.parametrize("version", [None, "study_genesis_future"])
def test_unsupported_genesis_is_reported_without_inventing_state(tmp_path, version):
    from app.protocol_workflow.application.reconstruction import reconstruct_study
    from app.protocol_workflow.events.models import EventEnvelopeBuilder

    factory = shared.make_factory(tmp_path / "legacy.sqlite")
    shared.make_service(factory).create_study_definition(shared.create_command(
        project_id="proj:legacy", study_definition_id="sd:legacy", idempotency_key="idem:legacy",
    ))
    with factory() as uow:
        original = uow.event_stream_repository.read_events("proj:legacy", study_definition_stream_id("sd:legacy"))[0]
    payload = dict(original.payload)
    if version is None:
        payload.pop("reconstruction_schema_version")
        payload.pop("genesis_definition")
    else:
        payload["reconstruction_schema_version"] = version
    # A separate synthetic, validly hashed legacy fixture; never overwrite DB.
    legacy = EventEnvelopeBuilder().build(**{
        name: getattr(original, name) for name in (
            "domain_event_id", "stream_id", "sequence", "event_type",
            "payload_schema_version", "upcaster_id", "actor_type", "actor_id",
            "action", "reason", "emitted_at", "previous_event_sha256",
        )
    }, payload=payload)
    before = shared.dump_business_tables(tmp_path / "legacy.sqlite")
    outcome = reconstruct_study([legacy])
    assert outcome.is_quarantined
    assert "genesis baseline" in outcome.quarantine.detail
    assert outcome.quarantine.partial_state is None
    assert shared.dump_business_tables(tmp_path / "legacy.sqlite") == before
