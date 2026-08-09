from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Callable, Dict, Tuple

from packages.contracts.workbench_contracts import AiTaskSourceRef

from .eligibility_ai_review import EligibilityAiCriterion
from .eligibility_artifact_store import (
    EligibilityArtifactMetadata,
    EligibilityArtifactStore,
)
from .eligibility_protocol_rules import eligibility_criterion_text_hash
from .sqlite_runtime_store import SqliteRuntimeStore


PROMPT_VERSION = "eligibility_rule_review_v0_1"
ALLOWED_ARTIFACT_SCHEMAS = {
    "eligibility_ocr_artifact_v1",
    "eligibility_pdf_text_artifact_v1",
}
MAX_EVIDENCE_TEXT_CHARACTERS = 20_000


@dataclass(frozen=True)
class EligibilityAiCurrentContext:
    project_id: str
    subject_id: str
    subject_token: str
    rule_revision: str
    subject_source_revision: str
    criteria: Tuple[EligibilityAiCriterion, ...]


@dataclass(frozen=True)
class EligibilityAiPacket:
    project_id: str
    subject_id: str
    subject_token: str
    rule_revision: str
    subject_source_revision: str
    criteria: Tuple[EligibilityAiCriterion, ...]
    evidence_sources: Tuple[AiTaskSourceRef, ...]
    packet_digest: str

    def audit_dict(self) -> Dict[str, object]:
        return {
            "project_id": self.project_id,
            "subject_id": self.subject_id,
            "subject_token": self.subject_token,
            "rule_revision": self.rule_revision,
            "subject_source_revision": self.subject_source_revision,
            "criterion_uids": [item.criterion_uid for item in self.criteria],
            "evidence_ids": [item.source_id for item in self.evidence_sources],
            "packet_digest": self.packet_digest,
        }


class EligibilityAiPacketBuilder:
    def __init__(
        self,
        store: SqliteRuntimeStore,
        artifact_store: EligibilityArtifactStore,
        current_context_loader: Callable[[str, str], EligibilityAiCurrentContext],
    ) -> None:
        self.store = store
        self.artifact_store = artifact_store
        self.current_context_loader = current_context_loader

    def build(self, project_id: str, subject_id: str) -> EligibilityAiPacket:
        context = self.current_context_loader(project_id, subject_id)
        if context.project_id != project_id or context.subject_id != subject_id:
            raise ValueError("eligibility AI current-context identity mismatch")
        if not context.criteria:
            raise ValueError("eligibility AI current context has no criteria")

        bindings = self.store.eligibility_ai_evidence_artifact_bindings(
            project_id=context.project_id,
            subject_id=context.subject_id,
            subject_source_revision=context.subject_source_revision,
        )
        evidence_sources = tuple(
            self._source_ref(context.project_id, row) for row in bindings
        )
        evidence_ids = [source.source_id for source in evidence_sources]
        self.store.validate_eligibility_ai_inputs(
            project_id=context.project_id,
            subject_id=context.subject_id,
            rule_revision=context.rule_revision,
            subject_source_revision=context.subject_source_revision,
            criteria=[
                {
                    "criterion_uid": criterion.criterion_uid,
                    "criterion_kind": criterion.criterion_kind.value,
                    "source_locator": criterion.source_locator,
                    "normalized_text_hash": eligibility_criterion_text_hash(
                        criterion.text
                    ),
                    "display_order": criterion.display_order,
                }
                for criterion in context.criteria
            ],
            evidence_ids=evidence_ids,
        )
        processing_state = self.store.eligibility_ai_source_unit_contract_state(
            project_id=context.project_id,
            subject_id=context.subject_id,
            subject_source_revision=context.subject_source_revision,
        )
        if processing_state != "completed":
            raise ValueError(
                "eligibility AI packet requires server-verified completed evidence processing"
            )

        digest_payload = {
            "project_id": context.project_id,
            "subject_id": context.subject_id,
            "subject_token": context.subject_token,
            "rule_revision": context.rule_revision,
            "subject_source_revision": context.subject_source_revision,
            "prompt_version": PROMPT_VERSION,
            "criteria": [
                {
                    "criterion_uid": item.criterion_uid,
                    "criterion_kind": item.criterion_kind.value,
                    "source_locator": item.source_locator,
                    "display_order": item.display_order,
                    "text_hash": eligibility_criterion_text_hash(item.text),
                }
                for item in context.criteria
            ],
            "evidence": [
                {
                    "evidence_id": item.source_id,
                    "locator": item.locator,
                    "text_hash": _text_hash(item.text_preview),
                }
                for item in evidence_sources
            ],
        }
        packet_digest = "eligpacket_" + sha256(
            _canonical_json(digest_payload).encode("utf-8")
        ).hexdigest()
        return EligibilityAiPacket(
            project_id=context.project_id,
            subject_id=context.subject_id,
            subject_token=context.subject_token,
            rule_revision=context.rule_revision,
            subject_source_revision=context.subject_source_revision,
            criteria=context.criteria,
            evidence_sources=evidence_sources,
            packet_digest=packet_digest,
        )

    def _source_ref(self, project_id: str, binding: Dict[str, object]) -> AiTaskSourceRef:
        metadata = EligibilityArtifactMetadata(
            storage_key=str(binding["storage_key"]),
            content_hash=str(binding["content_hash"]),
            size_bytes=int(binding["size_bytes"]),
            media_type=str(binding["media_type"]),
        )
        body = self.artifact_store.read(metadata)
        payload = _strict_json_object(body)
        schema_version = payload.get("schema_version")
        if schema_version not in ALLOWED_ARTIFACT_SCHEMAS:
            raise ValueError("eligibility AI evidence artifact schema is not allowed")
        if payload.get("extraction_revision") != binding["extraction_revision"]:
            raise ValueError("eligibility AI evidence extraction revision mismatch")
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("eligibility AI evidence artifact text is empty")
        if len(text) > MAX_EVIDENCE_TEXT_CHARACTERS:
            raise ValueError("eligibility AI evidence artifact text exceeds the bounded limit")
        locator = _canonical_json(binding["locator"])
        return AiTaskSourceRef(
            source_id=str(binding["evidence_id"]),
            source_type="eligibility_evidence_span",
            title=str(binding["evidence_id"]),
            locator=locator,
            text_preview=text,
            project_id=project_id,
            module="eligibility_review",
            source_entry_id=str(binding["artifact_id"]),
        )


def _strict_json_object(body: bytes) -> Dict[str, object]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("eligibility AI evidence artifact must be UTF-8 JSON") from exc

    def pairs(values):
        output = {}
        for key, value in values:
            if key in output:
                raise ValueError("eligibility AI evidence artifact has duplicate JSON keys")
            output[key] = value
        return output

    try:
        payload = json.loads(text, object_pairs_hook=pairs)
    except json.JSONDecodeError as exc:
        raise ValueError("eligibility AI evidence artifact is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("eligibility AI evidence artifact must be a JSON object")
    return payload


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text_hash(text: str) -> str:
    return sha256(" ".join(text.split()).encode("utf-8")).hexdigest()
