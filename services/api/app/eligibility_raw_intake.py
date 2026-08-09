from __future__ import annotations

import re
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .ai_gateway import AiTaskType, ai_gateway_status_from_env
from .eligibility_review_workflow import eligibility_subject_source_revision
from .protocol_text_extractor import parse_protocol_docx
from .raw_subject_bundle import needs_ocr_vlm_for_source_type, source_type_for_suffix


PathLike = Union[str, Path]
RAW_SOURCE_SYSTEM = "source_registry/raw_source"
FORBIDDEN_LEGACY_INPUTS = [
    "enrollment-review-app",
    "legacy_evidence_bundle",
    "legacy_review_report",
    "legacy_llm_output",
    "legacy_project_reports",
]
ARCHIVE_SUFFIXES = {".7z", ".rar", ".zip"}
SUBJECT_ID_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,3}\d{5})(?!\d)", re.IGNORECASE)


@dataclass(frozen=True)
class RawEligibilityProjectConfig:
    project_id: str
    protocol_path: PathLike
    raw_subject_root: PathLike
    project_label: str = ""
    allowed_roots: Sequence[PathLike] = ()


@dataclass(frozen=True)
class RawEligibilityProtocolSummary:
    filename: str
    title: str
    paragraph_count: int
    table_count: int
    span_count: int

    def public_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "title": self.title,
            "paragraph_count": self.paragraph_count,
            "table_count": self.table_count,
            "span_count": self.span_count,
        }


@dataclass(frozen=True)
class RawEligibilitySubjectPoolSummary:
    total_files: int
    unique_subject_count: int
    source_type_counts: Dict[str, int]
    suffix_counts: Dict[str, int]
    archive_count: int
    needs_ocr_vlm_count: int
    subject_id_prefixes: List[str]
    subject_file_count_min: int
    subject_file_count_max: int
    unassigned_file_count: int

    def public_dict(self) -> Dict[str, Any]:
        return {
            "total_files": self.total_files,
            "unique_subject_count": self.unique_subject_count,
            "source_type_counts": dict(self.source_type_counts),
            "suffix_counts": dict(self.suffix_counts),
            "archive_count": self.archive_count,
            "needs_ocr_vlm_count": self.needs_ocr_vlm_count,
            "subject_id_prefixes": list(self.subject_id_prefixes),
            "subject_file_count_min": self.subject_file_count_min,
            "subject_file_count_max": self.subject_file_count_max,
            "unassigned_file_count": self.unassigned_file_count,
        }


@dataclass(frozen=True)
class RawEligibilityAiTaskPlanItem:
    task_type: str
    module: str
    prompt_version: str
    status: str
    input_source_scopes: List[str]
    forbidden_source_ids: List[str]

    def public_dict(self) -> Dict[str, Any]:
        return {
            "task_type": self.task_type,
            "module": self.module,
            "prompt_version": self.prompt_version,
            "status": self.status,
            "input_source_scopes": list(self.input_source_scopes),
            "forbidden_source_ids": list(self.forbidden_source_ids),
        }


@dataclass(frozen=True)
class RawEligibilitySubjectSource:
    source_id: str
    source_revision: str
    content_hash: str
    source_order: int
    source_type: str
    suffix: str
    size_bytes: int
    extraction_status: str
    requires_visual_fallback: bool
    unit_kind: str
    expected_unit_count: int
    expected_unit_count_status: str

    def public_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "source_order": self.source_order,
            "source_type": self.source_type,
            "suffix": self.suffix,
            "size_bytes": self.size_bytes,
            "extraction_status": self.extraction_status,
            "requires_visual_fallback": self.requires_visual_fallback,
            "unit_kind": self.unit_kind,
            "expected_unit_count": self.expected_unit_count,
            "expected_unit_count_status": self.expected_unit_count_status,
        }


