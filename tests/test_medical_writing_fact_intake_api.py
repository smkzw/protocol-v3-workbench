"""End-to-end API tests for the conversational fact-intake endpoints.

These exercise the real FastAPI app with a fake DeepSeek V4 Pro provider
injected via the service's ``provider_factory``. They prove the idempotent
turn/apply endpoints work through the HTTP layer with optimistic revision
checks and field-path allowlist enforcement.
"""

from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from services.api.app import main as app_main


class _FakeProvider:
    provider_name = "fake_deepseek"
    model_name = "deepseek-v4-pro"

    def __init__(self, response: dict):
        self._response = response
        self.calls = 0

    def run(self, envelope):
        self.calls += 1
        return self._response


def _valid_response() -> dict:
    return {
        "response_text": "已记录类风湿关节炎 II 期信息。",
        "proposals": [
            {
                "proposal_id": "p_indication",
                "field_path": "framing.indication",
                "fact_kind": "user_stated",
                "value": "类风湿关节炎",
                "rationale": "用户明述",
                "confidence": "high",
            },
            {
                "proposal_id": "p_phase",
                "field_path": "framing.study_phase",
                "fact_kind": "user_stated",
                "value": "II期",
                "rationale": "用户明述",
                "confidence": "high",
            },
            {
                "proposal_id": "p_product",
                "field_path": "framing.investigational_product",
                "fact_kind": "user_stated",
                "value": "CMP-001",
                "rationale": "用户给出代号",
                "confidence": "high",
            },
            {
                "proposal_id": "p_dose",
                "field_path": "high_impact_missing.first_in_human_starting_dose",
                "fact_kind": "unknown",
                "value": "",
                "rationale": "用户未给，IB 未提供",
                "confidence": "unknown",
            },
        ],
        "questions": ["是否已有 IB？"],
        "high_impact_missing": ["high_impact_missing.first_in_human_starting_dose"],
        "uncertainties": [],
        "needs_medical_confirmation": True,
    }


