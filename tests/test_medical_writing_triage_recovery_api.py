from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

# Qoder's concurrent design-projection slice defines these models but has not
# yet exported them from the package entrypoint. Keep this compatibility shim
# test-local so the bounded triage API can be exercised without editing that
# worker-owned shared contract.
import packages.contracts.workbench_contracts as workbench_contracts
from packages.contracts.workbench_contracts import models as contract_models

for _name in (
    "MedicalWritingNormalizedDesignProjection",
    "MedicalWritingNormalizedDesignView",
    "MedicalWritingNormalizedDesignProjectionWithSources",
):
    if not hasattr(workbench_contracts, _name):
        setattr(workbench_contracts, _name, getattr(contract_models, _name))

from services.api.app import main


class _Dumpable:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, *, mode="python"):
        return dict(self.payload)


class CompetitorTriageRecoveryApiTests(unittest.TestCase):
    def test_research_pipeline_triage_retry_is_bound_to_current_parent(self):
        result = {
            "pipeline": {
                "pipeline_id": "mwpipe-current",
                "triage_run_id": "ct-run-current",
                "stage": "triaging",
            },
            "triage_job_id": "job-retry-current",
            "reused": False,
        }
        payload = {
            "actor": "medical_manager",
            "idempotency_key": "retry-triage-current-001",
            "expected_pipeline_id": "mwpipe-current",
            "expected_triage_run_id": "ct-run-current",
        }
        with (
            patch.object(
                main,
                "_canonical_module_project_id",
                return_value="proj-canonical",
            ),
            patch.object(
                main.medical_writing_research_pipeline_service,
                "retry_triage",
                return_value=result,
            ) as retry_mock,
        ):
            response = main.retry_medical_writing_research_pipeline_triage(
                "proj-alias", payload
            )

        self.assertEqual(result, response)
        retry_mock.assert_called_once_with(
            "proj-canonical",
            actor="medical_manager",
            idempotency_key="retry-triage-current-001",
            expected_pipeline_id="mwpipe-current",
            expected_triage_run_id="ct-run-current",
        )

    def test_latest_route_precedes_dynamic_run_route(self):
        # Newer FastAPI versions may keep lazy _IncludedRouter sentinels in the
        # route list after another test exercises an included router. Only
        # concrete routes participate in the precedence contract.
        paths = [
            route.path
            for route in main.app.routes
            if getattr(route, "path", None)
        ]
        latest = (
            "/api/projects/{project_id}/medical-writing/authoring-journey/"
            "competitor-triage/latest"
        )
        dynamic = (
            "/api/projects/{project_id}/medical-writing/authoring-journey/"
            "competitor-triage/{run_id}"
        )
        self.assertLess(paths.index(latest), paths.index(dynamic))

    def test_latest_route_is_strictly_scoped_to_requested_snapshot(self):
        latest = SimpleNamespace(run_id="ct_run_latest")
        response = _Dumpable(
            {
                "run": {
                    "run_id": "ct_run_latest",
                    "project_id": "proj-canonical",
                    "snapshot_id": "snapshot-current",
                    "status": "review_ready",
                },
                "summary": {"status": "review_ready"},
            }
        )
        with (
            patch.object(
                main,
                "_canonical_module_project_id",
                return_value="proj-canonical",
            ),
            patch.object(
                main.writing_reference_repository,
                "latest_triage_run_for_snapshot",
                return_value=latest,
            ) as latest_mock,
            patch.object(
                main.competitor_triage_service,
                "get_run",
                return_value=response,
            ) as get_mock,
        ):
            payload = main.get_latest_competitor_triage_run(
                "proj-alias", snapshot_id="snapshot-current"
            )

        self.assertEqual("ct_run_latest", payload["run"]["run_id"])
        latest_mock.assert_called_once_with("proj-canonical", "snapshot-current")
        get_mock.assert_called_once_with("proj-canonical", "ct_run_latest")

    def test_latest_route_returns_explicit_404_when_snapshot_has_no_run(self):
        with (
            patch.object(
                main,
                "_canonical_module_project_id",
                return_value="proj-canonical",
            ),
            patch.object(
                main.writing_reference_repository,
                "latest_triage_run_for_snapshot",
                return_value=None,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                main.get_latest_competitor_triage_run(
                    "proj-alias", snapshot_id="snapshot-empty"
                )

        self.assertEqual(404, raised.exception.status_code)
        self.assertIn("snapshot-empty", raised.exception.detail)

    def test_confirm_passes_final_classifications_to_single_service_call(self):
        final_classifications = {
            "NCT00000001": "indirect_reference",
            "NCT00000002": "excluded",
        }
        confirmation = _Dumpable(
            {
                "confirmation_id": "ct_conf_001",
                "run_id": "ct_run_001",
                "snapshot_id": "snapshot-current",
                "projection_status": "corpus_projected",
                "final_classifications": final_classifications,
            }
        )
        payload = {
            "expected_run_revision": "canonical-input-hash",
            "retained_nct_ids": ["NCT00000001"],
            "excluded_nct_ids": ["NCT00000002"],
            "final_classifications": final_classifications,
            "no_suitable_competitor_reason": "",
            "actor": "medical_manager",
            "reason": "医学经理逐项审核后调整第一项分类。",
            "idempotency_key": "confirm-triage-override-001",
            "expected_journey_revision": 7,
        }

        with (
            patch.object(
                main,
                "_canonical_module_project_id",
                return_value="proj-canonical",
            ),
            patch.object(
                main.competitor_triage_service,
                "confirm_basket",
                return_value=confirmation,
            ) as confirm_mock,
            patch.object(
                main.writing_reference_repository,
                "record_relevance_decision",
            ) as record_mock,
            patch.object(
                main.medical_writing_research_pipeline_service,
                "advance_after_basket_confirm",
                return_value={"pipeline": {"stage": ""}, "advanced": False},
            ),
        ):
            result = main.confirm_competitor_triage_basket(
                "proj-alias", "ct_run_001", payload
            )

        confirm_mock.assert_called_once()
        request = confirm_mock.call_args.args[2]
        self.assertEqual(
            "indirect_reference",
            request.final_classifications["NCT00000001"].value,
        )
        self.assertEqual(final_classifications, result["final_classifications"])
        record_mock.assert_not_called()

    def test_confirm_rejects_invalid_final_classification_contract(self):
        payload = {
            "expected_run_revision": "canonical-input-hash",
            "retained_nct_ids": ["NCT00000001"],
            "excluded_nct_ids": ["NCT00000002"],
            "final_classifications": {
                "NCT00000001": "direct_competitor",
                "NCT00000002": "maybe",
            },
            "no_suitable_competitor_reason": "",
            "actor": "medical_manager",
            "reason": "",
            "idempotency_key": "confirm-triage-incomplete-001",
            "expected_journey_revision": 7,
        }
        with (
            patch.object(
                main,
                "_canonical_module_project_id",
                return_value="proj-canonical",
            ),
            patch.object(
                main.competitor_triage_service,
                "confirm_basket",
            ) as confirm_mock,
        ):
            with self.assertRaises(HTTPException) as raised:
                main.confirm_competitor_triage_basket(
                    "proj-alias", "ct_run_001", payload
                )

        self.assertEqual(422, raised.exception.status_code)
        confirm_mock.assert_not_called()

    def test_reconfirm_reuses_existing_work_without_advancing_pipeline(self):
        confirmation = _Dumpable(
            {
                "confirmation_id": "ct_reconf_001",
                "run_id": "ct_run_001",
                "snapshot_id": "snapshot-current",
                "projection_status": "corpus_projected",
                "confirmation_kind": "human_reconfirmation",
                "source_confirmation_id": "ct_conf_001",
                "retained_nct_ids": ["NCT00000001"],
                "excluded_nct_ids": ["NCT00000002"],
                "final_classifications": {
                    "NCT00000001": "direct_competitor",
                    "NCT00000002": "excluded",
                },
            }
        )
        request = contract_models.CompetitorTriageBasketReconfirmationRequest(
            source_confirmation_id="ct_conf_001",
            expected_journey_revision=9,
            retained_nct_ids=["NCT00000001"],
            excluded_nct_ids=["NCT00000002"],
            final_classifications={
                "NCT00000001": "direct_competitor",
                "NCT00000002": "excluded",
            },
            actor="medical_manager",
            idempotency_key="reconfirm-triage-001",
        )
        with (
            patch.object(
                main,
                "_canonical_module_project_id",
                return_value="proj-canonical",
            ),
            patch.object(
                main.competitor_triage_service,
                "reconfirm_basket",
                return_value=confirmation,
            ) as reconfirm_mock,
            patch.object(
                main.medical_writing_research_pipeline_service,
                "advance_after_basket_confirm",
            ) as advance_mock,
        ):
            result = main.reconfirm_competitor_triage_basket(
                "proj-alias", "ct_run_001", request
            )

        reconfirm_mock.assert_called_once_with(
            "proj-canonical", "ct_run_001", request
        )
        advance_mock.assert_not_called()
        self.assertFalse(result["pipeline_advanced"])
        self.assertFalse(result["external_work_repeated"])


    def test_confirm_advances_parent_pipeline_after_basket_confirmation(self):
        """MW-A1-002: one-click basket confirm must also advance the parent
        research pipeline from awaiting_triage_confirm without a second
        user action."""
        final_classifications = {
            "NCT00000001": "indirect_reference",
            "NCT00000002": "excluded",
        }
        confirmation = _Dumpable(
            {
                "confirmation_id": "ct_conf_advance_001",
                "run_id": "ct_run_001",
                "snapshot_id": "snapshot-current",
                "projection_status": "discovery_projected",
                "final_classifications": final_classifications,
            }
        )
        pipeline_advance_result = {
            "pipeline": {
                "pipeline_id": "mwpipe-current",
                "stage": "preparing",
                "percent": 50,
            },
            "advanced": True,
        }
        payload = {
            "expected_run_revision": "canonical-input-hash",
            "retained_nct_ids": ["NCT00000001"],
            "excluded_nct_ids": ["NCT00000002"],
            "final_classifications": final_classifications,
            "no_suitable_competitor_reason": "",
            "actor": "medical_manager",
            "reason": "确认后流水线应自动继续。",
            "idempotency_key": "confirm-triage-advance-001",
            "expected_journey_revision": 7,
        }
        with (
            patch.object(
                main,
                "_canonical_module_project_id",
                return_value="proj-canonical",
            ),
            patch.object(
                main.competitor_triage_service,
                "confirm_basket",
                return_value=confirmation,
            ) as confirm_mock,
            patch.object(
                main.medical_writing_research_pipeline_service,
                "advance_after_basket_confirm",
                return_value=pipeline_advance_result,
            ) as advance_mock,
        ):
            result = main.confirm_competitor_triage_basket(
                "proj-alias", "ct_run_001", payload
            )

        confirm_mock.assert_called_once()
        advance_mock.assert_called_once()
        # The advance call must use a deterministic idempotency key derived
        # from the confirmation_id, so repeated calls are idempotent.
        advance_call = advance_mock.call_args
        self.assertEqual(
            "confirm-advance-ct_conf_advance_001",
            advance_call.kwargs.get("idempotency_key"),
        )
        self.assertTrue(result["pipeline_advanced"])
        self.assertEqual("preparing", result["pipeline"]["stage"])

    def test_confirm_does_not_fail_when_pipeline_advance_is_not_applicable(self):
        """If no pipeline exists, the confirm still succeeds; pipeline_advanced
        is False but the response is 200."""
        final_classifications = {
            "NCT00000001": "direct_competitor",
            "NCT00000002": "excluded",
        }
        confirmation = _Dumpable(
            {
                "confirmation_id": "ct_conf_no_pipe_001",
                "run_id": "ct_run_001",
                "snapshot_id": "snapshot-current",
                "projection_status": "discovery_projected",
                "final_classifications": final_classifications,
            }
        )
        pipeline_advance_result = {
            "pipeline": {"stage": "", "percent": 0},
            "advanced": False,
        }
        payload = {
            "expected_run_revision": "canonical-input-hash",
            "retained_nct_ids": ["NCT00000001"],
            "excluded_nct_ids": ["NCT00000002"],
            "final_classifications": final_classifications,
            "no_suitable_competitor_reason": "",
            "actor": "medical_manager",
            "reason": "",
            "idempotency_key": "confirm-triage-no-pipe-001",
            "expected_journey_revision": 7,
        }
        with (
            patch.object(
                main,
                "_canonical_module_project_id",
                return_value="proj-canonical",
            ),
            patch.object(
                main.competitor_triage_service,
                "confirm_basket",
                return_value=confirmation,
            ),
            patch.object(
                main.medical_writing_research_pipeline_service,
                "advance_after_basket_confirm",
                return_value=pipeline_advance_result,
            ),
        ):
            result = main.confirm_competitor_triage_basket(
                "proj-alias", "ct_run_001", payload
            )

        self.assertFalse(result["pipeline_advanced"])
        self.assertEqual(final_classifications, result["final_classifications"])


    def test_confirm_threads_retained_ids_from_confirmation_into_advance(self):
        """MW-A1-002 P0: the exact retained_nct_ids from the confirmation
        response must be passed into advance_after_basket_confirm so the
        resume path uses the medical manager's exact one-click decision,
        not a recomputed set."""
        final_classifications = {
            "NCT00000001": "direct_competitor",
            "NCT00000002": "indirect_reference",
            "NCT00000003": "excluded",
        }
        # Manager adjusted: retained NCT00000002 (indirect) but excluded
        # NCT00000001 (direct per AI). The exact retained set must be
        # preserved — not recomputed from AI classifications.
        confirmation = _Dumpable(
            {
                "confirmation_id": "ct_conf_retained_001",
                "run_id": "ct_run_001",
                "snapshot_id": "snapshot-current",
                "projection_status": "discovery_projected",
                "final_classifications": final_classifications,
                "retained_nct_ids": ["NCT00000002"],
                "excluded_nct_ids": ["NCT00000001", "NCT00000003"],
            }
        )
        pipeline_advance_result = {
            "pipeline": {"stage": "preparing", "percent": 50},
            "advanced": True,
        }
        payload = {
            "expected_run_revision": "canonical-input-hash",
            "retained_nct_ids": ["NCT00000002"],
            "excluded_nct_ids": ["NCT00000001", "NCT00000003"],
            "final_classifications": final_classifications,
            "no_suitable_competitor_reason": "",
            "actor": "medical_manager",
            "reason": "经理调整：保留间接参照，排除AI建议的直接竞品。",
            "idempotency_key": "confirm-retained-threads-001",
            "expected_journey_revision": 7,
        }
        with (
            patch.object(
                main,
                "_canonical_module_project_id",
                return_value="proj-canonical",
            ),
            patch.object(
                main.competitor_triage_service,
                "confirm_basket",
                return_value=confirmation,
            ),
            patch.object(
                main.medical_writing_research_pipeline_service,
                "advance_after_basket_confirm",
                return_value=pipeline_advance_result,
            ) as advance_mock,
        ):
            main.confirm_competitor_triage_basket(
                "proj-alias", "ct_run_001", payload
            )

        advance_call = advance_mock.call_args
        # The exact manager-adjusted retained set must be threaded through
        passed_retained = advance_call.kwargs.get("retained_candidate_ids")
        self.assertEqual(["NCT00000002"], passed_retained)

    def test_confirm_advance_idempotent_on_repeat(self):
        """Repeated confirm calls must use the same deterministic advance
        idempotency key derived from the confirmation_id."""
        final_classifications = {
            "NCT00000001": "direct_competitor",
            "NCT00000002": "excluded",
        }
        confirmation = _Dumpable(
            {
                "confirmation_id": "ct_conf_idem_001",
                "run_id": "ct_run_001",
                "snapshot_id": "snapshot-current",
                "projection_status": "discovery_projected",
                "final_classifications": final_classifications,
                "retained_nct_ids": ["NCT00000001"],
                "excluded_nct_ids": ["NCT00000002"],
            }
        )
        pipeline_advance_result = {
            "pipeline": {"stage": "preparing"},
            "advanced": True,
        }
        payload = {
            "expected_run_revision": "canonical-input-hash",
            "retained_nct_ids": ["NCT00000001"],
            "excluded_nct_ids": ["NCT00000002"],
            "final_classifications": final_classifications,
            "no_suitable_competitor_reason": "",
            "actor": "medical_manager",
            "reason": "",
            "idempotency_key": "confirm-idem-001",
            "expected_journey_revision": 7,
        }
        for _ in range(3):
            with (
                patch.object(
                    main,
                    "_canonical_module_project_id",
                    return_value="proj-canonical",
                ),
                patch.object(
                    main.competitor_triage_service,
                    "confirm_basket",
                    return_value=confirmation,
                ),
                patch.object(
                    main.medical_writing_research_pipeline_service,
                    "advance_after_basket_confirm",
                    return_value=pipeline_advance_result,
                ) as advance_mock,
            ):
                main.confirm_competitor_triage_basket(
                    "proj-alias", "ct_run_001", payload
                )

        # All three calls use the same deterministic key
        keys = [
            call.kwargs.get("idempotency_key")
            for call in advance_mock.call_args_list
        ]
        self.assertTrue(
            all(k == "confirm-advance-ct_conf_idem_001" for k in keys),
            f"Expected all keys to be confirm-advance-ct_conf_idem_001, got {keys}",
        )


if __name__ == "__main__":
    unittest.main()
