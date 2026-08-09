from __future__ import annotations

import json
import re
import sqlite3
import ssl
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from packages.contracts.workbench_contracts import (
    MedicalWritingCitationStyleUpdateRequest,
    MedicalWritingLiteratureLibrary,
    MedicalWritingProjectReference,
    MedicalWritingReferenceImportRequest,
    MedicalWritingReferenceImportResult,
)


TENANT_ID = "kangzhe_local"
DEFAULT_CITATION_STYLE = "gbt_7714_2015_numeric"
CROSSREF_HOST = "api.crossref.org"
NCBI_HOST = "eutils.ncbi.nlm.nih.gov"
ALLOWED_METADATA_HOSTS = {CROSSREF_HOST, NCBI_HOST}
MAX_METADATA_BYTES = 4 * 1024 * 1024
USER_AGENT = "CMS-Medical-Workbench/0.1 (mailto:medical-ai@cms.net.cn)"
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
PMID_PATTERN = re.compile(r"^(?:PMID\s*[:：]?\s*)?(\d{1,9})$", re.I)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


class MedicalWritingLiteratureError(ValueError):
    pass


class MedicalWritingLiteratureConflictError(MedicalWritingLiteratureError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def normalize_doi(value: str) -> str:
    match = DOI_PATTERN.search(str(value or "").strip())
    if not match:
        return ""
    return match.group(0).rstrip(".,;:)]}>").lower()


def normalize_url(value: str) -> str:
    try:
        parsed = urlsplit(str(value or "").strip())
        hostname = parsed.hostname
    except ValueError as exc:
        raise MedicalWritingLiteratureError("publication URL is invalid") from exc
    if parsed.scheme.lower() != "https" or not hostname:
        raise MedicalWritingLiteratureError("publication URL must use HTTPS")
    host = hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    try:
        port = parsed.port
    except ValueError as exc:
        raise MedicalWritingLiteratureError("publication URL has an invalid port") from exc
    if port and port != 443:
        host = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    if host in {"ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov"}:
        match = re.search(r"/(?:pubmed/)?(\d{1,9})(?:/|$)", path)
        if match:
            host = "pubmed.ncbi.nlm.nih.gov"
            path = f"/{match.group(1)}"
    query_pairs = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in TRACKING_QUERY_KEYS
        and not key.casefold().startswith("utm_")
    ]
    return urlunsplit(("https", host, path, urlencode(sorted(query_pairs)), ""))


def _year_from_parts(parts: Any) -> str:
    try:
        return str(parts[0][0])
    except (IndexError, KeyError, TypeError):
        return ""


