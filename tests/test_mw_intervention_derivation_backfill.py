"""R26 self-check R5 #2, P0-A backend counterexample (red-first, then fix).

Field evidence (proj_user_f6b25587e9b2): the assembly blocker
intervention.investigational_product_regimen could never be cleared.  The
legacy derivation (_derive_structured_intervention_rules_from_legacy) can
deterministically derive BOTH the IP and the placebo regimen from the
already-filled legacy fields, but it is skipped wholesale once
``intervention_rules.authority == structured`` — and once ANY manual row
(e.g. only the placebo row) lands as structured, the derivation is locked
out forever.  Combined with the frontend editor rows being lost in flight,
the user is left with "编辑器存不进 + 派生被锁死" and no path to the
required IP regimen.

Fixed contract pinned here: when the rules are already structured but a
REQUIRED regimen role is missing (investigational_product, or placebo under
a confirmed placebo-controlled design) AND the legacy text the derivation
needs is present, the derivation backfills exactly the missing role
(idempotent fixed ids) instead of returning unchanged.  Fully-populated
structured rules are still never touched.
"""
from __future__ import annotations

import unittest

from packages.contracts.workbench_contracts import (
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingJourneyImpactPreviewRequest,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from tests.test_medical_writing_authoring_journey import (
    _complete_framing,
    _complete_picos,
)

try:
    from tempfile import TemporaryDirectory
    from pathlib import Path
except ImportError:  # pragma: no cover
    raise


class TestDerivationBackfillsMissingRegimenRoles(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "authoring_journey.sqlite3"
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _commit(self, project_id: str, picos_payload: dict):
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                actor="medical_manager_test",
                idempotency_key=f"create-{project_id}",
            ),
        )
        framing = _complete_framing()
        framing.structured_design.randomization_mode = "randomized"
        framing.structured_design.blinding_mode = "double_blind"
        framing.structured_design.comparator_type = "placebo"
        framing_preview = self.service.impact_preview(
            project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=created.revision,
                stage="framing",
                framing=framing,
            ),
        )
        framed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=created.revision,
                stage="framing",
                framing=framing,
                impact_preview_id=framing_preview.preview_id,
                actor="medical_manager_test",
                idempotency_key=f"commit-framing-{project_id}",
            ),
        )
        picos = type(_complete_picos()).model_validate(picos_payload)
        picos_preview = self.service.impact_preview(
            project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=picos,
            ),
        )
        return self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=picos,
                impact_preview_id=picos_preview.preview_id,
                actor="medical_manager_test",
                idempotency_key=f"commit-picos-{project_id}",
            ),
        )

    def test_structured_placebo_only_rules_get_ip_backfilled_from_legacy_text(self):
        payload = _complete_picos().model_dump(mode="json")
        payload["intervention_rules"] = {
            "schema_version": "medical_writing_intervention_rules_v1",
            "authority": "structured",
            "ip_regimens": [
                {
                    "regimen_id": "reg-placebo-only",
                    "product_name": "安慰剂",
                    "product_role": "placebo",
                    "dose_and_frequency": "匹配安慰剂，每4周一次。",
                }
            ],
        }
        committed = self._commit("proj_derivation_backfill_ip", payload)
        regimens = committed.picos.intervention_rules.ip_regimens
        roles = {row.product_role for row in regimens}
        self.assertIn(
            "investigational_product",
            roles,
            "missing IP regimen must be backfilled from the filled legacy dose text",
        )
        ip_rows = [
            row
            for row in regimens
            if row.product_role == "investigational_product"
        ]
        self.assertEqual(1, len(ip_rows))
        self.assertEqual("每4周给药一次，持续24周。", ip_rows[0].dose_and_frequency)
        placebo_rows = [
            row for row in regimens if row.product_role == "placebo"
        ]
        self.assertEqual(1, len(placebo_rows))
        self.assertEqual("reg-placebo-only", placebo_rows[0].regimen_id)

    def test_fully_populated_structured_rules_are_never_touched(self):
        payload = _complete_picos().model_dump(mode="json")
        payload["intervention_rules"] = {
            "schema_version": "medical_writing_intervention_rules_v1",
            "authority": "structured",
            "ip_regimens": [
                {
                    "regimen_id": "reg-user-ip",
                    "product_name": "SMOKE-r2-2",
                    "product_role": "investigational_product",
                    "dose_and_frequency": "口服每日一次。",
                },
                {
                    "regimen_id": "reg-user-placebo",
                    "product_name": "安慰剂",
                    "product_role": "placebo",
                    "dose_and_frequency": "匹配安慰剂。",
                },
            ],
        }
        committed = self._commit("proj_derivation_backfill_full", payload)
        regimens = committed.picos.intervention_rules.ip_regimens
        self.assertEqual(
            ["reg-user-ip", "reg-user-placebo"],
            [row.regimen_id for row in regimens],
        )


if __name__ == "__main__":
    unittest.main()