@dataclass(frozen=True)
class RawEligibilitySubjectManifest:
    project_id: str
    subject_id: str
    subject_token: str
    subject_source_revision: str
    file_count: int
    source_type_counts: Dict[str, int]
    pending_visual_fallback_count: int
    sources: List[RawEligibilitySubjectSource]

    def public_dict(self, include_sources: bool = False) -> Dict[str, Any]:
        payload = {
            "project_id": self.project_id,
            "subject_id": self.subject_id,
            "subject_token": self.subject_token,
            "subject_source_revision": self.subject_source_revision,
            "file_count": self.file_count,
            "source_type_counts": dict(self.source_type_counts),
            "pending_visual_fallback_count": self.pending_visual_fallback_count,
        }
        if include_sources:
            payload["sources"] = [source.public_dict() for source in self.sources]
        return payload


@dataclass(frozen=True)
class RawEligibilityProjectSnapshot:
    project_id: str
    project_label: str
    source_system: str
    protocol: RawEligibilityProtocolSummary
    subject_pool: RawEligibilitySubjectPoolSummary
    ai_task_plan: List[RawEligibilityAiTaskPlanItem]
    forbidden_legacy_inputs: List[str]
    ai_gateway_status: Dict[str, Any]

    def public_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_label": self.project_label,
            "source_system": self.source_system,
            "protocol": self.protocol.public_dict(),
            "subject_pool": self.subject_pool.public_dict(),
            "ai_task_plan": [task.public_dict() for task in self.ai_task_plan],
            "forbidden_legacy_inputs": list(self.forbidden_legacy_inputs),
            "ai_gateway_status": {
                "configured": bool(self.ai_gateway_status.get("configured")),
                "provider": str(self.ai_gateway_status.get("provider", "")),
                "model": str(self.ai_gateway_status.get("model", "")),
                "semantic_ai_tasks_enabled": bool(self.ai_gateway_status.get("semantic_ai_tasks_enabled")),
                "codex_runtime_dependency": bool(self.ai_gateway_status.get("codex_runtime_dependency")),
                "missing_env": list(self.ai_gateway_status.get("missing_env", [])),
                "disabled_reason": self.ai_gateway_status.get("disabled_reason"),
            },
        }


