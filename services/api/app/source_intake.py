from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import replace
from typing import Any, Callable, Dict, List, Sequence

from packages.contracts.workbench_contracts import (
    AiTaskFromRegistryRequest,
    AiTaskRequest,
    ListingSheetPayload,
    SourceRegistrationResult,
    SourceContentValidationConfirmationRequest,
    SourceContentValidationRecord,
    SourceRegistryEntry,
    SourceRegistrySpan,
    WritingReferenceDocumentArtifact,
)

from .ai_gateway import AiSourceRef
from .ai_execution_policy import AiExecutionPolicyResolver
from .listing_file_parser import parse_listing_file
from .protocol_text_extractor import ProtocolTextDocument, parse_protocol_docx
from .raw_subject_bundle import RawSubjectBundleInventory, inventory_subject_bundle
from .source_content_validation import (
    VALIDATOR_VERSION,
    SourceContentValidationService,
    SourceExpectedContext,
)


_FILE_SHA256_CACHE: Dict[tuple[str, int, int, int], str] = {}

REGISTRABLE_LISTING_SUFFIXES = {".csv", ".xls", ".xlsx", ".xlsm"}
REGISTRABLE_PROTOCOL_SUFFIXES = {".docx"}
REGISTRABLE_MEDICAL_WRITING_DOCUMENT_SUFFIXES = {".docx", ".pdf"}
LOCAL_ABSOLUTE_PATH_RE = re.compile(r"/Users/[^\s\"'，,；;）)\]}]+")
SOURCE_ID_NAMESPACE = "workbench_source_registry_v0_1"
MAX_PROTOCOL_REGISTRY_SPANS = 10_000
MAX_EVIDENCE_SPAN_SEARCH_RESULTS = 200
MAX_EVIDENCE_SPAN_SEARCH_TERMS = 32


def protocol_document_to_ai_sources(
    document: ProtocolTextDocument,
    source_id_prefix: str,
    max_spans: int | None = None,
    preview_char_limit: int = 1200,
) -> List[AiSourceRef]:
    """Convert raw protocol text spans into AI source refs without extracting rules."""
    if len(document.spans) > MAX_PROTOCOL_REGISTRY_SPANS:
        raise ValueError(
            "protocol document exceeds the registry hard limit of "
            f"{MAX_PROTOCOL_REGISTRY_SPANS} spans"
        )
    selected_spans = document.spans
    if max_spans is not None:
        if max_spans < 1 or max_spans > MAX_PROTOCOL_REGISTRY_SPANS:
            raise ValueError(
                "max_spans must be between 1 and "
                f"{MAX_PROTOCOL_REGISTRY_SPANS}"
            )
        selected_spans = selected_spans[:max_spans]
    sources: List[AiSourceRef] = []
    for span in selected_spans:
        text = _sanitize_preview_text(span.text[:preview_char_limit])
        sources.append(
            AiSourceRef(
                source_id=f"{source_id_prefix}_{span.span_id}",
                source_type=f"protocol_docx_{span.kind}",
                title=document.title or document.filename,
                locator=span.source_locator,
                text_preview=text,
            )
        )
    return sources


def listing_sheets_to_ai_sources(
    filename: str,
    sheets: Sequence[ListingSheetPayload],
    source_id_prefix: str,
    max_sheets: int = 80,
    max_sample_rows: int = 5,
    max_columns: int = 80,
    preview_char_limit: int = 8000,
) -> List[AiSourceRef]:
    """Expose raw listing sheet headers and bounded sample rows for semantic mapping."""
    sources: List[AiSourceRef] = []
    display_name = Path(filename or "listing").name
    for sheet_index, sheet in enumerate(sheets[:max_sheets], start=1):
        rows = sheet.rows
        headers = _headers_for_rows(rows)[:max_columns]
        sample_rows = [
            {header: _truncate_cell(row.get(header, "")) for header in headers}
            for row in rows[:max_sample_rows]
        ]
        preview = json.dumps(
            {
                "filename": display_name,
                "sheet_name": sheet.sheet_name,
                "row_count": len(rows),
                "headers": headers,
                "sample_rows": sample_rows,
            },
            ensure_ascii=False,
        )
        if len(preview) > preview_char_limit:
            preview = preview[:preview_char_limit] + "...[truncated]"
        sample_end = min(len(rows), max_sample_rows)
        sources.append(
            AiSourceRef(
                source_id=f"{source_id_prefix}_sheet_{sheet_index:03d}",
                source_type="listing_sheet",
                title=f"{display_name} / {sheet.sheet_name}",
                locator=f"listing:sheet:{sheet_index}:sample_rows:1-{sample_end}",
                text_preview=preview,
            )
        )
    return sources


def raw_subject_inventory_to_ai_sources(
    inventory: RawSubjectBundleInventory,
    source_id_prefix: str,
) -> List[AiSourceRef]:
    """Expose raw subject file metadata without leaking conclusion-like filenames."""
    sources: List[AiSourceRef] = []
    for index, file in enumerate(inventory.files, start=1):
        source_id = f"{source_id_prefix}_file_{index:03d}"
        sources.append(
            AiSourceRef(
                source_id=source_id,
                source_type=f"raw_subject_{file.source_type}",
                title=f"raw_subject_file_{index:03d}{file.suffix}",
                locator=f"raw_subject_file:{index:03d}",
                text_preview=(
                    f"source_id={source_id}; type={file.source_type}; "
                    f"size_bytes={file.size_bytes}; needs_ocr_vlm={file.needs_ocr_vlm}"
                ),
            )
        )
    return sources


