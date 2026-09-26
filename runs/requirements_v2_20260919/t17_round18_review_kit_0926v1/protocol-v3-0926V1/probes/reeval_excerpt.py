"""Source-derived structural probes; only IO/models/checker are test doubles.

Source: writing_reference_translation_batch.py at 53feb06f,
_find_integration_for_reeval and _evaluate_integration_for_reeval.
NOT an execution of real Pydantic contracts, translation checker or admission.
"""
import json
from types import SimpleNamespace

TENANT_ID='fixture_tenant'
class ChapterTranslationPipelineError(Exception):
    pass
class ChapterIntegrationResult:
    @staticmethod
    def model_validate_json(payload):
        return SimpleNamespace(**json.loads(payload))

class ReevalExcerpt:
    def _find_integration_for_reeval(self, project_id, plan_id, chapter_id):
        with self.repository._connect() as connection:
            rows = connection.execute(
                '''SELECT payload_json FROM writing_reference_chapter_integration_results
                   WHERE tenant_id=? AND project_id=? AND plan_id=? AND chapter_id=?''',
                (TENANT_ID, project_id, plan_id, chapter_id),
            ).fetchall()
            if not rows:
                rows = connection.execute(
                    '''SELECT payload_json FROM writing_reference_chapter_integration_results
                       WHERE tenant_id=? AND project_id=? AND plan_id=?
                         AND chapter_id LIKE ? ORDER BY created_at DESC''',
                    (TENANT_ID, project_id, plan_id, chapter_id + ':%'),
                ).fetchall()
        candidates = [ChapterIntegrationResult.model_validate_json(row['payload_json']) for row in rows]
        if not candidates:
            return None
        candidates.sort(
            key=lambda result: (bool(result.chunk_ids) and result.status == 'completed', result.created_at),
            reverse=True,
        )
        return candidates[0]

    def _evaluate_integration_for_reeval(self, project_id, integration):
        if str(integration.blocked_raw_provider_output or '').strip():
            return 'data_missing', []
        chunk_ids = list(integration.chunk_ids or [])
        if not chunk_ids:
            return 'data_missing', []
        chunks_by_id = {
            chunk.chunk_id: chunk
            for chunk in self.repository.translation_chunks_for_plan(project_id, integration.plan_id)
        }
        all_codes = []
        for chunk_id in chunk_ids:
            chunk = chunks_by_id.get(chunk_id)
            if (chunk is None or chunk.status != 'completed'
                    or not chunk.source_text.strip() or not chunk.translated_text.strip()):
                return 'data_missing', []
            try:
                units = split_source_into_units(chunk.source_text)
                target_map = reconstruct_unit_map(chunk.translated_text, chunk.unit_targets, units)
            except ChapterTranslationPipelineError:
                return 'data_missing', []
            all_codes.extend(evaluate_translation_fidelity_aligned_units(units, target_map))
        codes = list(dict.fromkeys(all_codes))
        return ('rejected' if codes else 'admitted'), codes
