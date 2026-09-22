"""Project-level medical-writing full-draft candidate workflow.

The full draft is deliberately separate from the paragraph revision thread:
it is a bounded, source-bound AI candidate artifact.  Generation never mutates
working copies; explicit adoption performs per-section CAS saves with stable
idempotency keys.  The durable job row stores only a locator and digest while
the candidate JSON remains in the runtime artifact directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, get_args, get_origin

from packages.contracts.workbench_contracts import (
    AiTaskRequest,
    AiTaskRunStatus,
    AiTaskSourceRef,
    DurableJobCreateRequest,
    DurableJobProgressPayload,
    MedicalWritingPicosDefinition,
    MedicalWritingStudyFraming,
    MedicalWritingWorkingCopySaveRequest,
)

from .ai_gateway import AiTaskType
from .medical_writing_durable_jobs import (
    DurableJobExecutor,
    DurableJobResult,
    DurableJobStore,
)
from .medical_writing_content_quality import (
    DRAFTING_PROCESS_VOCABULARY_RE,
    INTERNAL_TRANSPORT_VOCABULARY_RE,
    iter_unresolved_draft_markers,
)
from .medical_writing_corpus_policy import CORPUS_GENERALIZATION_PROMPT_RULES
from .medical_writing_repository import RuntimeStoreError, StaleRuntimeStateError
from .medical_writing_authoring_prefill import SUPPORTED_ADOPT_PATHS
from .medical_writing_protocol_template import company_template_semantic_node_map


FULL_DRAFT_JOB_TYPE = "protocol_full_draft"
FULL_DRAFT_PROMPT_VERSION = "protocol_full_draft_v0_10"
FULL_DRAFT_ARTIFACT_SCHEMA = "protocol_full_draft_artifact_v10"
FULL_DRAFT_CHUNK_ARTIFACT_SCHEMA = "protocol_full_draft_chunk_v10"
FULL_DRAFT_DESCRIPTOR_VERSION = "protocol_full_draft_descriptor_v12"
LEGACY_FULL_DRAFT_ARTIFACT_SCHEMAS = {
    "protocol_full_draft_artifact_v3",
    "protocol_full_draft_artifact_v4",
    "protocol_full_draft_artifact_v5",
    "protocol_full_draft_artifact_v6",
    "protocol_full_draft_artifact_v7",
    "protocol_full_draft_artifact_v8",
    "protocol_full_draft_artifact_v9",
}
FULL_DRAFT_REVIEW_POLICY_VERSION = "protocol_full_draft_review_v0_2"
FULL_DRAFT_MINIMUM_BODY_CHARS = 80
# Four sections keep max-reasoning responses within the provider's bounded
# final-output budget.  An eight-section v0.4 batch was observed to end before
# its outer JSON object closed, leaving only a nested evidence object parsable.
FULL_DRAFT_CHUNK_SIZE = 4
FULL_DRAFT_MAX_OUTPUT_TOKENS = 65_536
# design.* paths whose authoritative mapping needs structured (dict) input; a
# prose decision answer would be silently dropped there, so such decisions
# fail closed instead of persisting nothing.
_DECISION_STRUCTURED_DESIGN_PATHS = frozenset(
    {"design.src_dmc", "design.phase1_parts", "design.arms_or_cohorts"}
)
FULL_DRAFT_DECISION_FACT_PATHS = tuple(
    sorted(
        {
            "picos.exploratory_endpoints",
            "picos.exploratory_objectives",
        }
        & SUPPORTED_ADOPT_PATHS
        - _DECISION_STRUCTURED_DESIGN_PATHS
    )
)

# A full-draft card may fill one whole, currently unconfirmed study-definition
# field.  It may not use a broad confirmed field as a convenient bucket for an
# unrelated operational choice.  Each field also has one owning section so a
# single user click cannot be duplicated across the document.
_DECISION_PATH_HEADING_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "picos.allowed_concomitant_rules": (
        re.compile(r"^允许的合并用药/治疗$"),
        re.compile(r"^合并用药/治疗$"),
    ),
    "picos.prohibited_concomitant_rules": (
        re.compile(r"^禁止的合并用药/治疗$"),
        re.compile(r"^合并用药/治疗$"),
    ),
    "picos.required_background_rules": (
        re.compile(r"^合并用药/治疗$"),
        re.compile(r"背景治疗"),
    ),
    "picos.assessment_timing_restrictions": (
        re.compile(r"^安全性评估$"),
        re.compile(r"^研究流程和评估$"),
    ),
    "picos.exploratory_objectives": (
        re.compile(r"探索性目的"),
        re.compile(r"^研究目的和终点$"),
    ),
    "picos.exploratory_endpoints": (
        re.compile(r"探索性终点"),
        re.compile(r"^研究目的和终点$"),
    ),
}

_PLACEHOLDER_RE = re.compile(
    r"(?:^|[\s，。；：])(?:待补充|待确认|待定|TBD|TODO|不适用|无适用内容|由方案规定|见方案规定)(?:$|[\s，。；：])",
    re.IGNORECASE,
)
_REQUIRED_REVIEW_HEADING_RE = re.compile(
    r"^(?:方案概要|研究目的和终点|主要目的和主要终点|主要终点.*|研究设计|总体设计|"
    r"确证性设计与假设依据|随机化|盲法与揭盲|研究人群|研究人群选择及依据|"
    r"入选标准|排除标准|统计分析|(?:主要)?估计目标.*|样本量.*|非劣效.*|"
    r"期中分析.*|多重性.*|剂量选择.*|对照选择.*|研究药物相关风险|"
    r"妊娠事件(?:的报告与随访)?|避孕的规定与方法|安全信息报告途径)$",
    re.IGNORECASE,
)
_REQUIRED_REVIEW_CONTENT_RE = re.compile(
    r"主要终点|估计目标|伴发事件|样本量|计划入组|非劣效界值|期中分析|alpha|α|"
    r"剂量选择|对照选择|核心人群",
    re.IGNORECASE,
)
_CORPUS_CONDUCT_RE = re.compile(
    r"避孕|妊娠.{0,24}(?:报告|随访|结局)|不良事件.{0,20}(?:是指|定义|记录|报告)|"
    r"严重不良事件.{0,30}(?:记录|报告)|剂量(?:调整|暂停|减量)|给药中断|永久停药|"
    r"合并用药|禁用药|限制用药|洗脱|救援治疗|IWRS|交互式网络应答|"
    r"侵入性操作|全分析集|符合方案集|安全性分析集",
    re.IGNORECASE,
)
_DESIGN_RESTATEMENT_SIGNALS = (
    re.compile(r"计划入组\s*\d+\s*例"),
    re.compile(r"\d+(?:\.\d+)?\s*mg", re.IGNORECASE),
    re.compile(r"主要终点"),
    re.compile(r"随机"),
    re.compile(r"双盲"),
)
_DESIGN_RESTATEMENT_ALLOWED_HEADING_RE = re.compile(
    r"方案概要|研究设计|研究目的和终点|主要目的和主要终点|样本量",
    re.IGNORECASE,
)
_CORPUS_SOURCE_TYPES = {
    "company_protocol_reference_corpus",
    "shared_protocol_reference_corpus",
    "shared_phase1_protocol_reference_corpus",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _body_blocks(blocks: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(block)
        for block in blocks
        if str(block.get("block_type") or "") == "paragraph"
        and str(block.get("block_id") or "").strip()
        and str(block.get("source_kind") or "") != "medical_writing_intervention_rules"
    ]


def _body_text(blocks: Iterable[Mapping[str, Any]]) -> str:
    return "\n".join(
        _text(block.get("text"))
        for block in _body_blocks(blocks)
        if _text(block.get("text"))
    ).strip()


def _is_substantive(text: str) -> bool:
    normalized = _text(text)
    return bool(normalized) and len(normalized) >= FULL_DRAFT_MINIMUM_BODY_CHARS and not _PLACEHOLDER_RE.search(normalized)


def _safe_project_path(project_id: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(project_id))
    return token[:120] or "project"


class MedicalWritingFullDraftService:
    """Composition-root service for durable full-draft jobs and adoption."""

    def __init__(
        self,
        service_resolver: Callable[[str], Any],
        artifact_root: Path,
    ) -> None:
        self.service_resolver = service_resolver
        self.artifact_root = Path(artifact_root).expanduser().resolve()

    def _service(self, project_id: str) -> Any:
        service = self.service_resolver(project_id)
        if service is None or not hasattr(service, "repo"):
            raise RuntimeStoreError("medical writing full-draft service is not configured")
        return service

    @staticmethod
    def _binding(repo: Any, project_id: str, document: Any) -> dict[str, Any]:
        resolver = getattr(repo, "authoritative_study_definition_binding", None)
        if callable(resolver):
            values = resolver(project_id)
            study_id, revision, digest = values
        else:
            study_id = str(getattr(document, "source_study_definition_id", "") or "")
            revision = getattr(document, "source_study_definition_revision", None)
            digest = str(getattr(document, "source_study_definition_sha256", "") or "")
        if any((study_id, revision is not None, digest)) and not all((study_id, revision is not None, digest)):
            raise RuntimeStoreError("当前研究设计绑定不完整，全文初稿已停止")
        return {
            "id": str(study_id or ""),
            "revision": int(revision) if revision is not None else None,
            "sha256": str(digest or ""),
        }

    def _working_copy_blocks(self, repo: Any, project_id: str, section: Any) -> tuple[int, list[dict[str, Any]]]:
        current = repo.working_copy(project_id, section.section_id)
        if current.revision >= 1:
            return int(current.revision), [dict(block) for block in current.content_blocks]
        return 0, [dict(block) for block in section.content_blocks]

    def _target_sections(
        self,
        service: Any,
        project_id: str,
        document: Any,
        *,
        section_ids: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        repo = service.repo
        scope = {
            _text(item) for item in (section_ids or ()) if _text(item)
        } or None
        targets: list[dict[str, Any]] = []
        semantic_nodes = company_template_semantic_node_map()
        for section in document.sections:
            if scope is not None and str(section.section_id) not in scope:
                continue
            if (
                section.applicability_status == "not_applicable"
                or section.applicability_render_action == "omit"
                or section.node_kind not in {"section", "appendix"}
            ):
                continue
            revision, blocks = self._working_copy_blocks(repo, project_id, section)
            writable = _body_blocks(blocks)
            if not writable:
                continue
            body = _body_text(writable)
            if _is_substantive(body):
                continue
            first = writable[0]
            targets.append(
                {
                    "section_id": str(section.section_id),
                    "section_number": str(section.section_number or ""),
                    "heading": str(section.heading or ""),
                    "node_kind": str(section.node_kind or "section"),
                    "template_node_id": str(section.template_node_id or ""),
                    "semantic_node_id": str(
                        semantic_nodes.get(str(section.template_node_id or ""), "")
                    ),
                    "body_block_id": str(first["block_id"]),
                    "expected_revision": revision,
                    "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    "body_text": body,
                }
            )
            if not targets[-1]["semantic_node_id"]:
                raise RuntimeStoreError(
                    f"章节缺少稳定语义节点映射：{section.section_id}"
                )
        return targets

    @staticmethod
    def _available_decision_paths(service: Any, project_id: str) -> set[str]:
        """Return only whole fields that are still awaiting confirmation.

        When a current authoring journey is available, a confirmed field is
        never offered to the chapter generator as a decision target.  This is
        the decisive guard against replacing an established estimand, visit
        strategy, safety endpoint set, or other study fact with a chapter-level
        operational answer.  Lightweight legacy test compositions without an
        authoring journey retain the small curated catalog.
        """
        journey_service = getattr(service, "authoring_journey_service", None)
        if journey_service is None or not journey_service.has_project(project_id):
            return set(FULL_DRAFT_DECISION_FACT_PATHS)
        journey = journey_service.get(project_id)
        definition = getattr(journey, "study_definition", None)
        states = getattr(definition, "field_states", None)
        if not isinstance(states, Mapping):
            return set()
        return {
            path
            for path in FULL_DRAFT_DECISION_FACT_PATHS
            if getattr(states.get(path), "status", "") in {"missing", "deferred"}
        }

    @staticmethod
    def _authoring_journey_binding(service: Any, project_id: str) -> dict[str, Any]:
        journey_service = getattr(service, "authoring_journey_service", None)
        if journey_service is None or not journey_service.has_project(project_id):
            return {}
        journey = journey_service.get(project_id)
        definition = getattr(journey, "study_definition", None)
        if definition is None:
            raise RuntimeStoreError("当前研究设计不存在，全文初稿已停止")
        return {
            "journey_id": str(journey.journey_id),
            "journey_revision": int(journey.revision),
            "study_definition_id": str(definition.definition_id),
            "study_definition_revision": int(definition.revision),
            "study_definition_sha256": str(definition.state_sha256),
            "framing": journey.framing.model_dump(mode="json"),
            "picos": journey.picos.model_dump(mode="json"),
        }

    @staticmethod
    def _decision_path_owners(
        targets: Iterable[Mapping[str, Any]],
        available_paths: Iterable[str],
    ) -> dict[str, str]:
        """Assign each writable decision field to one semantically named section."""
        target_list = list(targets)
        owners: dict[str, str] = {}
        for path in sorted(set(available_paths)):
            patterns = _DECISION_PATH_HEADING_PATTERNS.get(path, ())
            for pattern in patterns:
                match = next(
                    (
                        item
                        for item in target_list
                        if pattern.search(_text(item.get("heading")))
                    ),
                    None,
                )
                if match is not None:
                    owners[path] = _text(match.get("section_id"))
                    break
        return owners

    @staticmethod
    def _chunk_key(chunk: Iterable[Mapping[str, Any]]) -> str:
        return _digest([_text(item.get("section_id")) for item in chunk])

    @staticmethod
    def _source_role(source: AiTaskSourceRef) -> str:
        if source.source_type == "current_project_study_definition":
            return "confirmed_project_facts"
        if source.source_type == "company_protocol_reference_corpus":
            return "company_sop_or_protocol_reference"
        if source.source_type in {
            "shared_protocol_reference_corpus", "shared_phase1_protocol_reference_corpus"
        }:
            return "shared_reference_only"
        return "project_source"

    @classmethod
    def _freeze_reference_source(cls, source: AiTaskSourceRef) -> dict[str, Any]:
        payload = source.model_dump(mode="json")
        text_sha256 = hashlib.sha256(source.text_preview.encode("utf-8")).hexdigest()
        return {
            "source_id": source.source_id,
            "source_version": source.source_entry_id or source.source_id,
            "content_sha256": text_sha256,
            "role": cls._source_role(source),
            "locator": source.locator,
            "source": payload,
        }

    @staticmethod
    def _source_manifest_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for chunk in manifest.get("chunks") or []:
            for item in chunk.get("sources") or []:
                if not isinstance(item, Mapping):
                    continue
                payload = item.get("source") or {}
                key = (_text(item.get("source_id")), _text(item.get("content_sha256")))
                if not all(key):
                    continue
                unique[key] = {
                    "source_id": key[0],
                    "source_version": _text(item.get("source_version")),
                    "content_sha256": key[1],
                    "role": _text(item.get("role")),
                    "source_type": _text(payload.get("source_type")),
                    "title": _text(payload.get("title")),
                    "locator": _text(item.get("locator")),
                }
        sources = sorted(unique.values(), key=lambda item: (
            item["role"], item["title"], item["source_id"]
        ))
        return {
            "schema_version": "protocol-full-draft-source-summary.v1",
            "source_count": len(sources),
            "sources": sources,
        }

    def _live_reference_sources(
        self,
        service: Any,
        project_id: str,
        chunk: list[dict[str, Any]],
    ) -> list[AiTaskSourceRef]:
        """Resolve reference material once, before the durable task exists."""
        protocol = service.repo.protocol(project_id)
        section_by_id = {str(item.section_id): item for item in protocol.sections}
        sources: list[AiTaskSourceRef] = []
        seen: set[str] = set()
        for item in chunk:
            section = section_by_id.get(item["section_id"])
            if section is None:
                raise RuntimeStoreError(f"全文初稿章节不存在：{item['section_id']}")
            source = service._current_project_study_definition_source(protocol, section)
            if source is not None and source.source_id not in seen:
                sources.append(source)
                seen.add(source.source_id)
        if chunk:
            query = " ".join([item["heading"] for item in chunk])
            first_section = section_by_id[chunk[0]["section_id"]]
            for source in [
                *service._company_corpus_sources(
                    protocol, first_section, query, "medical_writing_revision"
                ),
                *service._shared_corpus_sources(
                    protocol, first_section, query, "medical_writing_revision"
                ),
            ]:
                if source.source_id not in seen:
                    sources.append(source)
                    seen.add(source.source_id)
        return sources

    def build_descriptor(
        self,
        project_id: str,
        *,
        section_ids: Iterable[str] | None = None,
        freeze_sources: bool = True,
    ) -> dict[str, Any]:
        service = self._service(project_id)
        repo = service.repo
        document = repo.protocol(project_id)
        scope = sorted({_text(item) for item in (section_ids or ()) if _text(item)})
        targets = self._target_sections(
            service,
            project_id,
            document,
            section_ids=scope,
        )
        if not targets:
            raise RuntimeStoreError(
                "指定章节没有可重新生成的空白正文；请检查章节是否已有实质正文"
                if scope
                else "当前文档没有可生成的空白正文章节；请先检查适用性或已有正文"
            )
        policy = dict(service._policy_identity())
        policy["prompt_version"] = FULL_DRAFT_PROMPT_VERSION
        decision_path_owners = self._decision_path_owners(
            targets,
            self._available_decision_paths(service, project_id),
        )
        descriptor = {
            "descriptor_version": FULL_DRAFT_DESCRIPTOR_VERSION,
            "project_id": project_id,
            "document_id": str(document.document_id),
            "document_version": str(document.version),
            "template_version": str(document.template_version),
            "study_definition": self._binding(repo, project_id, document),
            "authoring_journey": self._authoring_journey_binding(service, project_id),
            "target_sections": targets,
            "prompt_version": FULL_DRAFT_PROMPT_VERSION,
            "minimum_body_chars": FULL_DRAFT_MINIMUM_BODY_CHARS,
            "chunk_size": FULL_DRAFT_CHUNK_SIZE,
            "max_output_tokens": FULL_DRAFT_MAX_OUTPUT_TOKENS,
            "ai_policy": policy,
            "decision_path_owners": decision_path_owners,
        }
        if scope:
            # Only a scoped descriptor carries the key, so every pre-existing
            # full-document descriptor keeps its original digest and job
            # identity.  The scope is part of the digest, so a scoped
            # regeneration can never reuse the full-document job.
            descriptor["section_ids"] = scope
        # This hash protects the editable manuscript, confirmed design and
        # route contract.  The source manifest is frozen separately below so
        # later corpus/library changes do not invalidate an already submitted
        # task or cause it to consume newer bytes mid-run.
        descriptor["execution_context_sha256"] = _digest(descriptor)
        if not freeze_sources:
            return descriptor
        frozen_chunks = []
        for start in range(0, len(targets), FULL_DRAFT_CHUNK_SIZE):
            chunk = targets[start:start + FULL_DRAFT_CHUNK_SIZE]
            frozen_chunks.append({
                "chunk_key": self._chunk_key(chunk),
                "section_ids": [item["section_id"] for item in chunk],
                "sources": [
                    self._freeze_reference_source(source)
                    for source in self._live_reference_sources(service, project_id, chunk)
                ],
            })
        descriptor["source_manifest"] = {
            "schema_version": "protocol-full-draft-source-manifest.v1",
            "chunks": frozen_chunks,
        }
        descriptor["source_manifest_sha256"] = _digest(descriptor["source_manifest"])
        descriptor["digest"] = _digest(descriptor)
        return descriptor

    def submit_durable(
        self,
        project_id: str,
        durable_store: DurableJobStore,
        *,
        actor: str = "medical_manager",
        section_ids: Iterable[str] | None = None,
    ) -> tuple[str, bool]:
        descriptor = self.build_descriptor(project_id, section_ids=section_ids)
        business_key = f"v1:{descriptor['digest']}"
        payload = {
            "descriptor": descriptor,
            "actor": str(actor or "medical_manager"),
        }
        policy = descriptor["ai_policy"]
        request = DurableJobCreateRequest(
            project_id=project_id,
            job_type=FULL_DRAFT_JOB_TYPE,
            business_key=business_key,
            request_hash=descriptor["digest"],
            input_hash=descriptor["digest"],
            payload_json=_canonical(payload),
            created_by=str(actor or "medical_manager"),
            provider=str(policy.get("provider_name") or ""),
            model=str(policy.get("model_name") or ""),
            max_attempts=2,
        )
        response = durable_store.create_or_reuse(request)
        return response.job_id, bool(response.reused)

    def _sources_for_chunk(
        self,
        service: Any,
        project_id: str,
        descriptor: dict[str, Any],
        chunk: list[dict[str, Any]],
    ) -> list[AiTaskSourceRef]:
        packet_lines = []
        for item in chunk:
            packet_lines.append(
                "\n".join(
                    [
                        f"SECTION_ID={item['section_id']}",
                        f"章节编号={item['section_number']}",
                        f"章节标题={item['heading']}",
                        f"章节类型={item['node_kind']}",
                        f"当前正文={item['body_text'] or '（当前为空，需生成实质正文）'}",
                    ]
                )
            )
        packet = "\n\n".join(packet_lines)
        packet_id = _digest(
            {
                "descriptor": descriptor["digest"],
                "section_ids": [item["section_id"] for item in chunk],
            }
        )[:24]
        sources: list[AiTaskSourceRef] = [
            AiTaskSourceRef(
                source_id=f"protocol_full_draft_selection:{packet_id}",
                source_type="protocol_full_draft_selection",
                title=f"{descriptor.get('project_id') or project_id} 全文初稿章节包",
                locator=f"document:{descriptor.get('document_id')}:full-draft:{packet_id}",
                text_preview=packet,
                project_id=project_id,
                module="medical_writing",
                source_entry_id=f"full-draft:{descriptor['digest']}:{packet_id}",
            )
        ]
        seen = {sources[0].source_id}
        manifest = descriptor.get("source_manifest") or {}
        if _digest(manifest) != descriptor.get("source_manifest_sha256"):
            raise RuntimeStoreError("全文初稿冻结来源清单完整性校验失败")
        chunk_key = self._chunk_key(chunk)
        frozen = next((item for item in manifest.get("chunks") or []
                       if item.get("chunk_key") == chunk_key), None)
        if frozen is None or frozen.get("section_ids") != [item["section_id"] for item in chunk]:
            raise RuntimeStoreError("全文初稿冻结来源清单与章节范围不一致")
        for item in frozen.get("sources") or []:
            payload = item.get("source") if isinstance(item, Mapping) else None
            if not isinstance(payload, Mapping):
                raise RuntimeStoreError("全文初稿冻结来源条目损坏")
            source = AiTaskSourceRef(**dict(payload))
            if (item.get("source_id") != source.source_id
                    or item.get("locator") != source.locator
                    or item.get("content_sha256") != hashlib.sha256(
                        source.text_preview.encode("utf-8")
                    ).hexdigest()):
                raise RuntimeStoreError("全文初稿冻结来源身份校验失败")
            if source.source_id not in seen:
                sources.append(source)
                seen.add(source.source_id)
        return sources

    @staticmethod
    def _instruction(chunk: list[dict[str, Any]], descriptor: dict[str, Any]) -> str:
        ids = ", ".join(item["section_id"] for item in chunk)
        corpus_rules = "\n".join(
            f"- {rule}" for rule in CORPUS_GENERALIZATION_PROMPT_RULES
        )
        section_ids = {_text(item.get("section_id")) for item in chunk}
        decision_paths = [
            path
            for path, owner in (descriptor.get("decision_path_owners") or {}).items()
            if _text(owner) in section_ids
        ]
        decision_path_text = "、".join(decision_paths) or "（本批次没有可写入的待确认研究字段）"
        return (
            "你是中文临床研究方案撰写专家。请生成一个可直接进入研究方案全文的章节正文候选，"
            "而不是标题清单或提纲。只依据允许来源和当前项目已确认研究事实；公司/共享语料只用于"
            "监管语境措辞与结构，不得继承竞品的药物、人群、剂量、终点、时间点或样本量。"
            f"本批次必须按顺序完整返回这些章节ID：{ids}。每章至少{descriptor['minimum_body_chars']}个中文字符，"
            "必须是连续、可审阅的规范正文，不能使用Markdown表格、TBD/TODO、待补充、‘不适用’泛化句、"
            "‘由方案规定’或重复标题。不得把fixture、ProtocolAssemblyPlan、SECTION_ID、evidence_span_ids等"
            "内部传输/测试标记写入正文；应将事实改写为自然、原生的监管中文。无法安全支持的项目事实不要猜测，"
            "服务器会拒绝不完整或占位内容。对于允许来源已明确给出的年龄、剂量、给药频率、治疗周期、"
            "样本量、终点、量表和访视时间点，必须在对应章节直接写入原值；不得改写成‘将在正式文本中明确’、"
            "‘未提供具体数值’、‘尚无直接证据来源支持’、‘由医学经理/医学负责人确认’或‘确认后再写入’。"
            "当前输出就是供医学经理审核的完整候选，不得承诺后续补写；"
            "正文不得出现‘当前项目已确认’、‘本方案不引用竞品’、‘公司语料’、‘章节包’、"
            "‘候选正文’等写作过程说明；这些内容只可转化为rationale中的简洁证据说明。"
            "公司或共享语料不得直接决定本项目的避孕方法、妊娠报告、AE/SAE定义与时限、"
            "剂量调整、合并/禁限用药、洗脱、救援治疗、随机揭盲、分析集或其他研究实施规则。"
            "缺少项目实施细节时，必须先完成由已确认事实或允许来源支持的实质正文，并把每个未决事项"
            "写入gap_items；此时content_status使用partial，不得因为局部细节待核对而把已有充分依据的整章留空。"
            "gap_items必须给出稳定gap_id、类别、正文目标位置、下一动作和缺少的来源类别；资料已经存在但"
            "尚未检索到时使用source_not_retrieved，格式或语义节点无法映射时使用mapping_failed，不能误报为用户未上传。"
            "保守正文不得包含命名系统、固定方法清单、固定时限、未经来源支持的角色分工或停止后果。"
            "若允许的当前项目来源没有明确写出某项研究实施规则，不得把该规则写成方案既定要求；"
            "妊娠处理、AE分类、报告对象与时限、随访终点、数据职责、签署要求和CRF记录方式等"
            "只能说明本章节应覆盖的目的与范围，并把可选建议写入rationale，不能在正文中虚构为已决定事项。"
            "proposal_text必须是可以直接写入方案的规范句子，不得用‘本章节需要覆盖’、‘本节应列明’、"
            "‘本章节说明目的与范围’等目录说明冒充正文。不得由已有访视日推断实验室检查、生命体征、"
            "心电图、体格检查或依从性评价在每个访视都实施；不得由终点中的‘较基线变化’自行新增"
            "DLQI采集时点；不得自行定义TEAE采集窗口、研究结束时点或安全性评估窗口。"
            "妊娠或哺乳期排除不能推出避孕方法、伴侣妊娠报告、新生儿随访或妊娠检查日程。"
            "下列章节采用更严格的来源判定：方案概要必须用已确认设计事实完成，并省略未确认实施细节；"
            "疾病背景及治疗现状在缺少流行病学、疾病负担、指南或治疗现状来源时必须source_gap；"
            "筛选失败与重新筛选、计划外访视、剂量调整/暂停/恢复/永久停药、药物过量与给药错误、"
            "试验药包装储存与发放回收、AE/SAE/SUSAR定义与采集报告、研究药物具体风险、保险赔偿，"
            "在缺少对应项目文件时必须source_gap，不能用条件句、范围句或通用原则标成complete。"
            "盲法章节只能写双盲、1:1和匹配安慰剂等已确认事实，不得自行指定受试者、研究者、"
            "评价者或其他人员的盲态范围。"
            "除方案概要、研究设计、目的终点和样本量章节外，不要重复整套样本量、剂量、主要终点、"
            "随机和盲法信息，只写与本章节直接相关的事实。"
            "每章用evidence_span_ids绑定本次evidence_spans中的直接依据，并将needs_medical_confirmation设为true。"
            "每章还必须返回content_status、decision_items和missing_source_classes。"
            "事实充分时用complete并返回完整正文。只有本批次列出的待确认研究字段能够完整承载一个"
            "研究设计决定时才可用decision_required：给出一个推荐项和1至2个备选项，并将proposal_text"
            "严格留空；用户确认前不得输出任何预选正文。若缺少的实施规则没有对应的待确认研究字段，"
            "必须用source_gap说明所缺项目来源或职能确认，不能借用语义不相干的字段。缺少IB、既往研究、"
            "流行病学、研究药物作用机制/非临床/既往临床资料等核心来源缺失，导致本章无法形成任何"
            "有实质信息的正文时，才用source_gap；proposal_text留空并准确列出缺少的来源类别，禁止用"
            "通用段落凑足字数。量表名称、终点及评价时点已有项目事实时，应先写入这些已确认内容，"
            "把版本、授权和培训等待核细节列入rationale，不得把整章降为空白。每个决定项的fact_path只能从以下字段中按语义选择并原样复制："
            f"{decision_path_text}。不得自造字段路径；同一字段最多返回一个决定项。决定项只用于引导上游研究设计确认，"
            "模型本身不得写回研究事实。决定项的每个选项都必须是用户点选后可直接写入对应研究字段的"
            "具体答案；如果来源不足以提出具体、互斥且可执行的选项，必须返回source_gap，不能用‘按类别列出’、"
            "‘由团队确认’或其他写作方式选择冒充科学决定。"
            "探索性目的与终点的选项必须包含‘本研究不设置探索性目的/终点’，不能强迫确证性研究新增"
            "探索程序；目的和终点的推荐必须能够成对对应。"
            "\n语料泛化规则（全部适用）：\n"
            f"{corpus_rules}"
        )

    @staticmethod
    def _review_policy(heading: str, proposal: str, corpus_count: int) -> dict[str, Any]:
        required_reasons: list[str] = []
        advisory_reasons: list[str] = []
        heading_signals = sorted(
            {
                match.group(0)
                for match in _REQUIRED_REVIEW_HEADING_RE.finditer(heading)
            }
        )
        embedded_signals = sorted(
            {match.group(0) for match in _REQUIRED_REVIEW_CONTENT_RE.finditer(proposal)}
        )
        if heading_signals:
            advisory_reasons.append(
                f"本节复述高影响研究设计（{'、'.join(heading_signals[:6])}）；请在合并设计摘要中统一核对。"
            )
        if embedded_signals:
            advisory_reasons.append(
                f"本节提及高影响设计信息（{'、'.join(embedded_signals[:6])}）；系统未把重复提及升级为强制确认。"
            )
        if corpus_count and _CORPUS_CONDUCT_RE.search(proposal):
            advisory_reasons.append(
                "本节引用公司语料形成共性表述；定稿时请用本项目权威文件复核适用性。"
            )
        restatement_count = sum(
            bool(pattern.search(proposal)) for pattern in _DESIGN_RESTATEMENT_SIGNALS
        )
        if (
            restatement_count >= 3
            and not _DESIGN_RESTATEMENT_ALLOWED_HEADING_RE.search(heading)
        ):
            advisory_reasons.append(
                "本节重复了多项总体设计事实；建议压缩为与本节直接相关的信息。"
            )
        return {
            "review_level": "required" if required_reasons else "standard",
            "review_reasons": required_reasons,
            "review_advisories": advisory_reasons,
        }

    @classmethod
    def _review_metadata(
        cls,
        section: Mapping[str, Any],
        output: Mapping[str, Any],
        sources: list[AiTaskSourceRef],
        descriptor_section: Mapping[str, Any],
    ) -> dict[str, Any]:
        evidence_by_id = {
            str(item.get("span_id") or ""): item
            for item in output.get("evidence_spans") or []
            if isinstance(item, dict) and str(item.get("span_id") or "").strip()
        }
        source_by_id = {source.source_id: source for source in sources}
        referenced_sources = []
        for span_id in section.get("evidence_span_ids") or []:
            evidence = evidence_by_id.get(str(span_id))
            source = source_by_id.get(str((evidence or {}).get("source_id") or ""))
            if source is not None:
                referenced_sources.append(source)
        project_count = sum(
            source.source_type == "current_project_study_definition"
            for source in referenced_sources
        )
        corpus_count = sum(
            source.source_type in _CORPUS_SOURCE_TYPES for source in referenced_sources
        )
        metadata = cls._review_policy(
            _text(descriptor_section.get("heading")),
            _text(section.get("proposal_text")),
            corpus_count,
        )
        metadata.update(
            {
            "evidence_summary": {
                "project_fact_spans": project_count,
                "corpus_spans": corpus_count,
            },
            }
        )
        return metadata

    @staticmethod
    def _evidence_bindings_for_section(
        section: Mapping[str, Any],
        output: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        """Persist the exact evidence behind one section without cross-run ID collisions.

        ``span_id`` values are scoped to one provider response and may repeat in
        another chunk.  Keeping each binding beside its section makes the
        persisted candidate independently auditable while preserving the
        provider's original evidence IDs for display and diagnostics.
        """
        evidence_by_id = {
            _text(item.get("span_id")): item
            for item in output.get("evidence_spans") or []
            if isinstance(item, Mapping) and _text(item.get("span_id"))
        }
        bindings: list[dict[str, str]] = []
        for raw_span_id in section.get("evidence_span_ids") or []:
            span_id = _text(raw_span_id)
            evidence = evidence_by_id.get(span_id)
            if evidence is None:
                raise RuntimeStoreError(f"章节证据引用无法解析：{span_id or 'empty'}")
            binding = {
                "span_id": span_id,
                "source_id": _text(evidence.get("source_id")),
                "locator": _text(evidence.get("locator")),
                "quote": _text(evidence.get("quote")),
            }
            if not all(binding.values()):
                raise RuntimeStoreError(f"章节证据绑定不完整：{span_id}")
            binding["quote_sha256"] = hashlib.sha256(
                binding["quote"].encode("utf-8")
            ).hexdigest()
            bindings.append(binding)
        return bindings

    @staticmethod
    def _section_evidence_is_resolvable(
        section: Mapping[str, Any],
        source_locators: Mapping[str, str],
    ) -> bool:
        expected = [_text(item) for item in section.get("evidence_span_ids") or []]
        bindings = section.get("evidence_bindings")
        if not isinstance(bindings, list):
            return False
        section_source_ids = {
            _text(item) for item in section.get("source_ids") or [] if _text(item)
        }
        actual: list[str] = []
        for item in bindings:
            if not isinstance(item, Mapping):
                return False
            span_id = _text(item.get("span_id"))
            source_id = _text(item.get("source_id"))
            locator = _text(item.get("locator"))
            quote = _text(item.get("quote"))
            if (
                not span_id
                or source_id not in section_source_ids
                or source_locators.get(source_id) != locator
                or not locator
                or not quote
                or _text(item.get("quote_sha256"))
                != hashlib.sha256(quote.encode("utf-8")).hexdigest()
            ):
                return False
            actual.append(span_id)
        return actual == expected

    @classmethod
    def _artifact_evidence_is_resolvable(cls, artifact: Mapping[str, Any]) -> bool:
        source_locators: dict[str, str] = {}
        for item in artifact.get("source_bindings") or []:
            if not isinstance(item, Mapping):
                return False
            source_id = _text(item.get("source_id"))
            locator = _text(item.get("locator"))
            if not source_id or not locator:
                return False
            if source_id in source_locators and source_locators[source_id] != locator:
                return False
            source_locators[source_id] = locator
        sections = artifact.get("sections")
        return isinstance(sections, list) and bool(sections) and all(
            isinstance(section, Mapping)
            and cls._section_evidence_is_resolvable(section, source_locators)
            for section in sections
        )

    @classmethod
    def _apply_review_policy(cls, artifact: dict[str, Any]) -> dict[str, Any]:
        required_ids: list[str] = []
        decision_ids: list[str] = []
        source_gap_ids: list[str] = []
        partial_ids: list[str] = []
        for section in artifact.get("sections") or []:
            content_status = _text(section.get("content_status")) or "complete"
            if content_status == "decision_required":
                section.update({
                    "review_level": "blocked",
                    "review_reasons": ["本节包含尚未确认的科学决定；请先在研究设计中选择推荐项或备选项。"],
                    "review_advisories": [],
                })
                decision_ids.append(_text(section.get("section_id")))
                continue
            if content_status == "source_gap":
                section.update({
                    "review_level": "blocked",
                    "review_reasons": ["本节缺少可引用来源；补充所列资料后再生成正文。"],
                    "review_advisories": [],
                })
                source_gap_ids.append(_text(section.get("section_id")))
                continue
            if content_status == "partial":
                partial_ids.append(_text(section.get("section_id")))
            evidence_summary = section.get("evidence_summary") or {}
            section.update(
                cls._review_policy(
                    _text(section.get("heading")),
                    _text(section.get("proposal_text")),
                    int(evidence_summary.get("corpus_spans") or 0),
                )
            )
            if section.get("review_level") == "required":
                required_ids.append(_text(section.get("section_id")))
        coverage = artifact.setdefault("coverage", {})
        coverage["required_review_count"] = len(required_ids)
        coverage["required_review_section_ids"] = required_ids
        coverage["decision_required_count"] = len(decision_ids)
        coverage["decision_required_section_ids"] = decision_ids
        coverage["source_gap_count"] = len(source_gap_ids)
        coverage["source_gap_section_ids"] = source_gap_ids
        coverage["partial_count"] = len(partial_ids)
        coverage["partial_section_ids"] = partial_ids
        is_legacy = artifact.get("schema_version") in LEGACY_FULL_DRAFT_ARTIFACT_SCHEMAS
        evidence_chain_resolvable = (
            not is_legacy and cls._artifact_evidence_is_resolvable(artifact)
        )
        coverage["legacy_read_only"] = is_legacy
        coverage["evidence_chain_resolvable"] = evidence_chain_resolvable
        coverage["working_draft_ready"] = (
            evidence_chain_resolvable
            and any(_text(item.get("proposal_text")) for item in artifact.get("sections") or [])
        )
        coverage["formal_ready"] = (
            evidence_chain_resolvable and not decision_ids and not source_gap_ids
            and not partial_ids
        )
        coverage["adoption_ready"] = coverage["formal_ready"]
        artifact["review_policy_version"] = FULL_DRAFT_REVIEW_POLICY_VERSION
        return artifact

    @staticmethod
    def _run_output(run: Any) -> dict[str, Any]:
        for artifact in reversed(list(getattr(run, "artifacts", []) or [])):
            payload = getattr(artifact, "payload", None)
            if isinstance(payload, dict) and "full_draft" in payload:
                return payload
        raise RuntimeStoreError("全文初稿 AI 运行结果缺少可持久化的 full_draft 输出")

    def _artifact_path(
        self,
        project_id: str,
        job_id: str,
        filename: str,
        *,
        chunk: Optional[list[dict[str, Any]]] = None,
        descriptor_digest: str = "",
    ) -> Path:
        if chunk is None:
            relative = Path(_safe_project_path(project_id)) / job_id / filename
        else:
            chunk_digest = _digest(
                {
                    "descriptor": descriptor_digest,
                    "section_ids": [item["section_id"] for item in chunk],
                }
            )[:24]
            relative = (
                Path(_safe_project_path(project_id))
                / job_id
                / "chunks"
                / f"{filename}-{chunk_digest}.json"
            )
        return self.artifact_root / relative

    @staticmethod
    def _read_json_file(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = _canonical(payload).encode("utf-8")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return hashlib.sha256(encoded).hexdigest()

    def _read_reusable_chunk(
        self,
        project_id: str,
        job_id: str,
        descriptor: dict[str, Any],
        chunk_index: int,
        chunk: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        path = self._artifact_path(
            project_id,
            job_id,
            f"chunk-{chunk_index:04d}",
            chunk=chunk,
            descriptor_digest=str(descriptor.get("digest") or ""),
        )
        payload = self._read_json_file(path)
        if not payload:
            return None
        expected_ids = [item["section_id"] for item in chunk]
        if (
            payload.get("schema_version") != FULL_DRAFT_CHUNK_ARTIFACT_SCHEMA
            or payload.get("job_id") != job_id
            or payload.get("project_id") != project_id
            or payload.get("precondition_digest") != descriptor.get("digest")
            or payload.get("chunk_index") != chunk_index
            or payload.get("section_ids") != expected_ids
        ):
            return None
        sections = payload.get("sections")
        if not isinstance(sections, list):
            return None
        actual_ids = [
            str(item.get("section_id") or "")
            for item in sections
            if isinstance(item, dict)
        ]
        if actual_ids != expected_ids:
            return None
        source_locators = {
            _text(item.get("source_id")): _text(item.get("locator"))
            for item in payload.get("source_bindings") or []
            if isinstance(item, Mapping)
            and _text(item.get("source_id"))
            and _text(item.get("locator"))
        }
        if not all(
            self._section_evidence_is_resolvable(item, source_locators)
            for item in sections
            if isinstance(item, Mapping)
        ):
            return None
        return payload

    def _execute_chunk(
        self,
        service: Any,
        project_id: str,
        descriptor: dict[str, Any],
        chunk: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], Any, list[AiTaskSourceRef]]:
        sources = self._sources_for_chunk(service, project_id, descriptor, chunk)
        chunk_section_ids = {item["section_id"] for item in chunk}
        decision_fact_paths = [
            path
            for path, owner in (descriptor.get("decision_path_owners") or {}).items()
            if owner in chunk_section_ids
        ]
        context = {
            "draft_version": descriptor["digest"],
            "section_ids": [item["section_id"] for item in chunk],
            "marker_open": "SECTION_ID=",
            "marker_close": "\n",
            "minimum_body_chars": descriptor["minimum_body_chars"],
            "decision_fact_paths": decision_fact_paths,
        }
        run = service.ai_task_runner.submit_internal(
            project_id,
            AiTaskRequest(
                module="medical_writing",
                task_type=AiTaskType.PROTOCOL_FULL_DRAFT,
                prompt_version=FULL_DRAFT_PROMPT_VERSION,
                allowed_sources=sources,
                forbidden_source_ids=[],
                user_instruction=self._instruction(chunk, descriptor),
                task_context=context,
            ),
        )
        if run.status == AiTaskRunStatus.BLOCKED:
            raise RuntimeStoreError("独立AI未配置，未生成全文初稿候选")
        if run.status == AiTaskRunStatus.FAILED:
            detail = "; ".join(getattr(run, "validation_errors", []) or []) or getattr(run, "error_message", "")
            raise RuntimeStoreError(f"独立AI全文初稿未通过校验：{detail or 'provider output failed validation'}")
        output = self._run_output(run)
        sections = ((output.get("full_draft") or {}).get("sections") or [])
        expected_ids = [item["section_id"] for item in chunk]
        actual_ids = [str(item.get("section_id") or "") for item in sections if isinstance(item, dict)]
        if actual_ids != expected_ids:
            raise RuntimeStoreError("全文初稿章节身份或顺序不匹配，未写入任何正文")
        return output, run, sources

    def run_job(
        self,
        job: Any,
        claim_token: str,
        cancel_check: Callable[[], bool],
        heartbeat: Callable[[DurableJobProgressPayload], bool],
    ) -> DurableJobResult:
        payload = json.loads(job.payload_json or "{}")
        expected = payload.get("descriptor") or {}
        service = self._service(job.project_id)
        try:
            current = self.build_descriptor(
                job.project_id,
                section_ids=expected.get("section_ids"),
                freeze_sources=False,
            )
        except Exception as exc:
            return DurableJobResult(error=f"全文初稿上下文不可用：{exc}", retryable=False)
        if (current.get("execution_context_sha256")
                != expected.get("execution_context_sha256")):
            return DurableJobResult(error="全文初稿上下文已变化，请重新生成候选", retryable=False)
        expected_policy = (expected.get("ai_policy") or {}).get("route_identity_hash")
        current_policy = service._policy_identity()
        if expected_policy != current_policy.get("route_identity_hash"):
            return DurableJobResult(error="独立AI路由身份已变化，请重新生成全文初稿", retryable=False)

        target = list(expected.get("target_sections") or [])
        chunk_size = max(1, int(expected.get("chunk_size") or FULL_DRAFT_CHUNK_SIZE))
        chunks = [
            target[index : index + chunk_size]
            for index in range(0, len(target), chunk_size)
        ]
        final_path = self._artifact_path(job.project_id, job.job_id, "full-draft.json")
        existing_final = self._read_json_file(final_path)
        if (
            existing_final
            and existing_final.get("schema_version") == FULL_DRAFT_ARTIFACT_SCHEMA
            and existing_final.get("job_id") == job.job_id
            and existing_final.get("project_id") == job.project_id
            and existing_final.get("precondition_digest") == expected.get("digest")
            and (existing_final.get("coverage") or {}).get("section_ids")
            == [item["section_id"] for item in target]
            and self._artifact_evidence_is_resolvable(existing_final)
        ):
            encoded = _canonical(existing_final).encode("utf-8")
            artifact_sha = hashlib.sha256(encoded).hexdigest()
            relative = final_path.relative_to(self.artifact_root)
            locator = _canonical(
                {
                    "schema_version": FULL_DRAFT_ARTIFACT_SCHEMA,
                    "artifact_relpath": relative.as_posix(),
                    "artifact_sha256": artifact_sha,
                    "precondition_digest": expected["digest"],
                    # section_ids 列表随章节增长，会把 locator 撑破
                    # DurableJobRecord.artifact_locator 的 2000 字符上限；
                    # 定位器只需要路径与哈希，覆盖明细保留在工件内。
                    "coverage": {
                        key: value
                        for key, value in (existing_final.get("coverage") or {}).items()
                        if key != "section_ids"
                    },
                }
            )
            return DurableJobResult(
                output_hash=artifact_sha,
                artifact_locator=locator,
                provider=str((expected.get("ai_policy") or {}).get("provider_name") or ""),
                model=str((expected.get("ai_policy") or {}).get("model_name") or ""),
                progress=DurableJobProgressPayload(
                    phase="persisted_candidate",
                    percent=1.0,
                    step=len(chunks),
                    step_total=len(chunks),
                    message=f"已复用已持久化全文初稿 {len(target)}/{len(target)} 个章节候选",
                ),
            )
        all_sections: list[dict[str, Any]] = []
        run_ids: list[str] = []
        source_bindings: list[dict[str, Any]] = []
        total = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            if cancel_check():
                return DurableJobResult(error="全文初稿任务已取消或失去执行权", retryable=False)
            progress = DurableJobProgressPayload(
                phase="calling_synthesis_ai",
                percent=(index - 1) / max(total, 1),
                step=index,
                step_total=total,
                message=f"正在生成全文初稿（第 {index}/{total} 批）",
            )
            if not heartbeat(progress):
                return DurableJobResult(error="全文初稿任务失去执行权", retryable=True)
            reusable = self._read_reusable_chunk(
                job.project_id,
                job.job_id,
                expected,
                index,
                chunk,
            )
            if reusable is not None:
                run_ids.append(str(reusable.get("ai_run_id") or ""))
                source_bindings.extend(
                    item
                    for item in reusable.get("source_bindings") or []
                    if isinstance(item, dict)
                )
                all_sections.extend(
                    dict(item)
                    for item in reusable.get("sections") or []
                    if isinstance(item, dict)
                )
            else:
                try:
                    output, run, sources = self._execute_chunk(service, job.project_id, expected, chunk)
                except Exception as exc:
                    return DurableJobResult(error=str(exc), retryable=False)
                if cancel_check():
                    return DurableJobResult(error="AI完成后任务已取消，未持久化全文候选", retryable=False)
                chunk_source_bindings = [
                    {
                        "source_id": source.source_id,
                        "source_type": source.source_type,
                        "source_version": source.source_entry_id or source.source_id,
                        "role": (
                            "current_working_draft_packet"
                            if source.source_type == "protocol_full_draft_selection"
                            else self._source_role(source)
                        ),
                        "locator": source.locator,
                        "content_sha256": hashlib.sha256(
                            source.text_preview.encode("utf-8")
                        ).hexdigest(),
                        # Legacy read compatibility for v5-v9 evidence readers.
                        "text_sha256": hashlib.sha256(
                            source.text_preview.encode("utf-8")
                        ).hexdigest(),
                    }
                    for source in sources
                ]
                chunk_sections = []
                chunk_by_id = {item["section_id"]: item for item in chunk}
                for item in (output.get("full_draft") or {}).get("sections") or []:
                    section = dict(item)
                    descriptor_section = chunk_by_id.get(str(section.get("section_id") or ""), {})
                    section["heading"] = descriptor_section.get("heading", "")
                    section["section_number"] = descriptor_section.get("section_number", "")
                    section["ai_run_id"] = str(run.run_id)
                    section["source_ids"] = [source.source_id for source in sources]
                    try:
                        section["evidence_bindings"] = self._evidence_bindings_for_section(
                            section,
                            output,
                        )
                    except RuntimeStoreError as exc:
                        return DurableJobResult(error=str(exc), retryable=False)
                    section.update(
                        self._review_metadata(
                            section,
                            output,
                            sources,
                            descriptor_section,
                        )
                    )
                    chunk_sections.append(section)
                chunk_record = {
                    "schema_version": FULL_DRAFT_CHUNK_ARTIFACT_SCHEMA,
                    "job_id": job.job_id,
                    "project_id": job.project_id,
                    "precondition_digest": expected["digest"],
                    "chunk_index": index,
                    "section_ids": [item["section_id"] for item in chunk],
                    "sections": chunk_sections,
                    "ai_run_id": str(run.run_id),
                    "source_bindings": chunk_source_bindings,
                }
                try:
                    self._write_json_atomic(
                        self._artifact_path(
                            job.project_id,
                            job.job_id,
                            f"chunk-{index:04d}",
                            chunk=chunk,
                            descriptor_digest=expected["digest"],
                        ),
                        chunk_record,
                    )
                except Exception as exc:
                    return DurableJobResult(error=f"全文初稿分批候选持久化失败：{exc}", retryable=False)
                run_ids.append(str(run.run_id))
                source_bindings.extend(chunk_source_bindings)
                all_sections.extend(chunk_sections)
            if not heartbeat(
                DurableJobProgressPayload(
                    phase="validating_candidates",
                    percent=index / max(total, 1),
                    step=index,
                    step_total=total,
                    message=f"已完成全文初稿第 {index}/{total} 批校验",
                )
            ):
                return DurableJobResult(error="全文初稿校验后任务失去执行权", retryable=True)

        expected_ids = [item["section_id"] for item in target]
        actual_ids = [str(item.get("section_id") or "") for item in all_sections]
        if actual_ids != expected_ids:
            return DurableJobResult(error="全文初稿合并后章节覆盖不完整，未写入任何正文", retryable=False)
        if not self._artifact_evidence_is_resolvable(
            {"sections": all_sections, "source_bindings": source_bindings}
        ):
            return DurableJobResult(error="全文初稿章节证据链不完整，未写入候选", retryable=False)
        decision_path_owners = expected.get("decision_path_owners") or {}
        seen_decision_paths: set[str] = set()
        for section in all_sections:
            section_id = _text(section.get("section_id"))
            for item in section.get("decision_items") or []:
                fact_path = _text(item.get("fact_path"))
                if decision_path_owners.get(fact_path) != section_id:
                    return DurableJobResult(
                        error=f"全文初稿决定字段未由指定章节承载：{fact_path or 'empty'}",
                        retryable=False,
                    )
                if fact_path in seen_decision_paths:
                    return DurableJobResult(
                        error=f"全文初稿决定字段重复：{fact_path}",
                        retryable=False,
                    )
                seen_decision_paths.add(fact_path)
        required_review_ids = [
            str(item.get("section_id") or "")
            for item in all_sections
            if item.get("review_level") == "required"
        ]
        decision_required_ids = [
            str(item.get("section_id") or "")
            for item in all_sections
            if item.get("content_status") == "decision_required"
        ]
        source_gap_ids = [
            str(item.get("section_id") or "")
            for item in all_sections
            if item.get("content_status") == "source_gap"
        ]
        partial_ids = [
            str(item.get("section_id") or "")
            for item in all_sections
            if item.get("content_status") == "partial"
        ]
        artifact = {
            "schema_version": FULL_DRAFT_ARTIFACT_SCHEMA,
            "job_id": job.job_id,
            "project_id": job.project_id,
            "document_id": expected["document_id"],
            "document_version": expected["document_version"],
            "precondition_digest": expected["digest"],
            "source_manifest_sha256": expected.get("source_manifest_sha256", ""),
            "source_manifest": self._source_manifest_summary(
                expected.get("source_manifest") or {}
            ),
            "study_definition": expected["study_definition"],
            "authoring_journey": expected.get("authoring_journey") or {},
            "decision_path_owners": decision_path_owners,
            "target_sections": target,
            "sections": all_sections,
            "coverage": {
                "target_count": len(expected_ids),
                "generated_count": len(all_sections),
                "required_review_count": len(required_review_ids),
                "required_review_section_ids": required_review_ids,
                "decision_required_count": len(decision_required_ids),
                "decision_required_section_ids": decision_required_ids,
                "source_gap_count": len(source_gap_ids),
                "source_gap_section_ids": source_gap_ids,
                "partial_count": len(partial_ids),
                "partial_section_ids": partial_ids,
                "working_draft_ready": any(
                    _text(item.get("proposal_text")) for item in all_sections
                ),
                "formal_ready": not decision_required_ids and not source_gap_ids and not partial_ids,
                "adoption_ready": not decision_required_ids and not source_gap_ids and not partial_ids,
                "section_ids": expected_ids,
            },
            "ai_run_ids": run_ids,
            "source_bindings": source_bindings,
            "created_by": payload.get("actor") or "medical_manager",
        }
        try:
            destination = final_path
            relative = destination.relative_to(self.artifact_root)
            artifact_sha = self._write_json_atomic(destination, artifact)
        except Exception as exc:
            return DurableJobResult(error=f"全文初稿候选持久化失败：{exc}", retryable=False)
        locator = _canonical(
            {
                "schema_version": FULL_DRAFT_ARTIFACT_SCHEMA,
                "artifact_relpath": relative.as_posix(),
                "artifact_sha256": artifact_sha,
                "precondition_digest": expected["digest"],
                "coverage": {
                    key: value
                    for key, value in artifact["coverage"].items()
                    if key not in {
                        "section_ids",
                        "required_review_section_ids",
                        "decision_required_section_ids",
                        "source_gap_section_ids",
                        "partial_section_ids",
                    }
                },
            }
        )
        return DurableJobResult(
            output_hash=artifact_sha,
            artifact_locator=locator,
            provider=str((expected.get("ai_policy") or {}).get("provider_name") or ""),
            model=str((expected.get("ai_policy") or {}).get("model_name") or ""),
            progress=DurableJobProgressPayload(
                phase="persisted_candidate",
                percent=1.0,
                step=total,
                step_total=total,
                message=(
                    f"全文初稿已生成 {len(all_sections)}/{len(expected_ids)} 个章节候选，"
                    f"其中 {len(required_review_ids)} 个高影响章节需逐卡确认"
                ),
            ),
        )

    @staticmethod
    def decision_item_id(section_id: str, question: Any) -> str:
        """Deterministic identity of one full-draft decision item.

        The identity is derived from the artifact itself so a decision can be
        resolved and replayed without introducing a second decision store.
        """
        return "fdd_" + _digest(
            {"section_id": _text(section_id), "question": _text(question)}
        )[:24]

    @classmethod
    def decision_index(cls, artifact: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for section in artifact.get("sections") or []:
            if not isinstance(section, Mapping):
                continue
            section_id = _text(section.get("section_id"))
            for item in section.get("decision_items") or []:
                if not isinstance(item, Mapping):
                    continue
                index[cls.decision_item_id(section_id, item.get("question"))] = {
                    "section_id": section_id,
                    "content_status": _text(section.get("content_status")),
                    "item": dict(item),
                }
        return index

    def read_artifact(self, project_id: str, job: Any) -> dict[str, Any]:
        artifact, _ = self.read_frozen_artifact(project_id, job)
        return self._with_decision_identity(self._apply_review_policy(artifact))

    def read_frozen_artifact(
        self, project_id: str, job: Any
    ) -> tuple[dict[str, Any], str]:
        """Read the exact persisted candidate and its verified byte identity.

        Normal reads project decision identities and review policy into an
        in-memory copy.  Candidate acceptance must instead bind its receipt to
        the immutable bytes written by the durable job, so a later read-time
        projection can never change the accepted candidate identity.
        """
        if job.project_id != project_id or job.job_type != FULL_DRAFT_JOB_TYPE:
            raise RuntimeStoreError("全文初稿任务不属于当前项目")
        if job.status != "completed":
            raise RuntimeStoreError(f"全文初稿任务尚未完成：{job.status}")
        locator = json.loads(job.artifact_locator or "{}")
        relative = Path(str(locator.get("artifact_relpath") or ""))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise RuntimeStoreError("全文初稿候选定位无效")
        path = (self.artifact_root / relative).resolve()
        if self.artifact_root not in path.parents:
            raise RuntimeStoreError("全文初稿候选越界")
        raw = path.read_bytes()
        artifact_sha256 = hashlib.sha256(raw).hexdigest()
        if artifact_sha256 != str(locator.get("artifact_sha256") or ""):
            raise RuntimeStoreError("全文初稿候选完整性校验失败")
        if job.output_hash and artifact_sha256 != str(job.output_hash):
            raise RuntimeStoreError("全文初稿任务与候选身份不一致")
        artifact = json.loads(raw.decode("utf-8"))
        if artifact.get("schema_version") not in {
            FULL_DRAFT_ARTIFACT_SCHEMA,
            *LEGACY_FULL_DRAFT_ARTIFACT_SCHEMAS,
        }:
            raise RuntimeStoreError("全文初稿候选版本不受支持")
        return artifact, artifact_sha256

    @classmethod
    def _with_decision_identity(cls, artifact: dict[str, Any]) -> dict[str, Any]:
        """Project the stable decision identity into a read-time copy.

        The persisted artifact stays byte-identical; clients address a decision
        by the identity derived from the artifact itself instead of inventing
        their own index into a list that may be reordered.
        """
        for section in artifact.get("sections") or []:
            if not isinstance(section, dict):
                continue
            section_id = _text(section.get("section_id"))
            items = section.get("decision_items")
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    item.setdefault(
                        "decision_id",
                        cls.decision_item_id(section_id, item.get("question")),
                    )
        return artifact

    def adopt(
        self,
        project_id: str,
        job: Any,
        *,
        actor: str = "medical_manager",
        confirmed_section_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        artifact = self.read_artifact(project_id, job)
        if artifact.get("schema_version") != FULL_DRAFT_ARTIFACT_SCHEMA:
            raise RuntimeStoreError("旧版全文初稿候选仅供查阅；请按当前研究事实重新生成后再采纳")
        if not self._artifact_evidence_is_resolvable(artifact):
            raise RuntimeStoreError("全文初稿章节证据链不完整，未采纳")
        service = self._service(project_id)
        repo = service.repo
        document = repo.protocol(project_id)
        if str(document.document_id) != str(artifact.get("document_id")):
            raise RuntimeStoreError("全文初稿所属文档已变化，未采纳")
        if str(document.version) != str(artifact.get("document_version")):
            raise RuntimeStoreError("全文初稿所属文档版本已变化，未采纳")
        if self._binding(repo, project_id, document) != artifact.get("study_definition"):
            raise RuntimeStoreError("研究设计绑定已变化，未采纳全文初稿")
        candidates = {str(item.get("section_id")): item for item in artifact.get("sections") or []}
        target_by_id = {str(item.get("section_id")): item for item in artifact.get("target_sections") or []}
        if set(candidates) != set(target_by_id):
            raise RuntimeStoreError("全文初稿候选覆盖与目标章节不一致")
        unresolved = [
            section_id
            for section_id, candidate in candidates.items()
            if candidate.get("content_status", "complete") != "complete"
        ]
        if unresolved:
            raise RuntimeStoreError(
                f"仍有 {len(unresolved)} 个章节存在待决定或来源缺口，全文初稿未写入"
            )
        required_review_ids = {
            section_id
            for section_id, candidate in candidates.items()
            if candidate.get("review_level") == "required"
        }
        missing_confirmations = sorted(
            required_review_ids.difference(
                str(item) for item in confirmed_section_ids if str(item).strip()
            )
        )
        if missing_confirmations:
            raise RuntimeStoreError(
                f"仍有 {len(missing_confirmations)} 个高影响章节未逐卡确认，全文初稿未写入"
            )
        adopted: list[str] = []
        replayed: list[str] = []
        for section_id, target in target_by_id.items():
            candidate = candidates[section_id]
            proposal = _text(candidate.get("proposal_text"))
            if (
                len(proposal) < FULL_DRAFT_MINIMUM_BODY_CHARS
                or _PLACEHOLDER_RE.search(proposal)
                or INTERNAL_TRANSPORT_VOCABULARY_RE.search(proposal)
                or DRAFTING_PROCESS_VOCABULARY_RE.search(proposal)
                or next(iter_unresolved_draft_markers(proposal), None)
            ):
                raise RuntimeStoreError(f"全文初稿章节候选不具备实质内容：{section_id}")
            current = repo.working_copy(project_id, section_id)
            blocks = [dict(block) for block in current.content_blocks]
            body_index = next(
                (index for index, block in enumerate(blocks) if str(block.get("block_id")) == str(target.get("body_block_id"))),
                None,
            )
            if body_index is None:
                raise RuntimeStoreError(f"全文初稿目标正文块不存在：{section_id}")
            current_text = _text(blocks[body_index].get("text"))
            if current_text == proposal:
                replayed.append(section_id)
                continue
            if current.revision != int(target.get("expected_revision") or 0):
                raise StaleRuntimeStateError(f"全文初稿采纳遇到章节版本变化：{section_id}")
            if hashlib.sha256(current_text.encode("utf-8")).hexdigest() != str(target.get("body_sha256") or ""):
                raise StaleRuntimeStateError(f"全文初稿采纳遇到正文变化：{section_id}")
            blocks[body_index]["text"] = proposal
            expected_next_revision = current.revision + 1
            saved = repo.save_working_copy(
                project_id,
                section_id,
                MedicalWritingWorkingCopySaveRequest(
                    document_id=document.document_id,
                    expected_revision=current.revision,
                    content_blocks=blocks,
                    actor=actor,
                    idempotency_key=f"full-draft-adopt:{job.job_id}:{section_id}",
                ),
            )
            if saved.revision != expected_next_revision:
                raise RuntimeStoreError(f"全文初稿采纳未形成预期章节版本：{section_id}")
            adopted.append(section_id)
        return {
            "job_id": job.job_id,
            "project_id": project_id,
            "artifact_schema": FULL_DRAFT_ARTIFACT_SCHEMA,
            "adopted_section_ids": adopted,
            "replayed_section_ids": replayed,
            "adopted_count": len(adopted),
            "replayed_count": len(replayed),
            "coverage": artifact.get("coverage") or {},
        }

    @staticmethod
    def _decision_fact_value(fact_path: str, value: str) -> Any:
        """Shape one confirmed prose answer for its authoritative field.

        A decision card's answer is a single confirmed statement.  Scalar
        fields take it as-is; fields the StudyDefinition models declare as
        string lists receive a single-item list, the shape the existing
        adoption validation accepts for that declared field type.
        """
        root, _, rest = fact_path.partition(".")
        model = {
            "framing": MedicalWritingStudyFraming,
            "picos": MedicalWritingPicosDefinition,
        }.get(root)
        if model is None:
            return value
        cursor = model
        parts = [part for part in rest.split(".") if part]
        for index, part in enumerate(parts):
            field = cursor.model_fields.get(part)
            if field is None:
                return value
            annotation = field.annotation
            if index == len(parts) - 1:
                if get_origin(annotation) is list and get_args(annotation) == (str,):
                    return [value]
                return value
            if not hasattr(annotation, "model_fields"):
                return value
            cursor = annotation
        return value

    def resolve_decision(
        self,
        project_id: str,
        durable_store: DurableJobStore,
        job: Any,
        *,
        decisions: Iterable[Mapping[str, Any]],
        idempotency_key: str,
        actor: str = "medical_manager",
        study_definition_writer: Optional[Callable[..., Any]] = None,
    ) -> dict[str, Any]:
        """Resolve full-draft decision cards in one explicit confirmation.

        The answer is written by the existing authoritative StudyDefinition
        confirmation channel handed in as ``study_definition_writer``; this
        service never invents a fact path and never keeps a decision store of
        its own.  A decision item that does not carry an already supported
        authoritative fact path fails closed.

        Resolution order matters and is preserved:

        1. validate every decision against the current immutable artifact;
        2. persist the confirmed answers through the existing channel (CAS plus
           audit live inside that channel);
        3. the persisted StudyDefinition revision invalidates this artifact
           under the existing ``adopt`` binding check — the artifact is never
           rewritten;
        4. submit a new full-draft job scoped to the affected sections only.
        """
        artifact = self.read_artifact(project_id, job)
        if artifact.get("schema_version") != FULL_DRAFT_ARTIFACT_SCHEMA:
            raise RuntimeStoreError(
                "旧版全文初稿候选仅供查阅；请按当前研究事实重新生成后再确认决定"
            )
        service = self._service(project_id)
        repo = service.repo
        document = repo.protocol(project_id)
        if str(document.document_id) != str(artifact.get("document_id")) or str(
            document.version
        ) != str(artifact.get("document_version")):
            raise StaleRuntimeStateError("全文初稿所属文档已变化，决定未写入")
        key = _text(idempotency_key)
        if not key:
            raise ValueError("全文初稿决定确认需要 idempotency_key")
        index = self.decision_index(artifact)
        writer = study_definition_writer
        if writer is None or not callable(writer):
            raise RuntimeStoreError(
                "全文初稿决定尚未绑定研究设计确认通道，未写入任何研究事实"
            )
        submitted = list(decisions)
        if not 1 <= len(submitted) <= 6:
            raise ValueError("一次可确认1至6个相互关联的全文初稿决定")
        resolved: list[dict[str, Any]] = []
        seen: set[str] = set()
        seen_fact_paths: set[str] = set()
        for raw in submitted:
            if not isinstance(raw, Mapping):
                raise ValueError("全文初稿决定必须是对象")
            decision_id = _text(raw.get("decision_id"))
            option_id = _text(raw.get("option_id"))
            if not decision_id or not option_id:
                raise ValueError("全文初稿决定需要 decision_id 与 option_id")
            if decision_id in seen:
                raise ValueError(f"全文初稿决定重复提交：{decision_id}")
            seen.add(decision_id)
            entry = index.get(decision_id)
            if entry is None:
                raise RuntimeStoreError(f"全文初稿候选不存在该决定项：{decision_id}")
            if entry["content_status"] not in {"decision_required", "partial"}:
                raise RuntimeStoreError(
                    f"该章节当前不是待决定状态，不能按决定项确认：{entry['section_id']}"
                )
            item = entry["item"]
            option = next(
                (
                    candidate
                    for candidate in item.get("options") or []
                    if _text(candidate.get("option_id")) == option_id
                ),
                None,
            )
            if option is None:
                raise RuntimeStoreError(
                    f"全文初稿决定项没有该选项：{decision_id}/{option_id}"
                )
            fact_path = _text(item.get("fact_path"))
            if not fact_path:
                raise RuntimeStoreError(
                    "决定项未绑定研究设计字段路径，无法写入权威研究设计；"
                    "请先在既有研究设计流程中确认该决定"
                )
            if fact_path not in SUPPORTED_ADOPT_PATHS:
                raise RuntimeStoreError(
                    f"决定项目标不是既有研究设计字段：{fact_path}"
                )
            if fact_path in seen_fact_paths:
                raise ValueError(f"同一研究字段不能在一组决定中重复确认：{fact_path}")
            seen_fact_paths.add(fact_path)
            if fact_path in _DECISION_STRUCTURED_DESIGN_PATHS:
                raise RuntimeStoreError(
                    f"决定项目标路径需要结构化设计取值，决定卡无法安全写入：{fact_path}；"
                    "请在研究设计中直接确认该决定"
                )
            if (artifact.get("decision_path_owners") or {}).get(fact_path) != entry["section_id"]:
                raise RuntimeStoreError(
                    f"决定项不属于该研究字段的指定章节：{fact_path}"
                )
            prose = _text(option.get("summary")) or _text(option.get("label"))
            resolved.append(
                {
                    "decision_id": decision_id,
                    "section_id": entry["section_id"],
                    "question": _text(item.get("question")),
                    "option_id": option_id,
                    "recommended_option_id": _text(item.get("recommended_option_id")),
                    "fact_path": fact_path,
                    "value": self._decision_fact_value(fact_path, prose),
                }
            )
        if not resolved:
            raise ValueError("全文初稿决定确认为空")

        for entry in resolved:
            value = entry["value"]
            if not value:
                raise RuntimeStoreError(
                    f"决定项选项缺少可写入的实质内容：{entry['decision_id']}"
                )
        journey_binding = artifact.get("authoring_journey") or {}
        expected_journey_revision = journey_binding.get("journey_revision")
        if not isinstance(expected_journey_revision, int):
            raise RuntimeStoreError("全文初稿缺少可恢复的研究确认版本，决定未写入")
        outcome = writer(
            project_id,
            decisions=resolved,
            expected_journey_revision=expected_journey_revision,
            authoring_journey_binding=journey_binding,
            actor=actor,
            idempotency_key=(
                f"full-draft-decision-group:{job.job_id}:{_digest(key)[:24]}"
            ),
        )
        confirmations = [{
            "decision_id": entry["decision_id"],
            "section_id": entry["section_id"],
            "fact_path": entry["fact_path"],
            "option_id": entry["option_id"],
            "study_definition_revision": getattr(
                getattr(outcome, "study_definition", None), "revision", None
            ),
            "journey_revision": getattr(outcome, "revision", None),
        } for entry in resolved]

        affected_section_ids = sorted(
            {entry["section_id"] for entry in resolved}
        )
        regenerated_job_id, reused = self.submit_durable(
            project_id,
            durable_store,
            actor=actor,
            section_ids=affected_section_ids,
        )
        return {
            "job_id": job.job_id,
            "project_id": project_id,
            "artifact_schema": FULL_DRAFT_ARTIFACT_SCHEMA,
            # The written StudyDefinition revision makes this artifact stale for
            # every existing consumer: ``adopt`` already refuses it through the
            # unchanged binding check, and the scoped descriptor guarantees a
            # different durable job.  No artifact byte is rewritten.
            "superseded_job_id": job.job_id,
            "resolved_decisions": resolved,
            "study_definition_confirmations": confirmations,
            "affected_section_ids": affected_section_ids,
            "regeneration": {
                "job_id": regenerated_job_id,
                "reused": bool(reused),
                "section_ids": affected_section_ids,
            },
        }


class ProtocolFullDraftExecutor(DurableJobExecutor):
    job_type = FULL_DRAFT_JOB_TYPE

    def __init__(self, service: MedicalWritingFullDraftService) -> None:
        self.service = service

    def execute(
        self,
        job: Any,
        claim_token: str,
        cancel_check: Callable[[], bool],
        heartbeat: Callable[[DurableJobProgressPayload], bool],
    ) -> DurableJobResult:
        return self.service.run_job(job, claim_token, cancel_check, heartbeat)