def file_bundle_inventory_to_ai_sources(
    inventory: RawSubjectBundleInventory,
    source_id_prefix: str,
) -> List[AiSourceRef]:
    """Expose a generic local directory inventory without absolute paths."""
    sources: List[AiSourceRef] = []
    for index, file in enumerate(inventory.files, start=1):
        source_id = f"{source_id_prefix}_file_{index:03d}"
        sources.append(
            AiSourceRef(
                source_id=source_id,
                source_type=f"file_bundle_{file.source_type}",
                title=f"source_file_{index:03d}{file.suffix}",
                locator=f"file_bundle:{index:03d}",
                text_preview=(
                    f"source_id={source_id}; type={file.source_type}; suffix={file.suffix}; "
                    f"size_bytes={file.size_bytes}; needs_ocr_vlm={file.needs_ocr_vlm}"
                ),
            )
        )
    return sources


class SourceRegistryStore:
    def __init__(self, jsonl_path: Path):
        self.jsonl_path = jsonl_path

    def append(self, result: SourceRegistrationResult) -> None:
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        incoming_identity = _registration_identity(result)
        for existing in self._read_all():
            if existing.entry.entry_id != result.entry.entry_id:
                continue
            if _registration_identity(existing) == incoming_identity:
                return
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def list_results(self, project_id: str) -> List[SourceRegistrationResult]:
        return [result for result in self._read_all() if result.entry.project_id == project_id]

    def list_entries(self, project_id: str) -> List[SourceRegistryEntry]:
        entries_by_id: Dict[str, SourceRegistryEntry] = {}
        source_ids_by_entry: Dict[str, set[str]] = {}
        for result in self.list_results(project_id):
            entries_by_id.setdefault(result.entry.entry_id, result.entry)
            source_ids_by_entry.setdefault(result.entry.entry_id, set()).update(
                span.source_id for span in result.spans
            )
        return [
            entry.model_copy(
                update={"span_count": len(source_ids_by_entry.get(entry_id, set()))}
            )
            for entry_id, entry in entries_by_id.items()
        ]

    def list_spans(self, project_id: str) -> List[SourceRegistrySpan]:
        return [span for result in self.list_results(project_id) for span in result.spans]

    def get_spans(self, project_id: str, source_ids: Sequence[str]) -> List[SourceRegistrySpan]:
        requested = list(dict.fromkeys(source_ids))
        spans_by_id: Dict[str, List[SourceRegistrySpan]] = {}
        for span in self.list_spans(project_id):
            spans_by_id.setdefault(span.source_id, []).append(span)
        missing = [source_id for source_id in requested if source_id not in spans_by_id]
        if missing:
            raise KeyError(f"source ids not registered for project {project_id}: {missing}")
        ambiguous = [
            source_id
            for source_id in requested
            if len({_source_span_identity(span) for span in spans_by_id[source_id]}) != 1
        ]
        if ambiguous:
            raise ValueError(
                f"ambiguous registered source ids for project {project_id}: {ambiguous}"
            )
        return [spans_by_id[source_id][-1] for source_id in requested]

    def _read_all(self) -> List[SourceRegistrationResult]:
        if not self.jsonl_path.exists():
            return []
        results: List[SourceRegistrationResult] = []
        with self.jsonl_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                results.append(SourceRegistrationResult.model_validate(json.loads(line)))
        return results