class EligibilityRawProjectIntakeService:
    def __init__(self, ai_provider_configured: Optional[bool] = None):
        self.ai_provider_configured = ai_provider_configured

    def discover_project(self, config: RawEligibilityProjectConfig) -> RawEligibilityProjectSnapshot:
        project_id = config.project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        protocol_path = self._resolve_existing_file(config.protocol_path, config.allowed_roots)
        raw_subject_root = self._resolve_existing_directory(config.raw_subject_root, config.allowed_roots)

        protocol = self._protocol_summary(protocol_path)
        subject_pool = self._subject_pool_summary(raw_subject_root)
        ai_gateway_status = ai_gateway_status_from_env()
        if self.ai_provider_configured is not None:
            ai_gateway_status = dict(ai_gateway_status)
            ai_gateway_status["configured"] = self.ai_provider_configured
            ai_gateway_status["semantic_ai_tasks_enabled"] = self.ai_provider_configured
            if not self.ai_provider_configured:
                ai_gateway_status["disabled_reason"] = "external AI provider is not configured"

        return RawEligibilityProjectSnapshot(
            project_id=project_id,
            project_label=config.project_label,
            source_system=RAW_SOURCE_SYSTEM,
            protocol=protocol,
            subject_pool=subject_pool,
            ai_task_plan=self._ai_task_plan(ai_gateway_status),
            forbidden_legacy_inputs=list(FORBIDDEN_LEGACY_INPUTS),
            ai_gateway_status=ai_gateway_status,
        )

    def subject_manifests(self, config: RawEligibilityProjectConfig) -> List[RawEligibilitySubjectManifest]:
        project_id = config.project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        root = self._resolve_existing_directory(config.raw_subject_root, config.allowed_roots)
        return self._subject_manifests(project_id, root)

    def subject_manifest(
        self,
        config: RawEligibilityProjectConfig,
        subject_id: str,
    ) -> RawEligibilitySubjectManifest:
        normalized_subject_id = subject_id.strip().upper()
        if not normalized_subject_id:
            raise ValueError("subject_id is required")
        for manifest in self.subject_manifests(config):
            if manifest.subject_id == normalized_subject_id:
                return manifest
        raise KeyError(normalized_subject_id)

    def resolve_subject_source_path(
        self,
        config: RawEligibilityProjectConfig,
        subject_id: str,
        source_id: str,
        source_revision: str,
    ) -> Path:
        """Resolve an opaque current source identity for a private worker only."""
        project_id = config.project_id.strip()
        normalized_subject_id = subject_id.strip().upper()
        if not all((project_id, normalized_subject_id, source_id, source_revision)):
            raise ValueError("current eligibility source identity is required")
        root = self._resolve_existing_directory(
            config.raw_subject_root, config.allowed_roots
        )
        for file_path in sorted(
            root.rglob("*"), key=lambda path: _relative_sort_key(root, path)
        ):
            if not _is_source_file(root, file_path):
                continue
            if _subject_id_for_path(root, file_path) != normalized_subject_id:
                continue
            candidate_id = _opaque_source_id(
                project_id, normalized_subject_id, root, file_path
            )
            if candidate_id != source_id:
                continue
            candidate_revision = _opaque_source_revision(candidate_id, file_path)
            if candidate_revision != source_revision:
                raise KeyError("eligibility source revision is no longer current")
            return file_path.resolve(strict=True)
        raise KeyError("eligibility source is not current")

    def _protocol_summary(self, protocol_path: Path) -> RawEligibilityProtocolSummary:
        document = parse_protocol_docx(protocol_path.name, protocol_path.read_bytes())
        return RawEligibilityProtocolSummary(
            filename=document.filename,
            title=document.title,
            paragraph_count=len(document.paragraphs),
            table_count=len(document.tables),
            span_count=len(document.spans),
        )

    def _subject_pool_summary(self, root: Path) -> RawEligibilitySubjectPoolSummary:
        total_files = 0
        needs_ocr_vlm_count = 0
        archive_count = 0
        source_type_counts: Counter[str] = Counter()
        suffix_counts: Counter[str] = Counter()
        files_by_subject: Dict[str, int] = defaultdict(int)
        unassigned_file_count = 0

        for file_path in sorted(root.rglob("*"), key=lambda path: _relative_sort_key(root, path)):
            if not _is_source_file(root, file_path):
                continue
            total_files += 1
            suffix = file_path.suffix.lower()
            suffix_key = suffix or "[no_extension]"
            suffix_counts[suffix_key] += 1
            source_type = _source_type_for_suffix(suffix)
            source_type_counts[source_type] += 1
            if suffix in ARCHIVE_SUFFIXES:
                archive_count += 1
            if needs_ocr_vlm_for_source_type(source_type):
                needs_ocr_vlm_count += 1

            subject_id = _subject_id_for_path(root, file_path)
            if subject_id:
                files_by_subject[subject_id] += 1
            else:
                unassigned_file_count += 1

        subject_file_counts = list(files_by_subject.values())
        subject_id_prefixes = sorted({_subject_id_prefix(subject_id) for subject_id in files_by_subject})
        return RawEligibilitySubjectPoolSummary(
            total_files=total_files,
            unique_subject_count=len(files_by_subject),
            source_type_counts=dict(sorted(source_type_counts.items())),
            suffix_counts=dict(sorted(suffix_counts.items())),
            archive_count=archive_count,
            needs_ocr_vlm_count=needs_ocr_vlm_count,
            subject_id_prefixes=subject_id_prefixes,
            subject_file_count_min=min(subject_file_counts) if subject_file_counts else 0,
            subject_file_count_max=max(subject_file_counts) if subject_file_counts else 0,
            unassigned_file_count=unassigned_file_count,
        )

    def _subject_manifests(
        self,
        project_id: str,
        root: Path,
    ) -> List[RawEligibilitySubjectManifest]:
        files_by_subject: Dict[str, List[Path]] = defaultdict(list)
        for file_path in sorted(root.rglob("*"), key=lambda path: _relative_sort_key(root, path)):
            if not _is_source_file(root, file_path):
                continue
            subject_id = _subject_id_for_path(root, file_path)
            if subject_id:
                files_by_subject[subject_id].append(file_path)

        manifests: List[RawEligibilitySubjectManifest] = []
        for subject_id in sorted(files_by_subject):
            source_type_counts: Counter[str] = Counter()
            sources: List[RawEligibilitySubjectSource] = []
            for order, file_path in enumerate(files_by_subject[subject_id], start=1):
                suffix = file_path.suffix.lower()
                source_type = _source_type_for_suffix(suffix)
                visual_fallback = needs_ocr_vlm_for_source_type(source_type)
                source_type_counts[source_type] += 1
                source_id = _opaque_source_id(project_id, subject_id, root, file_path)
                source_revision, content_hash = _source_revision_and_content_hash(
                    source_id, file_path
                )
                unit_kind, expected_unit_count, expected_unit_count_status = (
                    _expected_processing_units(file_path, source_type)
                )
                sources.append(
                    RawEligibilitySubjectSource(
                        source_id=source_id,
                        source_revision=source_revision,
                        content_hash=content_hash,
                        source_order=order,
                        source_type=source_type,
                        suffix=suffix or "[no_extension]",
                        size_bytes=file_path.stat().st_size,
                        extraction_status=_initial_extraction_status(source_type),
                        requires_visual_fallback=visual_fallback,
                        unit_kind=unit_kind,
                        expected_unit_count=expected_unit_count,
                        expected_unit_count_status=expected_unit_count_status,
                    )
                )
            manifests.append(
                RawEligibilitySubjectManifest(
                    project_id=project_id,
                    subject_id=subject_id,
                    subject_token=_opaque_subject_token(project_id, subject_id),
                    subject_source_revision=_opaque_subject_source_revision(
                        project_id,
                        subject_id,
                        sources,
                    ),
                    file_count=len(sources),
                    source_type_counts=dict(sorted(source_type_counts.items())),
                    pending_visual_fallback_count=sum(
                        1 for source in sources if source.requires_visual_fallback
                    ),
                    sources=sources,
                )
            )
        return manifests

    def _ai_task_plan(self, ai_gateway_status: Dict[str, Any]) -> List[RawEligibilityAiTaskPlanItem]:
        status = "ready_external_ai_configured"
        if not ai_gateway_status.get("configured"):
            status = "blocked_external_ai_not_configured"
        return [
            RawEligibilityAiTaskPlanItem(
                task_type=AiTaskType.PROTOCOL_RULE_EXTRACTION.value,
                module="eligibility_review",
                prompt_version="protocol_rule_extraction_v0_1",
                status=status,
                input_source_scopes=["protocol_docx_spans"],
                forbidden_source_ids=list(FORBIDDEN_LEGACY_INPUTS),
            ),
            RawEligibilityAiTaskPlanItem(
                task_type=AiTaskType.ELIGIBILITY_RULE_REVIEW.value,
                module="eligibility_review",
                prompt_version="eligibility_rule_review_v0_1",
                status=status,
                input_source_scopes=["protocol_rules_pending", "raw_subject_file_inventory", "raw_subject_ocr_vlm_pending"],
                forbidden_source_ids=list(FORBIDDEN_LEGACY_INPUTS),
            ),
        ]

    def _resolve_existing_file(self, path: PathLike, allowed_roots: Sequence[PathLike]) -> Path:
        resolved = Path(path).expanduser().resolve()
        self._validate_allowed_root(resolved, allowed_roots)
        if not resolved.exists():
            raise FileNotFoundError(str(resolved))
        if not resolved.is_file():
            raise IsADirectoryError(str(resolved))
        return resolved

    def _resolve_existing_directory(self, path: PathLike, allowed_roots: Sequence[PathLike]) -> Path:
        resolved = Path(path).expanduser().resolve()
        self._validate_allowed_root(resolved, allowed_roots)
        if not resolved.exists():
            raise FileNotFoundError(str(resolved))
        if not resolved.is_dir():
            raise NotADirectoryError(str(resolved))
        return resolved

    def _validate_allowed_root(self, resolved_path: Path, allowed_roots: Sequence[PathLike]) -> None:
        if not allowed_roots:
            return
        allowed = [Path(root).expanduser().resolve() for root in allowed_roots]
        if not any(_is_relative_to(resolved_path, root) for root in allowed):
            raise PermissionError(f"path is outside allowed roots: {resolved_path.name}")