class _AllowlistedMetadataRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        parsed = urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_METADATA_HOSTS:
            raise urllib.error.URLError("metadata redirect target is outside the allowlist")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class LiteratureMetadataClient:
    def __init__(self, *, timeout_seconds: int = 30):
        self.timeout_seconds = timeout_seconds

    def fetch_json(self, url: str) -> dict[str, Any]:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_METADATA_HOSTS:
            raise MedicalWritingLiteratureError("metadata endpoint is outside the allowlist")
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _AllowlistedMetadataRedirectHandler(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        with opener.open(request, timeout=self.timeout_seconds) as response:
            payload = response.read(MAX_METADATA_BYTES + 1)
            if len(payload) > MAX_METADATA_BYTES:
                raise MedicalWritingLiteratureError("metadata response exceeds size limit")
            final = urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname not in ALLOWED_METADATA_HOSTS:
                raise MedicalWritingLiteratureError("metadata final URL is outside the allowlist")
        try:
            value = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise MedicalWritingLiteratureError(
                "metadata response is not valid JSON"
            ) from exc
        if not isinstance(value, dict):
            raise MedicalWritingLiteratureError("metadata response must be a JSON object")
        return value

    def crossref_by_doi(self, doi: str) -> dict[str, Any]:
        payload = self.fetch_json(f"https://{CROSSREF_HOST}/works/{quote(doi, safe='')}")
        message = payload.get("message")
        if not isinstance(message, dict):
            raise MedicalWritingLiteratureError("Crossref DOI metadata is unavailable")
        return message

    def crossref_by_exact_url(self, url: str) -> dict[str, Any] | None:
        query = urlencode({"query.bibliographic": url, "rows": 5})
        payload = self.fetch_json(f"https://{CROSSREF_HOST}/works?{query}")
        message = payload.get("message")
        if not isinstance(message, dict):
            raise MedicalWritingLiteratureError("Crossref metadata has an invalid shape")
        items = message.get("items") or []
        if not isinstance(items, list):
            raise MedicalWritingLiteratureError("Crossref metadata items must be a list")
        expected = normalize_url(url)
        for item in items:
            if not isinstance(item, dict):
                continue
            candidates = [item.get("URL") or ""]
            links = item.get("link") or []
            if isinstance(links, list):
                candidates.extend(
                    str(link.get("URL") or "")
                    for link in links
                    if isinstance(link, dict)
                )
            for candidate in candidates:
                try:
                    if candidate and normalize_url(candidate) == expected:
                        return item
                except MedicalWritingLiteratureError:
                    continue
        return None

    def pubmed_by_pmid(self, pmid: str) -> dict[str, Any]:
        query = urlencode({"db": "pubmed", "id": pmid, "retmode": "json", "version": "2.0"})
        payload = self.fetch_json(
            f"https://{NCBI_HOST}/entrez/eutils/esummary.fcgi?{query}"
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise MedicalWritingLiteratureError("PubMed metadata has an invalid shape")
        record = result.get(pmid)
        if not isinstance(record, dict):
            raise MedicalWritingLiteratureError("PubMed metadata is unavailable for this PMID")
        return record


class MedicalWritingLiteratureRepository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS medical_writing_literature_preferences (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    citation_style TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id)
                );
                CREATE TABLE IF NOT EXISTS medical_writing_literature_references (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    reference_id TEXT NOT NULL,
                    canonical_key TEXT NOT NULL,
                    doi TEXT NOT NULL,
                    pmid TEXT NOT NULL,
                    normalized_url TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, reference_id),
                    UNIQUE (tenant_id, project_id, canonical_key)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_mw_literature_doi
                ON medical_writing_literature_references(tenant_id, project_id, doi)
                WHERE doi <> '';
                CREATE UNIQUE INDEX IF NOT EXISTS idx_mw_literature_pmid
                ON medical_writing_literature_references(tenant_id, project_id, pmid)
                WHERE pmid <> '';
                CREATE TABLE IF NOT EXISTS medical_writing_literature_idempotency (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, operation, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS medical_writing_literature_audit (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, sequence_no)
                );
                """
            )

    def library(self, project_id: str) -> MedicalWritingLiteratureLibrary:
        with self._connect() as connection:
            preference = connection.execute(
                "SELECT citation_style FROM medical_writing_literature_preferences WHERE tenant_id=? AND project_id=?",
                (TENANT_ID, project_id),
            ).fetchone()
            rows = connection.execute(
                "SELECT payload_json FROM medical_writing_literature_references WHERE tenant_id=? AND project_id=? ORDER BY updated_at, reference_id",
                (TENANT_ID, project_id),
            ).fetchall()
        return MedicalWritingLiteratureLibrary(
            project_id=project_id,
            citation_style=(preference["citation_style"] if preference else DEFAULT_CITATION_STYLE),
            references=[MedicalWritingProjectReference.model_validate_json(row["payload_json"]) for row in rows],
        )

    def save_import(
        self,
        result: MedicalWritingReferenceImportResult,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> MedicalWritingReferenceImportResult:
        project_id = result.reference.project_id
        conflict_error: MedicalWritingLiteratureConflictError | None = None
        stored: MedicalWritingReferenceImportResult | None = None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                "SELECT request_hash, result_json FROM medical_writing_literature_idempotency WHERE tenant_id=? AND project_id=? AND operation='import' AND idempotency_key=?",
                (TENANT_ID, project_id, idempotency_key),
            ).fetchone()
            if replay:
                if replay["request_hash"] != request_hash:
                    raise MedicalWritingLiteratureConflictError(
                        "literature import idempotency key was reused with different content"
                    )
                return MedicalWritingReferenceImportResult.model_validate_json(replay["result_json"])

            rows = connection.execute(
                "SELECT payload_json FROM medical_writing_literature_references "
                "WHERE tenant_id=? AND project_id=?",
                (TENANT_ID, project_id),
            ).fetchall()
            existing = [
                MedicalWritingProjectReference.model_validate_json(row["payload_json"])
                for row in rows
            ]
            resolution = _resolve_identity_graph(existing, result.reference)

            if resolution["conflict"]:
                detail = {
                    **resolution["conflict"],
                    "incoming_reference_id": result.reference.reference_id,
                    "override_requested": result.reference.validation_status == "overridden",
                    "override_reason": result.reference.override_reason,
                }
                self._append_audit(
                    connection,
                    project_id,
                    "reference_identity_conflict",
                    result.reference.reference_id,
                    result.reference.updated_by,
                    detail,
                )
                conflict_error = MedicalWritingLiteratureConflictError(
                    "needs_review: literature identity conflict; the records were not merged"
                )
            else:
                component = resolution["component"]
                weak_override_separate = resolution["weak_override_separate"]
                if component:
                    ordered = sorted(
                        component,
                        key=lambda item: (item.created_at, item.reference_id),
                    )
                    survivor = ordered[0]
                    absorbed = ordered[1:]
                    reference = _merge_reference_component(
                        survivor,
                        [*absorbed, result.reference],
                        force_revision=bool(absorbed),
                    )
                    matched_on = (
                        "identity_graph"
                        if len(component) > 1
                        else resolution["matched_on"]
                    )
                    final = MedicalWritingReferenceImportResult(
                        reference=reference,
                        created=False,
                        matched_on=matched_on,
                    )
                else:
                    reference = result.reference
                    absorbed = []
                    final = result

                component_ids = {item.reference_id for item in component}
                absorbed_ids = [
                    item.reference_id
                    for item in component
                    if item.reference_id != reference.reference_id
                ]
                if absorbed_ids:
                    placeholders = ",".join("?" for _ in absorbed_ids)
                    connection.execute(
                        "DELETE FROM medical_writing_literature_references "
                        f"WHERE tenant_id=? AND project_id=? AND reference_id IN ({placeholders})",
                        (TENANT_ID, project_id, *absorbed_ids),
                    )

                connection.execute(
                    """
                    INSERT INTO medical_writing_literature_references(
                        tenant_id, project_id, reference_id, canonical_key, doi, pmid,
                        normalized_url, payload_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tenant_id, project_id, reference_id) DO UPDATE SET
                        canonical_key=excluded.canonical_key, doi=excluded.doi, pmid=excluded.pmid,
                        normalized_url=excluded.normalized_url, payload_json=excluded.payload_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        TENANT_ID,
                        project_id,
                        reference.reference_id,
                        reference.canonical_key,
                        reference.doi,
                        reference.pmid,
                        _safe_normalize_url(reference.url),
                        reference.model_dump_json(),
                        reference.updated_at.isoformat(),
                    ),
                )
                if component_ids:
                    self._remap_import_idempotency(
                        connection,
                        project_id,
                        component_ids,
                        reference,
                    )
                stored = final.model_copy(update={"reference": reference})
                connection.execute(
                    "INSERT INTO medical_writing_literature_idempotency VALUES (?, ?, 'import', ?, ?, ?, ?)",
                    (
                        TENANT_ID,
                        project_id,
                        idempotency_key,
                        request_hash,
                        stored.model_dump_json(),
                        _utc_now().isoformat(),
                    ),
                )
                if absorbed_ids:
                    self._append_audit(
                        connection,
                        project_id,
                        "reference_identity_merged",
                        reference.reference_id,
                        reference.updated_by,
                        {
                            "survivor_reference_id": reference.reference_id,
                            "absorbed_reference_ids": absorbed_ids,
                            "survivor_selection_policy": "earliest_created_at_then_reference_id",
                            "matched_on": stored.matched_on,
                            "canonical_key": reference.canonical_key,
                            "result_revision": reference.revision,
                        },
                    )
                if weak_override_separate:
                    self._append_audit(
                        connection,
                        project_id,
                        "reference_weak_identity_override_separate",
                        reference.reference_id,
                        reference.updated_by,
                        {
                            "conflicting_reference_ids": weak_override_separate,
                            "override_reason": reference.override_reason,
                        },
                    )
                self._append_audit(
                    connection,
                    project_id,
                    "reference_imported" if stored.created else "reference_deduplicated",
                    reference.reference_id,
                    reference.updated_by,
                    {"canonical_key": reference.canonical_key, "matched_on": stored.matched_on},
                )

        if conflict_error is not None:
            raise conflict_error
        if stored is None:
            raise MedicalWritingLiteratureError("literature import did not produce a result")
        return stored

    def record_identity_conflict(
        self,
        project_id: str,
        *,
        target_id: str,
        actor: str,
        detail: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._append_audit(
                connection,
                project_id,
                "reference_identity_conflict",
                target_id,
                actor,
                detail,
            )

    @staticmethod
    def _remap_import_idempotency(
        connection: sqlite3.Connection,
        project_id: str,
        component_ids: set[str],
        reference: MedicalWritingProjectReference,
    ) -> None:
        rows = connection.execute(
            "SELECT idempotency_key, result_json FROM medical_writing_literature_idempotency "
            "WHERE tenant_id=? AND project_id=? AND operation='import'",
            (TENANT_ID, project_id),
        ).fetchall()
        for row in rows:
            try:
                prior = MedicalWritingReferenceImportResult.model_validate_json(
                    row["result_json"]
                )
            except (ValueError, TypeError):
                continue
            if prior.reference.reference_id not in component_ids:
                continue
            remapped = prior.model_copy(update={"reference": reference})
            connection.execute(
                "UPDATE medical_writing_literature_idempotency SET result_json=? "
                "WHERE tenant_id=? AND project_id=? AND operation='import' AND idempotency_key=?",
                (
                    remapped.model_dump_json(),
                    TENANT_ID,
                    project_id,
                    row["idempotency_key"],
                ),
            )

    def update_style(
        self,
        project_id: str,
        request: MedicalWritingCitationStyleUpdateRequest,
    ) -> MedicalWritingLiteratureLibrary:
        request_hash = _payload_hash(request.model_dump(mode="json"))
        with self._connect() as connection:
            replay = connection.execute(
                "SELECT request_hash FROM medical_writing_literature_idempotency WHERE tenant_id=? AND project_id=? AND operation='style' AND idempotency_key=?",
                (TENANT_ID, project_id, request.idempotency_key),
            ).fetchone()
            if replay and replay["request_hash"] != request_hash:
                raise MedicalWritingLiteratureConflictError(
                    "citation-style idempotency key was reused with different content"
                )
            if not replay:
                now = _utc_now().isoformat()
                connection.execute(
                    "INSERT INTO medical_writing_literature_preferences VALUES (?, ?, ?, ?, ?) ON CONFLICT(tenant_id, project_id) DO UPDATE SET citation_style=excluded.citation_style, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                    (TENANT_ID, project_id, request.citation_style, request.actor, now),
                )
                connection.execute(
                    "INSERT INTO medical_writing_literature_idempotency VALUES (?, ?, 'style', ?, ?, '{}', ?)",
                    (TENANT_ID, project_id, request.idempotency_key, request_hash, now),
                )
                self._append_audit(
                    connection,
                    project_id,
                    "citation_style_updated",
                    request.citation_style,
                    request.actor,
                    {"citation_style": request.citation_style},
                )
        return self.library(project_id)

    @staticmethod
    def _append_audit(connection, project_id, event_type, target_id, actor, detail):  # noqa: ANN001
        row = connection.execute(
            "SELECT COALESCE(MAX(sequence_no), 0) AS last FROM medical_writing_literature_audit WHERE tenant_id=? AND project_id=?",
            (TENANT_ID, project_id),
        ).fetchone()
        connection.execute(
            "INSERT INTO medical_writing_literature_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                TENANT_ID,
                project_id,
                int(row["last"]) + 1,
                event_type,
                target_id,
                actor,
                _canonical_json(detail),
                _utc_now().isoformat(),
            ),
        )