class SourceRegistryService:
    def __init__(
        self,
        store: SourceRegistryStore,
        allowed_roots: Sequence[Path] | None = None,
        *,
        artifact_root: Path | None = None,
        content_validation_service: SourceContentValidationService | None = None,
        expected_context_resolver: Callable[[str, str, str], SourceExpectedContext] | None = None,
    ):
        self.store = store
        self.allowed_roots = [root.expanduser().resolve() for root in (allowed_roots or [])]
        self.artifact_root = Path(artifact_root) if artifact_root is not None else None
        if self.artifact_root is not None:
            self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.content_validation_service = content_validation_service
        self.expected_context_resolver = expected_context_resolver

    def register_protocol_docx(
        self,
        project_id: str,
        filename: str,
        content: bytes,
        module: str = "eligibility_review",
        expected_file_role: str = "",
    ) -> SourceRegistrationResult:
        document = parse_protocol_docx(filename, content)
        content_hash = _sha256_bytes(content)
        entry = self._entry(
            project_id=project_id,
            module=module,
            source_kind="protocol_docx",
            public_title=_document_public_title(document.title, filename),
            content_hash=content_hash,
            size_bytes=len(content),
            metadata={
                "filename": Path(filename).name,
                "paragraph_count": len(document.paragraphs),
                "table_count": len(document.tables),
                "span_count": len(document.spans),
            },
        )
        refs = protocol_document_to_ai_sources(document, entry.entry_id)
        result = self._result_from_refs(entry, refs)
        self.store.append(result)
        self._assess_protocol(
            result,
            filename,
            document,
            content_hash,
            expected_file_role=expected_file_role,
        )
        return result

    def register_protocol_selection(
        self,
        project_id: str,
        filename: str,
        content: bytes,
        locator: str,
        quote: str,
        module: str = "medical_writing",
    ) -> SourceRegistrationResult:
        """Register one verified protocol selection without registering a truncated prefix."""
        if module != "medical_writing":
            raise ValueError("protocol selection registration is restricted to medical_writing")
        normalized_quote = quote.strip()
        if not normalized_quote:
            raise ValueError("protocol selection quote is required")

        document = parse_protocol_docx(filename, content)
        source_span = _protocol_selection_span(document, locator, normalized_quote)
        safe_quote = _sanitize_preview_text(normalized_quote)
        if safe_quote != normalized_quote:
            raise ValueError("protocol selection contains a local path and cannot be registered")

        content_hash = _sha256_bytes(content)
        document_token = _sha256_text(Path(filename).name)[:16]
        entry = self._entry(
            project_id=project_id,
            module=module,
            source_kind="protocol_docx_selection",
            public_title=_document_public_title(document.title, filename),
            content_hash=content_hash,
            size_bytes=len(content),
            metadata={
                "filename": Path(filename).name,
                "document_token": document_token,
                "paragraph_count": len(document.paragraphs),
                "table_count": len(document.tables),
                "source_span_id": source_span.span_id,
            },
        )
        selection_token = _sha256_text(
            f"{entry.entry_id}|{source_span.span_id}|{source_span.source_locator}|{safe_quote}"
        )[:16]
        ref = AiSourceRef(
            source_id=f"{entry.entry_id}_selection_{selection_token}",
            source_type=f"protocol_docx_{source_span.kind}_selection",
            title=document.title or Path(filename).name,
            locator=source_span.source_locator,
            text_preview=safe_quote,
        )
        result = self._result_from_refs(entry, [ref])
        result = result.model_copy(
            update={
                "spans": [
                    result.spans[0].model_copy(
                        update={
                            "metadata": {
                                "document_token": document_token,
                                "source_span_id": source_span.span_id,
                            }
                        }
                    )
                ]
            }
        )
        self.store.append(result)
        return result

    def register_protocol_selection_from_file(
        self,
        project_id: str,
        file_path: Path | str,
        locator: str,
        quote: str,
        module: str = "medical_writing",
    ) -> SourceRegistrationResult:
        path = self._resolve_allowed_file(file_path)
        if path.suffix.lower() not in REGISTRABLE_PROTOCOL_SUFFIXES:
            raise ValueError(
                f"unsupported protocol selection file type: {path.suffix.lower() or 'unknown'}"
            )
        return self.register_protocol_selection(
            project_id,
            path.name,
            path.read_bytes(),
            locator=locator,
            quote=quote,
            module=module,
        )

    def register_medical_writing_document(
        self,
        project_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        *,
        document_role: str,
        expected_indication: str = "",
    ) -> SourceRegistrationResult:
        """Register a user-supplied writing source as parsed, citable evidence.

        This path is intentionally limited to basic file/content validation.
        It supports the optional investigator-brochure intake without making
        source admission a separate heavyweight workflow.
        """
        role = document_role.strip()
        if role != "investigator_brochure":
            raise ValueError(f"unsupported medical-writing document role: {role}")
        if not content:
            raise ValueError("medical-writing source file is empty")
        if len(content) > 50 * 1024 * 1024:
            raise ValueError("medical-writing source file exceeds 50 MiB")
        suffix = Path(filename).suffix.lower()
        if suffix not in REGISTRABLE_MEDICAL_WRITING_DOCUMENT_SUFFIXES:
            raise ValueError("medical-writing source must be a PDF or DOCX file")
        if suffix == ".pdf" and not content.startswith(b"%PDF-"):
            raise ValueError("selected PDF file cannot be read as a PDF")
        if suffix == ".docx" and not content.startswith(b"PK"):
            raise ValueError("selected DOCX file cannot be read as a DOCX")

        # Reuse the document extractors already used by the protocol-reference
        # workflow so the registered evidence has stable page/paragraph locators.
        from .writing_reference import extract_pdf_sections
        from .writing_reference_docx import extract_docx_sections

        content_hash = _sha256_bytes(content)
        source_id = (
            "mwsource_"
            + _opaque_source_token(project_id, "medical_writing", role, content_hash)
        )
        now = datetime.now(timezone.utc)
        artifact = WritingReferenceDocumentArtifact(
            artifact_id=source_id,
            project_id=project_id,
            snapshot_id="project_source_intake",
            nct_id=project_id,
            source_document_id=source_id,
            document_type=role,
            filename=Path(filename).name,
            requested_url="user-upload",
            final_url="user-upload",
            content_type=(
                "application/pdf"
                if suffix == ".pdf"
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            declared_size=len(content),
            actual_size=len(content),
            content_sha256=content_hash,
            source_status="user_uploaded",
            created_by="medical_manager",
            created_at=now,
        )
        extracted = (
            extract_pdf_sections(content, artifact)
            if suffix == ".pdf"
            else extract_docx_sections(content, artifact)
        )
        if not extracted.spans:
            raise ValueError("medical-writing source contains no extractable text")
        full_text = "\n".join(
            span.source_text for span in extracted.spans if span.source_text.strip()
        )
        validation = _medical_writing_document_validation(
            role,
            full_text,
            expected_indication,
        )
        storage_key = ""
        if self.artifact_root is not None:
            project_token = _slug(project_id)
            storage_key = f"{project_token}/{role}/{content_hash}{suffix}"
            output_path = self.artifact_root / storage_key
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if output_path.exists():
                if _sha256_file(output_path) != content_hash:
                    raise RuntimeError("existing medical-writing source hash does not match")
            else:
                output_path.write_bytes(content)

        entry = self._entry(
            project_id=project_id,
            module="medical_writing",
            source_kind=role,
            public_title=Path(filename).name,
            content_hash=content_hash,
            size_bytes=len(content),
            metadata={
                "filename": Path(filename).name,
                "media_type": artifact.content_type,
                "document_role": role,
                "parser_name": extracted.parser_name,
                "parser_version": extracted.parser_version,
                "page_count": extracted.page_count,
                "extraction_revision": extracted.extraction_revision,
                "content_validation": validation,
            },
            server_path=storage_key,
        )
        refs = [
            AiSourceRef(
                source_id=f"{entry.entry_id}_{span.span_id}",
                source_type=f"{role}_span",
                title=Path(filename).name,
                locator=span.source_locator,
                text_preview=_sanitize_preview_text(span.source_text[:6000]),
            )
            for span in extracted.spans[:240]
            if span.source_text.strip()
        ]
        result = self._result_from_refs(entry, refs)
        self.store.append(result)
        return result

    def register_listing_file(
        self,
        project_id: str,
        filename: str,
        content: bytes,
        module: str = "medical_monitoring",
        expected_file_role: str = "",
        parsed_sheets: Sequence[ListingSheetPayload] | None = None,
    ) -> SourceRegistrationResult:
        sheets = list(parsed_sheets) if parsed_sheets is not None else parse_listing_file(filename, content)
        content_hash = _sha256_bytes(content)
        entry = self._entry(
            project_id=project_id,
            module=module,
            source_kind=expected_file_role or "listing_file",
            public_title=Path(filename).name,
            content_hash=content_hash,
            size_bytes=len(content),
            metadata={
                "filename": Path(filename).name,
                "sheet_count": len(sheets),
                "row_count": sum(len(sheet.rows) for sheet in sheets),
                "parser_warnings": sorted(
                    {
                        warning
                        for sheet in sheets
                        for warning in sheet.parser_warnings
                    }
                ),
            },
        )
        refs = listing_sheets_to_ai_sources(filename, sheets, entry.entry_id)
        result = self._result_from_refs(entry, refs)
        self.store.append(result)
        self._assess_listing(
            result,
            filename,
            sheets,
            content_hash,
            expected_file_role=expected_file_role,
        )
        return result

    def register_raw_subject_bundle(
        self,
        project_id: str,
        root_path: Path | str,
        module: str = "eligibility_review",
    ) -> SourceRegistrationResult:
        root = self._resolve_allowed_root(root_path)
        inventory = inventory_subject_bundle(root)
        content_hash = _bundle_content_hash(inventory)
        entry = self._entry(
            project_id=project_id,
            module=module,
            source_kind="raw_subject_bundle_inventory",
            public_title="原始受试者资料包清单",
            content_hash=content_hash,
            size_bytes=sum(file.size_bytes for file in inventory.files),
            parser_status="inventory_only",
            metadata={
                "total_files": inventory.total_files,
                "source_type_counts": inventory.source_type_counts,
                "needs_ocr_vlm_count": inventory.needs_ocr_vlm_count,
                "evidence_status": "metadata_only_pending_ocr_vlm",
            },
            server_path=str(root),
        )
        refs = raw_subject_inventory_to_ai_sources(inventory, entry.entry_id)
        result = self._result_from_refs(entry, refs)
        self.store.append(result)
        self._assess_inventory(result, inventory, content_hash)
        return result

    def register_local_directory(
        self,
        project_id: str,
        root_path: Path | str,
        module: str,
        source_kind: str = "file_bundle_inventory",
    ) -> SourceRegistrationResult:
        root = self._resolve_allowed_root(root_path)
        inventory = inventory_subject_bundle(root)
        content_hash = _bundle_content_hash(inventory)
        entry = self._entry(
            project_id=project_id,
            module=module,
            source_kind=source_kind,
            public_title=_inventory_public_title(source_kind),
            content_hash=content_hash,
            size_bytes=sum(file.size_bytes for file in inventory.files),
            parser_status="inventory_only",
            metadata={
                "total_files": inventory.total_files,
                "source_type_counts": inventory.source_type_counts,
                "needs_ocr_vlm_count": inventory.needs_ocr_vlm_count,
                "evidence_status": "metadata_only_pending_parser",
            },
            server_path=str(root),
        )
        refs = file_bundle_inventory_to_ai_sources(inventory, entry.entry_id)
        result = self._result_from_refs(entry, refs)
        self.store.append(result)
        self._assess_inventory(result, inventory, content_hash)
        return result

    def register_local_file(
        self,
        project_id: str,
        file_path: Path | str,
        module: str,
        expected_file_role: str = "",
    ) -> SourceRegistrationResult:
        path = self._resolve_allowed_file(file_path)
        suffix = path.suffix.lower()
        content = path.read_bytes()
        if suffix in REGISTRABLE_PROTOCOL_SUFFIXES:
            return self.register_protocol_docx(
                project_id,
                path.name,
                content,
                module=module,
                expected_file_role=expected_file_role,
            )
        if suffix in REGISTRABLE_LISTING_SUFFIXES:
            return self.register_listing_file(
                project_id,
                path.name,
                content,
                module=module,
                expected_file_role=expected_file_role,
            )
        raise ValueError(f"unsupported local source file type for registry: {suffix or 'unknown'}")

    def reusable_local_file_registration(
        self,
        project_id: str,
        file_path: Path | str,
        *,
        module: str,
        expected_file_role: str,
    ) -> SourceRegistrationResult | None:
        path = self._resolve_allowed_file(file_path)
        content_hash = _sha256_file(path)
        candidates = [
            result
            for result in self.store.list_results(project_id)
            if result.entry.module == module
            and result.entry.source_kind == expected_file_role
            and result.entry.content_hash == content_hash
        ]
        if not candidates:
            return None
        current = max(candidates, key=lambda result: result.entry.created_at)
        if self.content_validation_service is None:
            return current
        validation = self.current_content_validation(project_id, current.entry.entry_id)
        if validation is None or validation.validator_version != VALIDATOR_VERSION:
            return None
        if self.expected_context_resolver is not None:
            expected = self.expected_context_resolver(project_id, module, expected_file_role)
            if validation.expected_context_hash != expected.context_hash:
                return None
        return current

    def list_entries(self, project_id: str) -> List[SourceRegistryEntry]:
        return self.store.list_entries(project_id)

    def list_spans(self, project_id: str) -> List[SourceRegistrySpan]:
        return self.store.list_spans(project_id)

    def search_protocol_spans(
        self,
        project_id: str,
        entry_id: str,
        query_terms: Sequence[str],
        *,
        limit: int = 50,
        required_module: str = "medical_monitoring",
    ) -> List[Dict[str, Any]]:
        """Search current registered protocol text without making medical claims."""
        if limit < 1 or limit > MAX_EVIDENCE_SPAN_SEARCH_RESULTS:
            raise ValueError(
                "evidence span search limit must be between 1 and "
                f"{MAX_EVIDENCE_SPAN_SEARCH_RESULTS}"
            )
        terms = _normalized_evidence_search_terms(query_terms)
        entries = self.list_entries(project_id)
        entry = next((item for item in entries if item.entry_id == entry_id), None)
        if entry is None:
            raise KeyError(
                f"source entry not registered for project {project_id}: {entry_id}"
            )
        if entry.module != required_module:
            raise ValueError(
                "source entry is outside the medical-monitoring module boundary"
            )
        if entry.source_kind != "protocol_docx":
            raise ValueError(
                "evidence span search requires a registered protocol document"
            )

        current = max(
            (
                item
                for item in entries
                if item.module == entry.module
                and item.source_kind == entry.source_kind
            ),
            key=lambda item: (item.created_at, item.entry_id),
        )
        if current.entry_id != entry.entry_id:
            raise ValueError(
                "superseded registered protocol is not allowed for "
                f"medical-monitoring evidence search: {entry.entry_id}"
            )

        spans_by_id: Dict[str, SourceRegistrySpan] = {}
        identities_by_id: Dict[str, set[tuple]] = {}
        for span in self.list_spans(project_id):
            if span.entry_id != entry.entry_id:
                continue
            if span.module != required_module or span.project_id != project_id:
                continue
            identities_by_id.setdefault(span.source_id, set()).add(
                _source_span_identity(span)
            )
            spans_by_id[span.source_id] = span
        if not spans_by_id:
            return []
        ambiguous = [
            source_id
            for source_id, identities in identities_by_id.items()
            if len(identities) != 1
        ]
        if ambiguous:
            raise ValueError(
                "ambiguous registered protocol spans for evidence search: "
                f"{sorted(ambiguous)[:5]}"
            )

        self._assert_registered_sources_usable(
            project_id,
            [next(iter(spans_by_id))],
        )
        matches: List[Dict[str, Any]] = []
        for span in spans_by_id.values():
            searchable = span.text_preview.casefold()
            matched = [
                (display, normalized, searchable.count(normalized))
                for display, normalized in terms
                if normalized in searchable
            ]
            if not matched:
                continue
            occurrence_count = sum(item[2] for item in matched)
            score = len(matched) * 1_000 + min(occurrence_count, 999)
            matched_keywords = [item[0] for item in matched]
            matches.append(
                {
                    "source_id": span.source_id,
                    "source_entry_id": entry.entry_id,
                    "locator": span.locator,
                    "text": span.text_preview,
                    "score": score,
                    "matched_keywords": matched_keywords,
                    "match_reason": (
                        "命中关键词："
                        + "、".join(matched_keywords)
                        + f"；共出现 {occurrence_count} 次"
                    ),
                }
            )
        matches.sort(
            key=lambda item: (
                -int(item["score"]),
                str(item["locator"]).casefold(),
                str(item["source_id"]).casefold(),
            )
        )
        return matches[:limit]

    def current_content_validation(
        self,
        project_id: str,
        source_entry_id: str,
    ) -> SourceContentValidationRecord | None:
        if self.content_validation_service is None:
            return None
        return self.content_validation_service.store.current_or_none(project_id, source_entry_id)

    def content_validation_history(
        self,
        project_id: str,
        source_entry_id: str,
    ) -> List[SourceContentValidationRecord]:
        if self.content_validation_service is None:
            return []
        return self.content_validation_service.store.history(project_id, source_entry_id)

    def confirm_content_validation(
        self,
        project_id: str,
        source_entry_id: str,
        request: SourceContentValidationConfirmationRequest,
    ) -> SourceContentValidationRecord:
        if self.content_validation_service is None:
            raise RuntimeError("source content validation is not configured")
        entries = {entry.entry_id for entry in self.store.list_entries(project_id)}
        if source_entry_id not in entries:
            raise KeyError(source_entry_id)
        return self.content_validation_service.confirm_after_warning(
            project_id,
            source_entry_id,
            request,
        )

    def latest_entry_id(
        self,
        project_id: str,
        module: str,
        source_kind: str,
        document_token: str,
    ) -> str:
        candidates = [
            result.entry
            for result in self.store.list_results(project_id)
            if result.entry.module == module
            and result.entry.source_kind == source_kind
            and result.entry.metadata.get("document_token") == document_token
        ]
        if not candidates:
            raise KeyError("registered source document version is unavailable")
        return max(candidates, key=lambda entry: entry.created_at).entry_id

    def ai_task_request_from_registry(
        self,
        project_id: str,
        request: AiTaskFromRegistryRequest,
        policy_resolver: AiExecutionPolicyResolver | None = None,
    ) -> AiTaskRequest:
        self._assert_registered_sources_usable(project_id, request.source_ids)
        resolution = (policy_resolver or AiExecutionPolicyResolver()).resolve_registered(
            project_id, request, self
        )
        return AiTaskRequest(
            module=resolution.module,
            task_type=resolution.task_type.value,
            prompt_version=resolution.prompt_version,
            allowed_sources=resolution.allowed_sources,
            forbidden_source_ids=resolution.forbidden_source_ids,
            user_instruction=resolution.user_instruction,
        )

    def _assert_registered_sources_usable(
        self,
        project_id: str,
        source_ids: Sequence[str],
    ) -> None:
        if self.content_validation_service is None:
            return
        operational_modules = {
            "eligibility_review",
            "medical_monitoring",
            "data_analysis_tfl",
            "safety_pv",
        }
        entries = self.list_entries(project_id)
        for span in self.store.get_spans(project_id, source_ids):
            validation = self.current_content_validation(project_id, span.entry_id)
            if validation is None:
                continue
            if validation.validator_version != VALIDATOR_VERSION:
                raise ValueError(
                    "registered source validation is stale and must be refreshed before AI use: "
                    f"{span.entry_id}/{validation.validator_version}"
                )
            entry = next((item for item in entries if item.entry_id == span.entry_id), None)
            if entry is None:
                raise ValueError(f"registered source entry is unavailable: {span.entry_id}")
            if self.expected_context_resolver is not None:
                expected = self.expected_context_resolver(project_id, entry.module, entry.source_kind)
                if validation.expected_context_hash != expected.context_hash:
                    raise ValueError(
                        "registered source project context changed and must be refreshed before AI use: "
                        f"{span.entry_id}"
                    )
            if entry.module in operational_modules:
                latest = max(
                    (
                        item
                        for item in entries
                        if item.module == entry.module and item.source_kind == entry.source_kind
                    ),
                    key=lambda item: item.created_at,
                )
                if latest.entry_id != entry.entry_id:
                    raise ValueError(
                        "superseded registered source is not allowed for operational AI use: "
                        f"{entry.entry_id}"
                    )
            if validation.use_status not in {"allowed", "confirmed_after_warning"}:
                raise ValueError(
                    "registered source requires content-consistency confirmation before AI use: "
                    f"{span.entry_id}/{validation.use_status}"
                )

    def _entry(
        self,
        project_id: str,
        module: str,
        source_kind: str,
        public_title: str,
        content_hash: str,
        size_bytes: int,
        metadata: Dict[str, Any],
        parser_status: str = "parsed",
        server_path: str = "",
    ) -> SourceRegistryEntry:
        now = datetime.now(timezone.utc)
        entry_id = (
            f"src_{_slug(project_id)}_{source_kind}_"
            f"{_opaque_source_token(project_id, module, source_kind, content_hash)}"
        )
        return SourceRegistryEntry(
            entry_id=entry_id,
            project_id=project_id,
            module=module,
            source_kind=source_kind,
            public_title=_public_title(public_title),
            content_hash=content_hash,
            size_bytes=size_bytes,
            parser_status=parser_status,
            span_count=0,
            metadata=metadata,
            server_path=server_path,
            created_at=now,
        )

    def _assess_listing(
        self,
        result: SourceRegistrationResult,
        filename: str,
        sheets: Sequence[ListingSheetPayload],
        content_hash: str,
        *,
        expected_file_role: str = "",
    ) -> None:
        if self.content_validation_service is None or self.expected_context_resolver is None:
            return
        expected = self.expected_context_resolver(
            result.entry.project_id,
            result.entry.module,
            result.entry.source_kind,
        )
        if expected_file_role:
            expected = replace(expected, expected_file_role=expected_file_role)
        self.content_validation_service.assess_listing(
            project_id=result.entry.project_id,
            source_entry_id=result.entry.entry_id,
            module=result.entry.module,
            filename=filename,
            file_sha256=content_hash,
            sheets=sheets,
            expected=expected,
            actor="system_validator",
        )

    def _assess_protocol(
        self,
        result: SourceRegistrationResult,
        filename: str,
        document: ProtocolTextDocument,
        content_hash: str,
        *,
        expected_file_role: str = "",
    ) -> None:
        if self.content_validation_service is None or self.expected_context_resolver is None:
            return
        expected = self.expected_context_resolver(
            result.entry.project_id,
            result.entry.module,
            result.entry.source_kind,
        )
        if expected_file_role:
            expected = replace(expected, expected_file_role=expected_file_role)
        self.content_validation_service.assess_protocol(
            project_id=result.entry.project_id,
            source_entry_id=result.entry.entry_id,
            module=result.entry.module,
            filename=filename,
            file_sha256=content_hash,
            document=document,
            expected=expected,
            actor="system_validator",
        )

    def _assess_inventory(
        self,
        result: SourceRegistrationResult,
        inventory: RawSubjectBundleInventory,
        content_hash: str,
    ) -> None:
        if self.content_validation_service is None or self.expected_context_resolver is None:
            return
        expected = self.expected_context_resolver(
            result.entry.project_id,
            result.entry.module,
            result.entry.source_kind,
        )
        self.content_validation_service.assess_inventory(
            project_id=result.entry.project_id,
            source_entry_id=result.entry.entry_id,
            module=result.entry.module,
            inventory=inventory,
            file_sha256=content_hash,
            expected=expected,
            actor="system_validator",
        )

    def _result_from_refs(self, entry: SourceRegistryEntry, refs: Sequence[AiSourceRef]) -> SourceRegistrationResult:
        now = datetime.now(timezone.utc)
        spans = [
            SourceRegistrySpan(
                source_id=ref.source_id,
                entry_id=entry.entry_id,
                project_id=entry.project_id,
                module=entry.module,
                source_type=ref.source_type,
                title=ref.title,
                locator=ref.locator,
                text_preview=ref.text_preview,
                preview_hash=_sha256_text(ref.text_preview),
                metadata={},
                created_at=now,
            )
            for ref in refs
        ]
        return SourceRegistrationResult(entry=entry.model_copy(update={"span_count": len(spans)}), spans=spans)

    def _resolve_allowed_root(self, root_path: Path | str) -> Path:
        root = Path(root_path).expanduser().resolve()
        if not self.allowed_roots:
            return root
        if any(root == allowed or root.is_relative_to(allowed) for allowed in self.allowed_roots):
            return root
        raise ValueError("raw subject bundle path is outside configured allowed roots")

    def _resolve_allowed_file(self, file_path: Path | str) -> Path:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(str(path))
        if not path.is_file():
            raise ValueError(f"source path is not a file: {path}")
        if not self.allowed_roots:
            return path
        if any(path == allowed or path.is_relative_to(allowed) for allowed in self.allowed_roots):
            return path
        raise ValueError("source file path is outside configured allowed roots")


def _headers_for_rows(rows: Sequence[Dict[str, Any]]) -> List[str]:
    headers: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in headers:
                headers.append(key)
    return headers


def _bundle_content_hash(inventory: RawSubjectBundleInventory) -> str:
    fingerprint = []
    for file in inventory.files:
        fingerprint.append(
            {
                "relative_path": file.relative_path,
                "suffix": file.suffix,
                "size_bytes": file.size_bytes,
                "source_type": file.source_type,
                "needs_ocr_vlm": file.needs_ocr_vlm,
                "file_sha256": _sha256_file(Path(file.path)),
            }
        )
    return _sha256_text(json.dumps(fingerprint, sort_keys=True, ensure_ascii=False))


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    stat = path.stat()
    cache_key = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    cached = _FILE_SHA256_CACHE.get(cache_key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    value = digest.hexdigest()
    if len(_FILE_SHA256_CACHE) > 10000:
        _FILE_SHA256_CACHE.clear()
    _FILE_SHA256_CACHE[cache_key] = value
    return value


def _truncate_cell(value: Any, limit: int = 160) -> str:
    text = _sanitize_preview_text("" if value is None else str(value))
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _sanitize_preview_text(text: str) -> str:
    return LOCAL_ABSOLUTE_PATH_RE.sub("[local_path_redacted]", text)


def _protocol_selection_span(
    document: ProtocolTextDocument,
    locator: str,
    quote: str,
):
    paragraph_match = re.fullmatch(r"docx:paragraph:(\d+)", locator.strip())
    paragraph_index = int(paragraph_match.group(1)) if paragraph_match else None
    locator_matches = [
        span
        for span in document.spans
        if span.source_locator == locator
        or (paragraph_index is not None and span.paragraph_index == paragraph_index)
    ]
    if not locator_matches:
        raise ValueError("protocol selection locator is not present in the original DOCX")
    quote_matches = [span for span in locator_matches if quote in span.text]
    if len(quote_matches) != 1:
        if not quote_matches:
            raise ValueError("protocol selection quote does not match the original DOCX locator")
        raise ValueError("protocol selection locator and quote are ambiguous")
    return quote_matches[0]


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _opaque_source_token(
    project_id: str,
    module: str,
    source_kind: str,
    content_hash: str,
) -> str:
    seed = f"{SOURCE_ID_NAMESPACE}:{project_id}:{module}:{source_kind}:{content_hash}"
    return _sha256_text(seed)[:12]


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    return slug or "project"


def _public_title(title: str) -> str:
    return Path(title or "source").name


def _document_public_title(document_title: str, filename: str) -> str:
    title = _public_title(document_title).strip()
    if len(title) >= 4 and not title.isdigit():
        return title
    return Path(filename).name


def _inventory_public_title(source_kind: str) -> str:
    return {
        "raw_subject_bundle_inventory": "原始受试者资料包清单",
        "file_bundle_inventory": "原始资料包清单",
        "tfl_dataset_package_inventory": "数据集与TFL资料包清单",
        "tfl_output_package_inventory": "TFL输出资料包清单",
        "safety_signal_package_inventory": "安全性评估资料包清单",
        "pv_safety_package_inventory": "PV计划资料包清单",
        "clinical_safety_summary_inventory": "临床安全性总结资料包清单",
    }.get(source_kind, f"{source_kind}_清单")


def _medical_writing_document_validation(
    document_role: str,
    full_text: str,
    expected_indication: str,
) -> Dict[str, Any]:
    normalized = re.sub(r"\s+", " ", full_text).casefold()
    role_markers = (
        "研究者手册",
        "研究者资料手册",
        "investigator's brochure",
        "investigators brochure",
        "investigator brochure",
        "summary of data and guidance for the investigator",
    )
    supporting_markers = (
        "非临床研究",
        "nonclinical studies",
        "临床试验经验",
        "effects in humans",
        "安全性信息",
        "safety information",
        "药代动力学",
        "pharmacokinetics",
    )
    competing_role_markers = (
        "clinical study protocol",
        "临床试验方案",
        "statistical analysis plan",
        "统计分析计划",
        "publication",
        "discussion",
    )
    role_hits = [marker for marker in role_markers if marker.casefold() in normalized]
    supporting_hits = [
        marker for marker in supporting_markers if marker.casefold() in normalized
    ]
    competing_hits = [
        marker for marker in competing_role_markers if marker.casefold() in normalized
    ]
    if document_role == "investigator_brochure" and (
        role_hits or len(supporting_hits) >= 3
    ):
        role_status = "matched"
    elif len(competing_hits) >= 2 and not role_hits:
        role_status = "mismatch"
    else:
        role_status = "warning"

    indication = expected_indication.strip()
    if not indication:
        indication_status = "not_assessed"
    elif re.sub(r"\s+", "", indication).casefold() in re.sub(
        r"\s+", "", full_text
    ).casefold():
        indication_status = "matched"
    else:
        # An IB may legitimately cover a product across several indications.
        # Absence is a review prompt, not proof that the file is unusable.
        indication_status = "warning"

    warnings: List[Dict[str, str]] = []
    if role_status != "matched":
        warnings.append(
            {
                "code": "document_role",
                "label": "文件角色",
                "status": role_status,
                "message": (
                    "未能明确确认该文件为研究者手册，请核对文件标题和正文后决定是否沿用。"
                    if role_status == "warning"
                    else "文件更像临床试验方案、统计分析计划或发表文献，请确认是否误选。"
                ),
            }
        )
    if indication_status == "warning":
        warnings.append(
            {
                "code": "indication",
                "label": "适应症",
                "status": "warning",
                "message": (
                    f"正文中未直接识别到当前适应症“{indication}”；"
                    "研究者手册可能覆盖多适应症，可由医学经理确认后沿用。"
                ),
            }
        )
    return {
        "document_role": document_role,
        "role_status": role_status,
        "indication_status": indication_status,
        "expected_indication": indication,
        "role_markers": role_hits[:8],
        "supporting_markers": supporting_hits[:8],
        "warnings": warnings,
        "usable_without_override": not warnings,
    }


def _source_span_identity(span: SourceRegistrySpan) -> tuple:
    return (
        span.source_id,
        span.entry_id,
        span.project_id,
        span.module,
        span.source_type,
        span.title,
        span.locator,
        span.text_preview,
        json.dumps(span.metadata, ensure_ascii=False, sort_keys=True),
    )


def _normalized_evidence_search_terms(
    query_terms: Sequence[str],
) -> List[tuple[str, str]]:
    raw_terms: List[str] = []
    for item in query_terms:
        raw_terms.extend(
            part
            for part in re.split(r"[\s,，;；、|]+", str(item).strip())
            if part
        )
    if not raw_terms:
        raise ValueError("evidence span search requires at least one keyword")
    if len(raw_terms) > MAX_EVIDENCE_SPAN_SEARCH_TERMS:
        raise ValueError(
            "evidence span search exceeds "
            f"{MAX_EVIDENCE_SPAN_SEARCH_TERMS} keywords"
        )
    normalized: List[tuple[str, str]] = []
    seen: set[str] = set()
    for term in raw_terms:
        if len(term) > 160:
            raise ValueError("evidence span search keyword exceeds 160 characters")
        folded = term.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        normalized.append((term, folded))
    return normalized


def _registration_identity(result: SourceRegistrationResult) -> tuple:
    entry = result.entry
    return (
        entry.entry_id,
        entry.project_id,
        entry.module,
        entry.source_kind,
        entry.content_hash,
        entry.parser_status,
        entry.parser_version,
        entry.span_count,
        tuple(_source_span_identity(span) for span in result.spans),
    )
