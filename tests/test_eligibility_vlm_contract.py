from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from packages.contracts.workbench_contracts.models import (
    EligibilityEvidenceVisualQcRequest,
    EligibilityVlmDescriptor,
    EligibilityVlmGatewayOutcome,
    EligibilityVlmMediaClass,
)
from services.api.app.eligibility_vlm_contract import (
    VlmDescriptorValidationError,
    derive_vlm_gateway_outcome,
    parse_vlm_descriptor,
)


def descriptor_payload(**overrides):
    payload = {
        "schema_version": "eligibility_visual_descriptor_v1",
        "media_class": "document_page",
        "primary_document_type": "medical_record",
        "capture_quality": {
            "overall": "adequate_for_human_qc",
            "flags": ["none"],
        },
        "orientation": "upright",
        "requires_human_attention": ["none"],
    }
    payload.update(overrides)
    return payload


class EligibilityVlmContractTests(unittest.TestCase):
    def parse(self, payload):
        return parse_vlm_descriptor(json.dumps(payload, separators=(",", ":")))

    def test_valid_document_descriptor_is_not_a_qc_pass(self):
        descriptor = self.parse(descriptor_payload())
        self.assertEqual("descriptor_valid", derive_vlm_gateway_outcome(descriptor).value)
        self.assertFalse(hasattr(descriptor, "status"))

    def test_generated_json_schema_is_closed_and_contains_individual_flag_enums(self):
        schema = EligibilityVlmDescriptor.model_json_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertNotIn("status", schema["properties"])
        self.assertNotIn("body_region", schema["properties"])
        self.assertNotIn("laterality", schema["properties"])
        self.assertNotIn("pairing", schema["properties"])
        capture = schema["$defs"]["EligibilityVlmCaptureQuality"]
        self.assertFalse(capture["additionalProperties"])
        flag_ref = capture["properties"]["flags"]["items"]["$ref"]
        flag_enum = schema["$defs"][flag_ref.rsplit("/", 1)[-1]]["enum"]
        self.assertIn("none", flag_enum)
        self.assertIn("blur", flag_enum)
        self.assertNotIn("none | blur", flag_enum)

    def test_identifier_alert_requires_manual_review_without_transcription(self):
        descriptor = self.parse(
            descriptor_payload(
                requires_human_attention=["possible_identifier_visible"]
            )
        )
        self.assertEqual(
            "manual_review_required", derive_vlm_gateway_outcome(descriptor).value
        )
        self.assertNotIn("name", descriptor.model_dump_json())

    def test_non_document_cannot_claim_document_or_orientation(self):
        payload = descriptor_payload(
            media_class="clinical_photo",
            primary_document_type="medical_record",
            orientation="upright",
        )
        with self.assertRaisesRegex(
            VlmDescriptorValidationError, "schema_or_policy_violation"
        ):
            self.parse(payload)

    def test_limited_quality_requires_concrete_ordered_flags_and_attention(self):
        valid = descriptor_payload(
            capture_quality={"overall": "limited", "flags": ["blur", "glare"]},
            requires_human_attention=["capture_quality_limited"],
        )
        descriptor = self.parse(valid)
        self.assertEqual(
            "manual_review_required", derive_vlm_gateway_outcome(descriptor).value
        )
        for flags in (["none", "blur"], ["glare", "blur"], ["blur", "blur"]):
            invalid = dict(valid)
            invalid["capture_quality"] = {"overall": "limited", "flags": flags}
            with self.assertRaises(VlmDescriptorValidationError):
                self.parse(invalid)

    def test_unknown_media_requires_unsupported_attention(self):
        payload = descriptor_payload(
            media_class="unknown",
            primary_document_type="not_applicable",
            orientation="not_applicable",
        )
        with self.assertRaises(VlmDescriptorValidationError):
            self.parse(payload)
        payload["requires_human_attention"] = ["unsupported_content"]
        descriptor = self.parse(payload)
        self.assertEqual(
            "manual_review_required", derive_vlm_gateway_outcome(descriptor).value
        )

    def test_status_clinical_inference_and_removed_fields_fail_closed(self):
        for key, value in (
            ("status", "described"),
            ("diagnosis", "eczema"),
            ("body_region", "trunk_anterior"),
            ("laterality", "left"),
            ("pairing", "before_after_pair"),
        ):
            payload = descriptor_payload()
            payload[key] = value
            with self.assertRaises(VlmDescriptorValidationError):
                self.parse(payload)

    def test_prose_markdown_multiple_objects_and_duplicate_keys_fail_closed(self):
        valid = json.dumps(descriptor_payload(), separators=(",", ":"))
        invalid_outputs = [
            f"result: {valid}",
            f"```json\n{valid}\n```",
            valid + valid,
            valid + "[1,2]",
            "[1,2]",
            valid[:-1] + ',"media_class":"unknown"}',
        ]
        for raw in invalid_outputs:
            with self.assertRaises(VlmDescriptorValidationError):
                parse_vlm_descriptor(raw)

    def test_nested_duplicate_key_and_wrong_schema_version_fail_closed(self):
        valid = json.dumps(descriptor_payload(), separators=(",", ":"))
        nested_duplicate = valid.replace(
            '"flags":["none"]', '"flags":["blur"],"flags":["none"]'
        )
        with self.assertRaisesRegex(VlmDescriptorValidationError, "duplicate_key"):
            parse_vlm_descriptor(nested_duplicate)
        payload = descriptor_payload(schema_version="eligibility_visual_descriptor_v0_1")
        with self.assertRaises(VlmDescriptorValidationError):
            self.parse(payload)

    def test_outcome_revalidates_constructed_model_and_cannot_be_visual_qc_result(self):
        valid = self.parse(descriptor_payload())
        unsafe = valid.model_copy(
            update={"media_class": EligibilityVlmMediaClass.CLINICAL_PHOTO}
        )
        with self.assertRaisesRegex(VlmDescriptorValidationError, "not_validated"):
            derive_vlm_gateway_outcome(unsafe)
        with self.assertRaises(ValidationError):
            EligibilityEvidenceVisualQcRequest.model_validate(
                {
                    "expected_qc_revision": 0,
                    "expected_source_revision": "source-v1",
                    "expected_extraction_revision": "extract-v1",
                    "idempotency_key": "key-1",
                    "result": EligibilityVlmGatewayOutcome.DESCRIPTOR_VALID.value,
                    "reason_code": "fixture",
                    "user_reason": "fixture",
                    "policy_version": "visual-qc-policy-v1",
                    "actor": "reviewer",
                }
            )

    def test_image_instruction_cannot_become_an_extra_output_field(self):
        payload = descriptor_payload()
        payload["ignore_previous_instructions"] = True
        with self.assertRaises(VlmDescriptorValidationError):
            self.parse(payload)


if __name__ == "__main__":
    unittest.main()