class FactIntakeEndpointsTests(unittest.TestCase):
    def setUp(self):
        self._original_factory = app_main.medical_writing_fact_intake_service.provider_factory
        self.client = TestClient(app_main.app)
        self.suffix = os.urandom(4).hex()
        bootstrap = self.client.post(
            "/api/projects",
            json={
                "project_name": "E2E Fact Intake",
                "protocol_id": f"E2E-FI-{self.suffix}",
                "protocol_version": "1.0",
                "indication": "Rheumatoid Arthritis",
                "study_phase": "PHASE2",
                "product_name": "CMP-001",
                "entry_mode": "from_zero",
                "actor": "medical_manager",
                "idempotency_key": f"bootstrap-{self.suffix}",
            },
        )
        self.assertEqual(201, bootstrap.status_code, bootstrap.text)
        self.project_id = bootstrap.json()["project"]["project_id"]
        self.base = (
            f"/api/projects/{self.project_id}/medical-writing/fact-intake/study_framing"
        )

    def tearDown(self):
        app_main.medical_writing_fact_intake_service.provider_factory = (
            self._original_factory
        )

    def _install_fake(self, response: dict) -> _FakeProvider:
        provider = _FakeProvider(response)
        app_main.medical_writing_fact_intake_service.provider_factory = lambda: provider
        return provider

    def test_full_flow_create_turn_apply_is_idempotent(self):
        provider = self._install_fake(_valid_response())

        create = self.client.post(
            self.base,
            json={
                "scope": "study_framing",
                "actor": "medical_manager",
                "idempotency_key": "create-1",
            },
        )
        self.assertEqual(201, create.status_code, create.text)
        conversation_id = create.json()["conversation_id"]
        self.assertEqual(1, create.json()["revision"])
        self.assertEqual(
            {
                "framing.indication": "Rheumatoid Arthritis",
                "framing.study_phase": "II期",
                "framing.investigational_product": "CMP-001",
            },
            create.json()["confirmed_field_values"],
        )
        self.assertEqual("sufficient_for_research", create.json()["status"])

        # duplicate create is idempotent (same conversation, still 201)
        dup = self.client.post(
            self.base,
            json={
                "scope": "study_framing",
                "actor": "medical_manager",
                "idempotency_key": "create-1",
            },
        )
        self.assertEqual(201, dup.status_code)
        self.assertEqual(conversation_id, dup.json()["conversation_id"])

        # turn without IB: facts recorded, research stays open, writing blocked
        turn = self.client.post(
            self.base + "/turns",
            json={
                "expected_revision": 1,
                "message_text": "类风湿关节炎 II 期，药物 CMP-001",
                "ib_status": "not_provided",
                "actor": "medical_manager",
                "idempotency_key": "turn-1",
            },
        )
        self.assertEqual(200, turn.status_code, turn.text)
        body = turn.json()
        self.assertEqual(2, body["conversation"]["revision"])
        self.assertEqual(4, len(body["proposals"]))
        self.assertEqual(
            "high_impact_missing.first_in_human_starting_dose",
            body["conversation"]["unresolved_high_impact_fields"][0],
        )
        self.assertIn(
            "intervention_sections.starting_dose",
            body["conversation"]["locally_blocked_clauses"],
        )

        # idempotent replay: same revision, no extra provider call
        calls_before = provider.calls
        replay = self.client.post(
            self.base + "/turns",
            json={
                "expected_revision": 1,
                "message_text": "类风湿关节炎 II 期，药物 CMP-001",
                "ib_status": "not_provided",
                "actor": "medical_manager",
                "idempotency_key": "turn-1",
            },
        )
        self.assertEqual(200, replay.status_code)
        self.assertEqual(
            body["conversation"]["revision"],
            replay.json()["conversation"]["revision"],
        )
        self.assertEqual(calls_before, provider.calls)

        # stale expected_revision is rejected with 409
        stale = self.client.post(
            self.base + "/turns",
            json={
                "expected_revision": 1,
                "message_text": "another message",
                "ib_status": "not_provided",
                "actor": "medical_manager",
                "idempotency_key": "turn-2",
            },
        )
        self.assertEqual(409, stale.status_code)

        # apply adopt: confirms facts, status promotes to sufficient_for_research
        apply = self.client.post(
            self.base + "/apply",
            json={
                "expected_revision": 2,
                "decisions": [
                    {"proposal_id": "p_indication", "action": "adopt"},
                    {"proposal_id": "p_phase", "action": "adopt"},
                    {"proposal_id": "p_product", "action": "adopt"},
                    {"proposal_id": "p_dose", "action": "reject", "note": "待 IB"},
                ],
                "actor": "medical_manager",
                "idempotency_key": "apply-1",
            },
        )
        self.assertEqual(200, apply.status_code, apply.text)
        applied = apply.json()
        self.assertEqual(3, applied["conversation"]["revision"])
        self.assertEqual(
            "sufficient_for_research", applied["conversation"]["status"]
        )
        self.assertEqual(
            "类风湿关节炎",
            applied["conversation"]["confirmed_field_values"]["framing.indication"],
        )
        # writing remains locally blocked because the dose is still unknown
        self.assertIn(
            "intervention_sections.starting_dose",
            applied["conversation"]["locally_blocked_clauses"],
        )

        # A medical manager's first decision is final; a fresh request cannot
        # re-reject a proposal whose adopted value is already confirmed.
        redecide = self.client.post(
            self.base + "/apply",
            json={
                "expected_revision": 3,
                "decisions": [
                    {"proposal_id": "p_indication", "action": "reject"},
                ],
                "actor": "medical_manager",
                "idempotency_key": "apply-redecide",
            },
        )
        self.assertEqual(409, redecide.status_code, redecide.text)
        self.assertIn("decision is final", redecide.text)

    def test_forbidden_field_path_rejected_at_http_layer(self):
        bad = {
            "response_text": "x",
            "proposals": [
                {
                    "proposal_id": "b1",
                    "field_path": "framing.secret_field",
                    "fact_kind": "user_stated",
                    "value": "x",
                    "rationale": "x",
                }
            ],
            "questions": [],
            "high_impact_missing": [],
            "uncertainties": [],
            "needs_medical_confirmation": True,
        }
        self._install_fake(bad)
        self.client.post(
            self.base,
            json={
                "scope": "study_framing",
                "actor": "medical_manager",
                "idempotency_key": "create-1",
            },
        )
        turn = self.client.post(
            self.base + "/turns",
            json={
                "expected_revision": 1,
                "message_text": "trick",
                "ib_status": "not_provided",
                "actor": "medical_manager",
                "idempotency_key": "turn-bad",
            },
        )
        self.assertEqual(422, turn.status_code)

    def test_fabricated_high_impact_value_rejected_at_http_layer(self):
        bad = {
            "response_text": "x",
            "proposals": [
                {
                    "proposal_id": "b1",
                    "field_path": "high_impact_missing.first_in_human_starting_dose",
                    "fact_kind": "ai_inferred",
                    "value": "3 mg/kg",
                    "rationale": "from label",
                    "confidence": "medium",
                }
            ],
            "questions": [],
            "high_impact_missing": [],
            "uncertainties": [],
            "needs_medical_confirmation": True,
        }
        self._install_fake(bad)
        self.client.post(
            self.base,
            json={
                "scope": "study_framing",
                "actor": "medical_manager",
                "idempotency_key": "create-1",
            },
        )
        turn = self.client.post(
            self.base + "/turns",
            json={
                "expected_revision": 1,
                "message_text": "trick",
                "ib_status": "not_provided",
                "actor": "medical_manager",
                "idempotency_key": "turn-bad",
            },
        )
        self.assertEqual(422, turn.status_code)

    def test_get_allow_missing_returns_not_available(self):
        # use a fresh project so no conversation exists yet
        suffix = os.urandom(4).hex()
        bootstrap = self.client.post(
            "/api/projects",
            json={
                "project_name": "E2E Fact Intake Missing",
                "protocol_id": f"E2E-FIM-{suffix}",
                "protocol_version": "1.0",
                "indication": "Rheumatoid Arthritis",
                "study_phase": "PHASE2",
                "product_name": "CMP-002",
                "entry_mode": "from_zero",
                "actor": "medical_manager",
                "idempotency_key": f"bootstrap-missing-{suffix}",
            },
        )
        pid = bootstrap.json()["project"]["project_id"]
        r = self.client.get(
            f"/api/projects/{pid}/medical-writing/fact-intake/study_framing",
            params={"allow_missing": "true"},
        )
        self.assertEqual(200, r.status_code)
        self.assertFalse(r.json()["available"])


if __name__ == "__main__":
    unittest.main()