def _source_type_for_suffix(suffix: str) -> str:
    normalized = (suffix or "").lower()
    if normalized in {".7z", ".rar"}:
        return "archive"
    if normalized == ".zip":
        return "archive"
    return source_type_for_suffix(normalized)


def _subject_id_for_path(root: Path, file_path: Path) -> str:
    relative_text = file_path.relative_to(root).as_posix().upper()
    matches = SUBJECT_ID_RE.findall(relative_text)
    if not matches:
        return ""
    return matches[0].upper()


def _subject_id_prefix(subject_id: str) -> str:
    match = re.match(r"[A-Z]+", subject_id)
    return match.group(0) if match else ""


def _opaque_subject_token(project_id: str, subject_id: str) -> str:
    digest = sha256(f"eligibility-subject|{project_id}|{subject_id}".encode("utf-8")).hexdigest()[:16]
    return f"eligsub_{digest}"


def _opaque_source_id(project_id: str, subject_id: str, root: Path, file_path: Path) -> str:
    relative_path = file_path.relative_to(root).as_posix()
    digest = sha256(
        f"eligibility-source|{project_id}|{subject_id}|{relative_path}".encode("utf-8")
    ).hexdigest()[:20]
    return f"eligsrc_{digest}"


def _opaque_source_revision(source_id: str, file_path: Path) -> str:
    return _source_revision_and_content_hash(source_id, file_path)[0]