class MedicalWritingLiteratureService:
    def __init__(
        self,
        repository: MedicalWritingLiteratureRepository,
        client: LiteratureMetadataClient,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self.repository = repository
        self.client = client
        self.clock = clock

    def library(self, project_id: str) -> MedicalWritingLiteratureLibrary:
        return self.repository.library(project_id)

    def update_style(
        self,
        project_id: str,
        request: MedicalWritingCitationStyleUpdateRequest,
    ) -> MedicalWritingLiteratureLibrary:
        return self.repository.update_style(project_id, request)

    def import_reference(
        self,
        project_id: str,
        request: MedicalWritingReferenceImportRequest,
    ) -> MedicalWritingReferenceImportResult:
        source_kind, identifier = _classify_source(request.source_input)
        metadata: dict[str, Any]
        try:
            if source_kind == "doi":
                metadata = _from_crossref(self.client.crossref_by_doi(identifier))
            elif source_kind in {"pmid", "pubmed_url"}:
                metadata = _from_pubmed(self.client.pubmed_by_pmid(identifier))
            else:
                embedded_doi = normalize_doi(identifier)
                if embedded_doi:
                    metadata = _from_crossref(self.client.crossref_by_doi(embedded_doi))
                else:
                    item = self.client.crossref_by_exact_url(identifier)
                    if item is None:
                        raise MedicalWritingLiteratureError(
                            "publication URL could not be matched exactly; provide DOI/PMID or confirm manual metadata"
                        )
                    metadata = _from_crossref(item)
        except (
            MedicalWritingLiteratureError,
            urllib.error.URLError,
            TimeoutError,
            TypeError,
            AttributeError,
            KeyError,
        ) as exc:
            if (
                not request.override_validation
                or request.manual_metadata is None
                or not request.manual_metadata.title
            ):
                raise MedicalWritingLiteratureError(str(exc)) from exc
            metadata = {}
        metadata = _merge_manual_metadata(metadata, request.manual_metadata)
        metadata = _sanitize_metadata(metadata)
        if not metadata["title"]:
            raise MedicalWritingLiteratureError("reference title is required")
        doi = normalize_doi(metadata["doi"])
        pmid = _normalize_pmid(metadata["pmid"])
        if source_kind == "doi":
            if doi and doi != identifier:
                self._record_source_identity_conflict(
                    project_id,
                    request,
                    source_kind="doi",
                    requested=identifier,
                    received=doi,
                )
            doi = identifier
        elif source_kind in {"pmid", "pubmed_url"}:
            if pmid and pmid != identifier:
                self._record_source_identity_conflict(
                    project_id,
                    request,
                    source_kind="pmid",
                    requested=identifier,
                    received=pmid,
                )
            pmid = identifier
        url = metadata["url"] or request.source_input
        if source_kind == "publisher_url":
            url = identifier
        try:
            url = normalize_url(url) if url else ""
        except MedicalWritingLiteratureError:
            url = ""
        metadata.update({"doi": doi, "pmid": pmid, "url": url})
        warnings = _metadata_warnings(metadata)
        status = "overridden" if request.override_validation else ("needs_review" if warnings else "confirmed")
        now = self.clock()
        canonical_key = _canonical_reference_key(doi, pmid, url, metadata)
        reference_id = "mwref_" + sha256(
            f"{project_id}|{canonical_key}".encode("utf-8")
        ).hexdigest()[:20]
        reference = MedicalWritingProjectReference(
            reference_id=reference_id,
            project_id=project_id,
            canonical_key=canonical_key,
            source_kind=source_kind,
            source_input=request.source_input,
            title=metadata["title"],
            authors=metadata["authors"],
            journal=metadata["journal"],
            year=metadata["year"],
            volume=metadata["volume"],
            issue=metadata["issue"],
            pages=metadata["pages"],
            doi=doi,
            pmid=pmid,
            url=url,
            validation_status=status,
            validation_warnings=warnings,
            override_reason=request.override_reason,
            created_by=request.actor,
            updated_by=request.actor,
            created_at=now,
            updated_at=now,
        )
        result = MedicalWritingReferenceImportResult(
            reference=reference,
            created=True,
            matched_on=canonical_key.split(":", 1)[0],
        )
        request_hash = _payload_hash(request.model_dump(mode="json"))
        return self.repository.save_import(
            result,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
        )

    def _record_source_identity_conflict(
        self,
        project_id: str,
        request: MedicalWritingReferenceImportRequest,
        *,
        source_kind: str,
        requested: str,
        received: str,
    ) -> None:
        target_id = "mwref_conflict_" + sha256(
            f"{project_id}|{source_kind}|{requested}|{received}".encode("utf-8")
        ).hexdigest()[:20]
        self.repository.record_identity_conflict(
            project_id,
            target_id=target_id,
            actor=request.actor,
            detail={
                "kind": "source_metadata_identifier_conflict",
                "source_kind": source_kind,
                "requested": requested,
                "received": received,
                "override_requested": request.override_validation,
                "override_reason": request.override_reason,
            },
        )
        raise MedicalWritingLiteratureConflictError(
            "needs_review: source identifier conflicts with provider metadata"
        )


def _classify_source(value: str) -> tuple[str, str]:
    text = value.strip()
    pmid = PMID_PATTERN.fullmatch(text)
    if pmid:
        return "pmid", pmid.group(1)
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise MedicalWritingLiteratureError("publication URL is invalid") from exc
    if parsed.scheme:
        normalized = normalize_url(text)
        host = urlsplit(normalized).hostname or ""
        if host in {"pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov"}:
            match = re.search(r"/(?:pubmed/)?(\d{1,9})(?:/|$)", urlsplit(normalized).path)
            if not match:
                raise MedicalWritingLiteratureError("PubMed URL does not contain a PMID")
            return "pubmed_url", match.group(1)
        if host == "doi.org":
            doi = normalize_doi(text)
            if not doi:
                raise MedicalWritingLiteratureError("DOI URL is invalid")
            return "doi", doi
        return "publisher_url", normalized
    doi = normalize_doi(text)
    if doi:
        return "doi", doi
    raise MedicalWritingLiteratureError("enter a DOI, PMID, PubMed URL or HTTPS publication URL")


def _from_crossref(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise MedicalWritingLiteratureError("Crossref metadata must be an object")
    authors = []
    raw_authors = item.get("author") or []
    if not isinstance(raw_authors, list):
        raw_authors = []
    for author in raw_authors:
        if not isinstance(author, dict):
            continue
        name = " ".join(
            part
            for part in (
                _safe_scalar_text(author.get("family")),
                _safe_scalar_text(author.get("given")),
            )
            if part
        )
        if name:
            authors.append(name)
    date = _first_mapping(
        item.get("published-print"),
        item.get("published-online"),
        item.get("published"),
    )
    return {
        "title": _first_text(item.get("title")),
        "authors": authors,
        "journal": _first_text(item.get("container-title")),
        "year": _year_from_parts(date.get("date-parts")),
        "volume": _safe_scalar_text(item.get("volume")),
        "issue": _safe_scalar_text(item.get("issue")),
        "pages": _safe_scalar_text(item.get("page"))
        or _safe_scalar_text(item.get("article-number")),
        "doi": _safe_scalar_text(item.get("DOI")),
        "pmid": "",
        "url": _safe_scalar_text(item.get("URL")),
    }


def _from_pubmed(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise MedicalWritingLiteratureError("PubMed metadata must be an object")
    raw_ids = item.get("articleids") or []
    if not isinstance(raw_ids, list):
        raw_ids = []
    identifiers = {}
    for entry in raw_ids:
        if not isinstance(entry, dict):
            continue
        id_type = _safe_scalar_text(entry.get("idtype")).casefold()
        value = _safe_scalar_text(entry.get("value"))
        if id_type and value:
            identifiers[id_type] = value
    pubdate = _safe_scalar_text(item.get("pubdate"))
    year_match = re.search(r"\b(19|20)\d{2}\b", pubdate)
    raw_authors = item.get("authors") or []
    if not isinstance(raw_authors, list):
        raw_authors = []
    uid = _safe_scalar_text(item.get("uid")) or identifiers.get("pubmed", "")
    return {
        "title": _safe_scalar_text(item.get("title")).rstrip(". "),
        "authors": [
            _safe_scalar_text(author.get("name"))
            for author in raw_authors
            if isinstance(author, dict) and _safe_scalar_text(author.get("name"))
        ],
        "journal": _safe_scalar_text(item.get("fulljournalname"))
        or _safe_scalar_text(item.get("source")),
        "year": year_match.group(0) if year_match else "",
        "volume": _safe_scalar_text(item.get("volume")),
        "issue": _safe_scalar_text(item.get("issue")),
        "pages": _safe_scalar_text(item.get("pages")),
        "doi": identifiers.get("doi", ""),
        "pmid": uid,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/" if uid else "",
    }


def _merge_manual_metadata(metadata: dict[str, Any], manual) -> dict[str, Any]:  # noqa: ANN001
    if not isinstance(metadata, dict):
        raise MedicalWritingLiteratureError("reference metadata must be an object")
    merged = dict(metadata)
    if manual is None:
        return merged
    for key, value in manual.model_dump().items():
        if value not in ("", [], None):
            merged[key] = value
    return merged


def _metadata_warnings(metadata: dict[str, Any]) -> list[str]:
    labels = {"authors": "作者", "year": "发表年份", "journal": "期刊名称"}
    return [f"元数据缺少{label}" for field, label in labels.items() if not metadata.get(field)]


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise MedicalWritingLiteratureError("reference metadata must be an object")
    raw_authors = metadata.get("authors") or []
    authors = []
    if isinstance(raw_authors, list):
        authors = [
            text
            for text in (_safe_scalar_text(item) for item in raw_authors)
            if text
        ]
    return {
        "title": _safe_scalar_text(metadata.get("title")),
        "authors": authors,
        "journal": _safe_scalar_text(metadata.get("journal")),
        "year": _normalize_year(metadata.get("year")),
        "volume": _safe_scalar_text(metadata.get("volume")),
        "issue": _safe_scalar_text(metadata.get("issue")),
        "pages": _safe_scalar_text(metadata.get("pages")),
        "doi": _safe_scalar_text(metadata.get("doi")),
        "pmid": _safe_scalar_text(metadata.get("pmid")),
        "url": _safe_scalar_text(metadata.get("url")),
    }


def _canonical_reference_key(doi: str, pmid: str, url: str, metadata: dict[str, Any]) -> str:
    if doi:
        return f"doi:{doi}"
    if pmid:
        return f"pmid:{pmid}"
    try:
        if url:
            return f"url:{normalize_url(url)}"
    except MedicalWritingLiteratureError:
        pass
    title_year = _normalized_title_year(
        _safe_scalar_text(metadata.get("title")),
        _safe_scalar_text(metadata.get("year")),
    )
    if not title_year:
        raise MedicalWritingLiteratureError(
            "reference requires a DOI, PMID, canonical URL, or title and year"
        )
    return "title_year:" + sha256(title_year.encode("utf-8")).hexdigest()[:24]


def _safe_normalize_url(value: str) -> str:
    try:
        return normalize_url(value) if value else ""
    except MedicalWritingLiteratureError:
        return ""


def _safe_scalar_text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            text = _safe_scalar_text(item)
            if text:
                return text
    return ""


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _normalize_year(value: Any) -> str:
    text = _safe_scalar_text(value)
    match = re.search(r"\b(19|20)\d{2}\b", text)
    return match.group(0) if match else ""


def _normalize_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", _safe_scalar_text(value)).casefold()
    return "".join(
        character
        for character in text
        if unicodedata.category(character)[:1] in {"L", "N"}
    )


def _normalized_title_year(title: Any, year: Any) -> str:
    normalized_title = _normalize_title(title)
    normalized_year = _normalize_year(year)
    if not normalized_title or not normalized_year:
        return ""
    return f"{normalized_title}|{normalized_year}"


def _identity_values(reference: MedicalWritingProjectReference) -> dict[str, str]:
    return {
        "doi": normalize_doi(reference.doi),
        "pmid": _normalize_pmid(reference.pmid),
        "url": _safe_normalize_url(reference.url),
        "title_year": _normalized_title_year(reference.title, reference.year),
    }


def _identity_relation(
    left: MedicalWritingProjectReference,
    right: MedicalWritingProjectReference,
) -> tuple[str, list[str]]:
    left_ids = _identity_values(left)
    right_ids = _identity_values(right)
    shared = [
        field
        for field in ("doi", "pmid", "url")
        if left_ids[field] and left_ids[field] == right_ids[field]
    ]
    conflicts = [
        field
        for field in ("doi", "pmid")
        if left_ids[field]
        and right_ids[field]
        and left_ids[field] != right_ids[field]
    ]
    if shared:
        return shared[0], conflicts
    if (
        left_ids["title_year"]
        and left_ids["title_year"] == right_ids["title_year"]
    ):
        return "title_year", conflicts
    return "", []


def _resolve_identity_graph(
    existing: list[MedicalWritingProjectReference],
    incoming: MedicalWritingProjectReference,
) -> dict[str, Any]:
    component: list[MedicalWritingProjectReference] = []
    direct_matches: list[tuple[MedicalWritingProjectReference, str]] = []
    weak_conflicts: list[dict[str, Any]] = []
    hard_conflicts: list[dict[str, Any]] = []

    for candidate in existing:
        matched_on, conflicts = _identity_relation(candidate, incoming)
        if not matched_on:
            continue
        detail = {
            "reference_id": candidate.reference_id,
            "matched_on": matched_on,
            "conflicting_strong_identifiers": conflicts,
        }
        if conflicts:
            if matched_on == "title_year":
                weak_conflicts.append(detail)
            else:
                hard_conflicts.append(detail)
        else:
            direct_matches.append((candidate, matched_on))

    if hard_conflicts:
        return {
            "component": [],
            "matched_on": "",
            "conflict": {"kind": "strong_identifier_conflict", "matches": hard_conflicts},
            "weak_override_separate": [],
        }

    if weak_conflicts:
        override_separate = (
            incoming.validation_status == "overridden"
            and bool(incoming.override_reason)
            and not direct_matches
        )
        if not override_separate:
            return {
                "component": [],
                "matched_on": "",
                "conflict": {"kind": "weak_identity_strong_conflict", "matches": weak_conflicts},
                "weak_override_separate": [],
            }
        return {
            "component": [],
            "matched_on": "",
            "conflict": None,
            "weak_override_separate": [item["reference_id"] for item in weak_conflicts],
        }

    component = [item[0] for item in direct_matches]
    matched_on = direct_matches[0][1] if direct_matches else ""
    remaining = [item for item in existing if item not in component]
    changed = True
    while component and changed:
        changed = False
        for candidate in list(remaining):
            relations = [_identity_relation(candidate, member) for member in component]
            related = [(kind, conflicts) for kind, conflicts in relations if kind]
            if not related:
                continue
            conflicts = [
                {"matched_on": kind, "conflicting_strong_identifiers": fields}
                for kind, fields in related
                if fields
            ]
            if conflicts:
                return {
                    "component": [],
                    "matched_on": "",
                    "conflict": {
                        "kind": "historical_identity_graph_conflict",
                        "reference_id": candidate.reference_id,
                        "matches": conflicts,
                    },
                    "weak_override_separate": [],
                }
            component.append(candidate)
            remaining.remove(candidate)
            changed = True

    return {
        "component": component,
        "matched_on": matched_on,
        "conflict": None,
        "weak_override_separate": [],
    }


def _prefer_text(field_name: str, current: str, candidate: str) -> str:
    if not candidate:
        return current
    if not current:
        return candidate
    if field_name == "year":
        return current
    if field_name == "url":
        def url_score(value: str) -> tuple[int, int]:
            normalized = _safe_normalize_url(value)
            host = urlsplit(normalized).hostname or ""
            score = 1 if host == "doi.org" else 2 if "pubmed.ncbi.nlm.nih.gov" in host else 3
            return score, len(normalized)

        return max((current, candidate), key=url_score)
    return candidate if len(candidate) > len(current) else current


def _merge_reference_component(
    survivor: MedicalWritingProjectReference,
    candidates: list[MedicalWritingProjectReference],
    *,
    force_revision: bool,
) -> MedicalWritingProjectReference:
    updates: dict[str, Any] = {}
    state = survivor
    override_reason = survivor.override_reason
    overridden = survivor.validation_status == "overridden"
    for candidate in candidates:
        candidate_updates: dict[str, Any] = {}
        for field_name in (
            "title",
            "journal",
            "year",
            "volume",
            "issue",
            "pages",
            "doi",
            "pmid",
            "url",
        ):
            selected = _prefer_text(
                field_name,
                getattr(state, field_name),
                getattr(candidate, field_name),
            )
            if selected != getattr(state, field_name):
                candidate_updates[field_name] = selected
        known_authors = {item.casefold() for item in state.authors}
        merged_authors = [*state.authors]
        for author in candidate.authors:
            if author.casefold() not in known_authors:
                merged_authors.append(author)
                known_authors.add(author.casefold())
        if merged_authors != state.authors:
            candidate_updates["authors"] = merged_authors
        if candidate.validation_status == "overridden":
            overridden = True
            override_reason = override_reason or candidate.override_reason
        if candidate_updates:
            state = state.model_copy(update=candidate_updates)
            updates.update(candidate_updates)

    normalized_id_updates = {
        "doi": normalize_doi(state.doi),
        "pmid": _normalize_pmid(state.pmid),
        "url": _safe_normalize_url(state.url),
    }
    normalized_id_updates = {
        field_name: value
        for field_name, value in normalized_id_updates.items()
        if value != getattr(state, field_name)
    }
    if normalized_id_updates:
        state = state.model_copy(update=normalized_id_updates)
        updates.update(normalized_id_updates)

    canonical_key = _canonical_reference_key(
        state.doi,
        state.pmid,
        state.url,
        state.model_dump(),
    )
    if canonical_key != survivor.canonical_key:
        updates["canonical_key"] = canonical_key
    warnings = _metadata_warnings(state.model_dump())
    status = "overridden" if overridden else ("needs_review" if warnings else "confirmed")
    if warnings != survivor.validation_warnings:
        updates["validation_warnings"] = warnings
    if status != survivor.validation_status:
        updates["validation_status"] = status
    if override_reason and override_reason != survivor.override_reason:
        updates["override_reason"] = override_reason
    if not updates and not force_revision:
        return survivor
    latest = candidates[-1]
    updates.update(
        {
            "revision": survivor.revision + 1,
            "updated_by": latest.updated_by,
            "updated_at": latest.updated_at,
        }
    )
    return survivor.model_copy(update=updates)


def _normalize_pmid(value: Any) -> str:
    text = _safe_scalar_text(value)
    return text if re.fullmatch(r"\d{1,9}", text) else ""
