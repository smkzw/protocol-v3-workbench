from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.api.app.main import app


class EligibilityProtocolRulesApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_d001_and_my009_return_project_scoped_protocol_rules(self) -> None:
        expected = {
            "proj_d001": (6, 30, "IN-06", "EX-30"),
            "proj_my009_uc": (10, 24, "IN-10", "EX-24"),
        }
        payloads = {}
        for project_id, (in_count, ex_count, last_in, last_ex) in expected.items():
            with self.subTest(project_id=project_id):
                response = self.client.get(
                    f"/api/projects/{project_id}/eligibility/protocol-rules"
                )
                self.assertEqual(200, response.status_code)
                payload = response.json()
                payloads[project_id] = payload
                self.assertEqual(project_id, payload["project_id"])
                self.assertEqual(in_count, payload["counts"]["inclusion"])
                self.assertEqual(ex_count, payload["counts"]["exclusion"])
                self.assertEqual(last_in, payload["inclusion"]["rules"][-1]["rule_id"])
                self.assertEqual(last_ex, payload["exclusion"]["rules"][-1]["rule_id"])

                serialized = response.text
                self.assertNotIn("/Users/", serialized)
                self.assertNotIn("protocol_path", serialized)
                self.assertNotIn("全量-入组", serialized)
                self.assertNotIn("EVF审核", serialized)

        self.assertNotEqual(
            payloads["proj_d001"]["source_entry"],
            payloads["proj_my009_uc"]["source_entry"],
        )
        for payload in payloads.values():
            serialized = str(payload)
            self.assertNotIn("content_hash", serialized)
            self.assertNotIn("word_numbering", serialized)

    def test_alias_is_ingress_only_and_unknown_project_fails_closed(self) -> None:
        alias_response = self.client.get(
            "/api/projects/d001_raw_intake/eligibility/protocol-rules"
        )
        self.assertEqual(200, alias_response.status_code)
        self.assertEqual("proj_d001", alias_response.json()["project_id"])

        unknown = self.client.get(
            "/api/projects/proj_unknown/eligibility/protocol-rules"
        )
        self.assertEqual(404, unknown.status_code)

    def test_source_read_failure_does_not_expose_local_path(self) -> None:
        with patch(
            "services.api.app.eligibility.protocol_rule_service.rules_for_project",
            side_effect=FileNotFoundError(
                "/Users/private/sensitive-project/protocol.docx"
            ),
        ):
            response = self.client.get(
                "/api/projects/proj_d001/eligibility/protocol-rules"
            )

        self.assertEqual(422, response.status_code)
        self.assertNotIn("/Users/", response.text)
        self.assertNotIn("sensitive-project", response.text)
        self.assertIn("原始方案无法读取", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