def _source_revision_and_content_hash(
    source_id: str,
    file_path: Path,
) -> tuple[str, str]:
    for _ in range(2):
        before = file_path.stat()
        content_digest = _file_content_digest_cached(
            str(file_path),
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after = file_path.stat()
        if (
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) == (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            digest = sha256(
                f"eligibility-source-revision|{source_id}|{content_digest}".encode("utf-8")
            ).hexdigest()[:24]
            return f"eligsrcv_{digest}", content_digest
    raise OSError(f"source changed while revision was calculated: {file_path.name}")


@lru_cache(maxsize=4096)
def _file_content_digest_cached(
    path: str,
    size_bytes: int,
    mtime_ns: int,
    ctime_ns: int,
) -> str:
    del size_bytes, mtime_ns, ctime_ns
    digest = sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _opaque_subject_source_revision(
    project_id: str,
    subject_id: str,
    sources: Sequence[RawEligibilitySubjectSource],
) -> str:
    return eligibility_subject_source_revision(
        project_id,
        subject_id,
        [
            {
                "source_id": source.source_id,
                "source_revision": source.source_revision,
                "processing_unit_kind": source.unit_kind,
                "expected_unit_count": source.expected_unit_count,
                "expected_unit_count_status": source.expected_unit_count_status,
            }
            for source in sources
        ],
    )


def _initial_extraction_status(source_type: str) -> str:
    if source_type == "image":
        return "pending_ocr_vlm"
    if source_type == "pdf":
        return "pending_text_extraction_or_ocr"
    if source_type == "archive":
        return "pending_safe_unpack"
    if source_type in {"doc", "docx"}:
        return "pending_text_extraction"
    return "pending_source_classification"


def _expected_processing_units(file_path: Path, source_type: str) -> tuple[str, int, str]:
    if source_type == "pdf":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                import pymupdf
        except ImportError:
            return "page", 0, "unknown_pdf_parser_unavailable"
        try:
            with pymupdf.open(file_path) as document:
                return "page", len(document), "known"
        except Exception:
            return "page", 0, "unknown_unreadable_pdf"
    if source_type == "image":
        return "image", 1, "known"
    if source_type in {"doc", "docx"}:
        return "document", 1, "known"
    if source_type == "archive":
        return "archive_container", 1, "known"
    return "file", 1, "known"


def _is_source_file(root: Path, path: Path) -> bool:
    if not path.is_file():
        return False
    relative_parts = path.relative_to(root).parts
    if any(part.startswith(".") or part == "__MACOSX" for part in relative_parts):
        return False
    if path.name.startswith("~$"):
        return False
    return True


def _relative_sort_key(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix().lower()
    except ValueError:
        return path.as_posix().lower()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
