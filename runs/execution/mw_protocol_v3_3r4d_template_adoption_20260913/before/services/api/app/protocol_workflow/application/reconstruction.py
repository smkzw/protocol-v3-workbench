"""Pure study reconstruction from immutable events; never reads snapshots."""

from packages.contracts.workbench_contracts.protocol_v3 import DecisionRecord, StudyDefinitionV3
from app.protocol_workflow.canonical.study_definition import StudyDefinitionReducer, study_revision_hash
from app.protocol_workflow.canonical.decision_inputs import DecisionInputBinding
from app.protocol_workflow.events.models import EventTypeRegistry, UpcasterRegistry
from app.protocol_workflow.events.store import EventReplayEngine


class _StudyReplayReducer:
    def initial_state(self):
        return None

    def apply(self, current, payload, event):
        if event.event_type == "study_definition.created":
            if current is not None or payload.get("reconstruction_schema_version") != "study_genesis_v1":
                raise ValueError("missing or unsupported immutable genesis baseline")
            rebuilt = StudyDefinitionV3.model_validate(payload["genesis_definition"])
            if rebuilt.revision != 1:
                raise ValueError("genesis must be revision one")
        else:
            if current is None:
                raise ValueError("decision requires immutable genesis baseline")
            binding = (
                DecisionInputBinding.model_validate(payload["decision_input_binding"])
                if "decision_input_binding" in payload else None
            )
            operation = payload.get("operation")
            if operation not in (None, "confirmed_fact_revision.v1"):
                raise ValueError("unsupported fact revision operation")
            rebuilt = StudyDefinitionReducer().apply_decision(
                current, DecisionRecord.model_validate(payload["decision_record"]),
                fact_updates=payload["fact_updates"], now=event.emitted_at,
                revise_confirmed_facts=operation == "confirmed_fact_revision.v1",
                decision_input_refs=binding.refs if binding is not None else None,
            )
        if rebuilt.project_id != payload["project_id"] or rebuilt.study_definition_id != payload["study_definition_id"]:
            raise ValueError("event and reconstructed study identity differ")
        if study_revision_hash(rebuilt) != payload["result_revision_sha256"]:
            raise ValueError("reconstructed revision differs from committed event")
        return rebuilt

    def canonical_revision_hash(self, state):
        return study_revision_hash(state)


def reconstruct_study(events):
    """Return the existing replay outcome, including unsupported legacy streams."""
    registry = UpcasterRegistry(current_schema_version="mw_protocol_v3_event_v1")
    registry.register_noop("mw_protocol_v3_event_v1")
    return EventReplayEngine(
        upcasters=registry,
        event_types=EventTypeRegistry([
            "study_definition.created", "study_definition.decision_applied",
        ]),
        reducer=_StudyReplayReducer(),
    ).replay_stream(events)
