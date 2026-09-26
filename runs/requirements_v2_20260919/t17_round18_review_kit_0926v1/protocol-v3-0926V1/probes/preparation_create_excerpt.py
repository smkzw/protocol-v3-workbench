"""Preparation create prefix from reviewed source, with explicitly mocked IO.

Source: services/api/app/writing_reference_preparation_batch.py
53feb06fc1402df820a6dba5d8b6e3fa15d50437; create lines 210-247,
staticmethod _study_facts_hash shown in commit 1ab056a.
No production database, model or network is used. Prefix stops at scope hashing.
"""
from hashlib import sha256
import json

DEFAULT_PREPARATION_STAGE_SIZE = 8
MAX_PREPARATION_STAGE_SIZE = 32

def _payload_hash(value):
    return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

class PreparationPrefix:
    @staticmethod
    def _study_facts_hash(journey):
        # Harness stand-in; original delegates to _material_facts_hash.
        return _payload_hash(journey)

    def create(self, project_id, request):
        stage_size = min(
            MAX_PREPARATION_STAGE_SIZE,
            max(1, int(request.stage_size or DEFAULT_PREPARATION_STAGE_SIZE)),
        )
        request_hash = _payload_hash(
            {"snapshot_id": request.snapshot_id, "stage_size": stage_size}
        )
        replay = self._idempotent_batch(
            project_id,
            "create_preparation_batch",
            request.idempotency_key,
            request_hash,
        )
        if replay:
            return self.get(project_id, replay)

        retained_ids, scope_entries = self._frozen_scope(project_id, request.snapshot_id)
        scope_sha256 = _payload_hash(
            {
                "project_id": project_id,
                "snapshot_id": request.snapshot_id,
                "retained_candidate_ids": retained_ids,
                "entries": scope_entries,
                "study_facts_sha256": _study_facts_hash(journey),
            }
        )
        return scope_sha256  # Harness boundary; no IO beyond this prefix.
