from __future__ import annotations

import json
from typing import Dict, Iterable, Tuple

from pydantic import ValidationError

from packages.contracts.workbench_contracts.models import (
    EligibilityVlmCaptureQualityFlag,
    EligibilityVlmCaptureQualityOverall,
    EligibilityVlmDescriptor,
    EligibilityVlmGatewayOutcome,
    EligibilityVlmHumanAttention,
    EligibilityVlmMediaClass,
)


class VlmDescriptorValidationError(ValueError):
    """Sanitized failure raised for any untrusted model-output violation."""


def _reject_duplicate_keys(pairs: Iterable[Tuple[str, object]]) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise VlmDescriptorValidationError("vlm_output_duplicate_key")
        result[key] = value
    return result


def parse_vlm_descriptor(raw_output: str) -> EligibilityVlmDescriptor:
    if not isinstance(raw_output, str):
        raise VlmDescriptorValidationError("vlm_output_not_text")
    stripped = raw_output.strip()
    if not stripped or not stripped.startswith("{") or not stripped.endswith("}"):
        raise VlmDescriptorValidationError("vlm_output_not_single_json_object")
    decoder = json.JSONDecoder(object_pairs_hook=_reject_duplicate_keys)
    try:
        payload, end_index = decoder.raw_decode(stripped)
    except VlmDescriptorValidationError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError, RecursionError):
        raise VlmDescriptorValidationError("vlm_output_invalid_json") from None
    if stripped[end_index:].strip():
        raise VlmDescriptorValidationError("vlm_output_not_single_json_object")
    if not isinstance(payload, dict):
        raise VlmDescriptorValidationError("vlm_output_not_json_object")
    try:
        return EligibilityVlmDescriptor.model_validate(payload)
    except ValidationError:
        raise VlmDescriptorValidationError("vlm_output_schema_or_policy_violation") from None


def derive_vlm_gateway_outcome(
    descriptor: EligibilityVlmDescriptor,
) -> EligibilityVlmGatewayOutcome:
    try:
        descriptor = EligibilityVlmDescriptor.model_validate(
            descriptor.model_dump(mode="json")
        )
    except (AttributeError, ValidationError):
        raise VlmDescriptorValidationError("vlm_descriptor_not_validated") from None
    if descriptor.media_class == EligibilityVlmMediaClass.UNKNOWN:
        return EligibilityVlmGatewayOutcome.MANUAL_REVIEW_REQUIRED
    if descriptor.capture_quality.overall != EligibilityVlmCaptureQualityOverall.ADEQUATE_FOR_HUMAN_QC:
        return EligibilityVlmGatewayOutcome.MANUAL_REVIEW_REQUIRED
    if descriptor.capture_quality.flags != [EligibilityVlmCaptureQualityFlag.NONE]:
        return EligibilityVlmGatewayOutcome.MANUAL_REVIEW_REQUIRED
    if descriptor.requires_human_attention != [EligibilityVlmHumanAttention.NONE]:
        return EligibilityVlmGatewayOutcome.MANUAL_REVIEW_REQUIRED
    return EligibilityVlmGatewayOutcome.DESCRIPTOR_VALID
