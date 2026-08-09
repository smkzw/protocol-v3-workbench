from __future__ import annotations

import json
import sqlite3
import tempfile
import warnings
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts import (
    MedicalWritingCitationStyleUpdateRequest,
    MedicalWritingReferenceImportRequest,
    MedicalWritingReferenceManualMetadata,
)
from services.api.app.medical_writing_literature import (
    MedicalWritingLiteratureConflictError,
    MedicalWritingLiteratureError,
    MedicalWritingLiteratureRepository,
    MedicalWritingLiteratureService,
)


NOW = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)


class FakeMetadataClient:
    def crossref_by_doi(self, doi: str):
        return {
            "DOI": doi,
            "title": ["Efficacy and safety of a study treatment"],
            "author": [
                {"family": "Zhang", "given": "Wei"},
                {"family": "Smith", "given": "John"},
            ],
            "container-title": ["Journal of Clinical Research"],
            "published-print": {"date-parts": [[2025, 8, 1]]},
            "volume": "18",
            "issue": "4",
            "page": "101-112",
            "URL": f"https://doi.org/{doi}",
        }

    def pubmed_by_pmid(self, pmid: str):
        return {
            "uid": pmid,
            "title": "Efficacy and safety of a study treatment.",
            "authors": [{"name": "Zhang W"}, {"name": "Smith J"}],
            "fulljournalname": "Journal of Clinical Research",
            "pubdate": "2025 Aug",
            "volume": "18",
            "issue": "4",
            "pages": "101-112",
            "articleids": [
                {"idtype": "pubmed", "value": pmid},
                {"idtype": "doi", "value": "10.1234/example.2025.01"},
            ],
        }

    def crossref_by_exact_url(self, url: str):
        if url == "https://journal.example.org/article/valid":
            item = self.crossref_by_doi("10.1234/publisher.url.01")
            item["URL"] = url
            return item
        return None


class SequencedMetadataClient(FakeMetadataClient):
    def __init__(self):
        self.doi_records: dict[str, dict] = {}
        self.pmid_records: dict[str, dict] = {}
        self.url_records: dict[str, dict | None] = {}

    def crossref_by_doi(self, doi: str):
        return self.doi_records[doi]

    def pubmed_by_pmid(self, pmid: str):
        return self.pmid_records[pmid]

    def crossref_by_exact_url(self, url: str):
        return self.url_records.get(url)


def _crossref_record(
    doi: str,
    *,
    title: str = "Identity graph publication",
    year: int = 2025,
    url: str | None = None,
) -> dict:
    record = {
        "DOI": doi,
        "title": [title],
        "author": [{"family": "Zhang", "given": "Wei"}],
        "container-title": ["Journal of Identity Resolution"],
        "published-print": {"date-parts": [[year, 1, 1]]},
        "volume": "12",
        "issue": "3",
        "page": "10-20",
        "URL": url or f"https://doi.org/{doi}",
    }
    return record


def _pubmed_record(
    pmid: str,
    *,
    title: str = "Identity graph publication.",
    year: int = 2025,
    doi: str = "",
) -> dict:
    articleids = [{"idtype": "pubmed", "value": pmid}]
    if doi:
        articleids.append({"idtype": "doi", "value": doi})
    return {
        "uid": pmid,
        "title": title,
        "authors": [{"name": "Zhang W"}],
        "fulljournalname": "Journal of Identity Resolution",
        "pubdate": f"{year} Jan",
        "volume": "12",
        "issue": "3",
        "pages": "10-20",
        "articleids": articleids,
    }


def _audit_events(repository: MedicalWritingLiteratureRepository, project_id: str):
    with sqlite3.connect(repository.db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT event_type, target_id, detail_json FROM medical_writing_literature_audit "
            "WHERE tenant_id='kangzhe_local' AND project_id=? ORDER BY sequence_no",
            (project_id,),
        ).fetchall()
    return [
        {
            "event_type": row["event_type"],
            "target_id": row["target_id"],
            "detail": json.loads(row["detail_json"]),
        }
        for row in rows
    ]


@pytest.fixture()
def sequenced_service():
    with tempfile.TemporaryDirectory() as directory:
        repository = MedicalWritingLiteratureRepository(
            Path(directory) / "literature.sqlite3"
        )
        client = SequencedMetadataClient()
        yield MedicalWritingLiteratureService(
            repository,
            client,
            clock=lambda: NOW,
        ), repository, client


@pytest.fixture()
def service():
    with tempfile.TemporaryDirectory() as directory:
        repository = MedicalWritingLiteratureRepository(
            Path(directory) / "literature.sqlite3"
        )
        yield MedicalWritingLiteratureService(
            repository,
            FakeMetadataClient(),
            clock=lambda: NOW,
        ), repository


def test_doi_import_is_project_scoped_idempotent_and_persistent(service):
    literature, repository = service
    request = MedicalWritingReferenceImportRequest(
        source_input="https://doi.org/10.1234/EXAMPLE.2025.01",
        idempotency_key="doi-import-0001",
    )

    created = literature.import_reference("project-a", request)
    replay = literature.import_reference("project-a", request)

    assert created.created is True
    assert replay.model_dump() == created.model_dump()
    assert created.reference.doi == "10.1234/example.2025.01"
    assert created.reference.validation_status == "confirmed"
    assert repository.library("project-a").references == [created.reference]
    assert repository.library("project-b").references == []

    restarted = MedicalWritingLiteratureRepository(repository.db_path)
    assert restarted.library("project-a").references[0] == created.reference


def test_pmid_and_doi_resolve_to_one_reference(service):
    literature, _ = service
    doi_result = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input="10.1234/example.2025.01",
            idempotency_key="dedupe-by-doi-01",
        ),
    )
    pmid_result = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input="PMID: 45678901",
            idempotency_key="dedupe-by-pmid-1",
        ),
    )

    assert pmid_result.created is False
    assert pmid_result.matched_on == "doi"
    assert pmid_result.reference.reference_id == doi_result.reference.reference_id
    assert pmid_result.reference.pmid == "45678901"
    assert len(literature.library("project-a").references) == 1


def test_publisher_url_requires_exact_match_or_explicit_manual_override(service):
    literature, _ = service
    exact = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input="https://journal.example.org/article/valid",
            idempotency_key="publisher-exact-1",
        ),
    )
    assert exact.reference.doi == "10.1234/publisher.url.01"

    with pytest.raises(MedicalWritingLiteratureError, match="could not be matched exactly"):
        literature.import_reference(
            "project-a",
            MedicalWritingReferenceImportRequest(
                source_input="https://journal.example.org/article/unknown",
                idempotency_key="publisher-miss-01",
            ),
        )

    overridden = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input="https://journal.example.org/article/unknown",
            manual_metadata=MedicalWritingReferenceManualMetadata(
                title="A manually confirmed publication",
                authors=["Li Ming"],
                journal="Clinical Medicine",
                year="2024",
                url="https://journal.example.org/article/unknown",
            ),
            override_validation=True,
            override_reason="医学经理已在期刊官网逐项核对题名、作者和发表年份。",
            idempotency_key="publisher-override",
        ),
    )
    assert overridden.reference.validation_status == "overridden"
    assert overridden.reference.override_reason


def test_incomplete_metadata_is_visible_and_style_version_is_project_persistent(service):
    literature, repository = service
    client = FakeMetadataClient()
    client.crossref_by_doi = lambda doi: {
        "DOI": doi,
        "title": ["Metadata with missing fields"],
        "URL": f"https://doi.org/{doi}",
    }
    literature.client = client

    result = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input="10.1234/missing.01",
            idempotency_key="missing-fields-01",
        ),
    )
    assert result.reference.validation_status == "needs_review"
    assert result.reference.validation_warnings == [
        "元数据缺少作者",
        "元数据缺少发表年份",
        "元数据缺少期刊名称",
    ]
    assert repository.library("project-a").citation_style == "gbt_7714_2015_numeric"

    updated = literature.update_style(
        "project-a",
        MedicalWritingCitationStyleUpdateRequest(
            citation_style="gbt_7714_2025_numeric",
            actor="medical_manager",
            idempotency_key="style-update-2025",
        ),
    )
    assert updated.citation_style == "gbt_7714_2025_numeric"
    assert MedicalWritingLiteratureRepository(repository.db_path).library(
        "project-a"
    ).citation_style == "gbt_7714_2025_numeric"
    assert repository.library("project-b").citation_style == "gbt_7714_2015_numeric"


def test_idempotency_key_reuse_with_different_reference_is_rejected(service):
    literature, _ = service
    literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input="10.1234/example.2025.01",
            idempotency_key="shared-import-key",
        ),
    )
    with pytest.raises(MedicalWritingLiteratureConflictError):
        literature.import_reference(
            "project-a",
            MedicalWritingReferenceImportRequest(
                source_input="10.1234/different.2025.02",
                idempotency_key="shared-import-key",
            ),
        )


def test_literature_api_uses_canonical_project_and_returns_project_library(service):
    literature, _ = service
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"\s*on_event is deprecated.*",
            category=DeprecationWarning,
        )
        from services.api.app import main as app_main

    client = TestClient(app_main.app)
    with patch.object(app_main, "medical_writing_literature_service", literature):
        imported = client.post(
            "/api/projects/proj_rux_03_002/medical-writing/literature/imports",
            json={
                "source_input": "PMID: 45678901",
                "actor": "medical_manager",
                "idempotency_key": "api-pmid-import-1",
            },
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["reference"]["project_id"] == "proj_rux_03_002"

        library = client.get(
            "/api/projects/proj_rux_03_002/medical-writing/literature"
        )
        assert library.status_code == 200, library.text
        assert library.json()["citation_style"] == "gbt_7714_2015_numeric"
        assert len(library.json()["references"]) == 1

        style = client.put(
            "/api/projects/proj_rux_03_002/medical-writing/literature/citation-style",
            json={
                "citation_style": "gbt_7714_2025_numeric",
                "actor": "medical_manager",
                "idempotency_key": "api-style-update-1",
            },
        )
        assert style.status_code == 200, style.text
        assert style.json()["citation_style"] == "gbt_7714_2025_numeric"


def test_doi_then_pmid_without_doi_merges_by_normalized_title_year(sequenced_service):
    literature, _, client = sequenced_service
    doi = "10.5555/identity.doi-first"
    pmid = "71000001"
    client.doi_records[doi] = _crossref_record(
        doi,
        title="Unicode: Identity\u00a0Graph -- Trial!",
    )
    client.pmid_records[pmid] = _pubmed_record(
        pmid,
        title="unicode： identity graph — trial.",
        doi="",
    )

    first = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=doi,
            idempotency_key="doi-then-pmid-0001",
        ),
    )
    second = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=f"PMID: {pmid}",
            idempotency_key="doi-then-pmid-0002",
        ),
    )

    assert second.created is False
    assert second.matched_on == "title_year"
    assert second.reference.reference_id == first.reference.reference_id
    assert second.reference.doi == doi
    assert second.reference.pmid == pmid
    assert len(literature.library("project-a").references) == 1


def test_pmid_then_doi_without_pmid_merges_by_normalized_title_year(sequenced_service):
    literature, _, client = sequenced_service
    doi = "10.5555/identity.pmid-first"
    pmid = "71000002"
    client.pmid_records[pmid] = _pubmed_record(pmid, doi="")
    client.doi_records[doi] = _crossref_record(doi)

    first = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=pmid,
            idempotency_key="pmid-then-doi-0001",
        ),
    )
    second = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=doi,
            idempotency_key="pmid-then-doi-0002",
        ),
    )

    assert second.reference.reference_id == first.reference.reference_id
    assert second.reference.doi == doi
    assert second.reference.pmid == pmid
    assert len(literature.library("project-a").references) == 1


def test_publisher_url_then_doi_merges_without_losing_publisher_url(sequenced_service):
    literature, _, client = sequenced_service
    url = "https://journal.example.org/articles/identity?utm_source=test"
    canonical_url = "https://journal.example.org/articles/identity"
    doi = "10.5555/identity.url-first"
    client.url_records[canonical_url] = _crossref_record(
        "",
        url=canonical_url,
    )
    client.doi_records[doi] = _crossref_record(doi)

    first = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=url,
            idempotency_key="url-then-doi-0001",
        ),
    )
    second = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=doi,
            idempotency_key="url-then-doi-0002",
        ),
    )

    assert second.reference.reference_id == first.reference.reference_id
    assert second.reference.doi == doi
    assert second.reference.url == canonical_url
    assert len(literature.library("project-a").references) == 1


def test_incoming_reference_bridges_two_historical_identity_rows_transactionally(
    sequenced_service,
):
    literature, repository, client = sequenced_service
    doi = "10.5555/identity.bridge"
    pmid = "71000003"
    client.doi_records[doi] = _crossref_record(doi, title="Bridge DOI record", year=2024)
    client.pmid_records[pmid] = _pubmed_record(
        pmid,
        title="Bridge PMID record.",
        year=2023,
        doi="",
    )
    doi_result = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=doi,
            idempotency_key="bridge-history-doi",
        ),
    )
    pmid_result = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=pmid,
            idempotency_key="bridge-history-pmid",
        ),
    )
    assert len(literature.library("project-a").references) == 2

    client.pmid_records[pmid] = _pubmed_record(
        pmid,
        title="Bridge DOI record with complete metadata.",
        doi=doi,
    )
    bridged = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=pmid,
            idempotency_key="bridge-connect-both",
        ),
    )

    survivor = min(
        (doi_result.reference, pmid_result.reference),
        key=lambda item: (item.created_at, item.reference_id),
    )
    assert bridged.created is False
    assert bridged.matched_on == "identity_graph"
    assert bridged.reference.reference_id == survivor.reference_id
    assert bridged.reference.doi == doi
    assert bridged.reference.pmid == pmid
    assert bridged.reference.title == "Bridge DOI record with complete metadata"
    assert len(literature.library("project-a").references) == 1
    merge_events = [
        event
        for event in _audit_events(repository, "project-a")
        if event["event_type"] == "reference_identity_merged"
    ]
    assert len(merge_events) == 1
    assert merge_events[0]["detail"]["survivor_reference_id"] == survivor.reference_id
    assert len(merge_events[0]["detail"]["absorbed_reference_ids"]) == 1

    replay = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=pmid,
            idempotency_key="bridge-history-pmid",
        ),
    )
    assert replay.reference.reference_id == survivor.reference_id


def test_bridge_merge_rolls_back_all_rows_when_a_mid_transaction_step_fails(
    sequenced_service,
    monkeypatch,
):
    literature, repository, client = sequenced_service
    doi = "10.5555/identity.rollback"
    pmid = "71000008"
    client.doi_records[doi] = _crossref_record(doi, title="Rollback DOI", year=2024)
    client.pmid_records[pmid] = _pubmed_record(
        pmid,
        title="Rollback PMID.",
        year=2023,
        doi="",
    )
    literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=doi,
            idempotency_key="rollback-history-doi",
        ),
    )
    literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=pmid,
            idempotency_key="rollback-history-pmid",
        ),
    )
    before = repository.library("project-a").model_dump()
    client.pmid_records[pmid] = _pubmed_record(
        pmid,
        title="Rollback bridge.",
        doi=doi,
    )

    def fail_after_row_mutation(*args, **kwargs):
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr(repository, "_remap_import_idempotency", fail_after_row_mutation)
    with pytest.raises(RuntimeError, match="injected transaction failure"):
        literature.import_reference(
            "project-a",
            MedicalWritingReferenceImportRequest(
                source_input=pmid,
                idempotency_key="rollback-bridge-attempt",
            ),
        )

    assert repository.library("project-a").model_dump() == before
    assert not any(
        event["event_type"] == "reference_identity_merged"
        for event in _audit_events(repository, "project-a")
    )


def test_shared_doi_with_conflicting_pmid_is_controlled_and_never_force_merged(
    sequenced_service,
):
    literature, repository, client = sequenced_service
    doi = "10.5555/identity.strong-conflict"
    client.doi_records[doi] = _crossref_record(doi)
    original = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=doi,
            manual_metadata=MedicalWritingReferenceManualMetadata(pmid="71000004"),
            idempotency_key="strong-conflict-base",
        ),
    )

    with pytest.raises(MedicalWritingLiteratureConflictError, match="needs_review"):
        literature.import_reference(
            "project-a",
            MedicalWritingReferenceImportRequest(
                source_input=doi,
                manual_metadata=MedicalWritingReferenceManualMetadata(pmid="71000005"),
                override_validation=True,
                override_reason="医学经理确认来源存在冲突，要求保留审计但不得自动合并。",
                idempotency_key="strong-conflict-override",
            ),
        )

    stored = literature.library("project-a").references
    assert len(stored) == 1
    assert stored[0].reference_id == original.reference.reference_id
    assert stored[0].pmid == "71000004"
    conflict_events = [
        event
        for event in _audit_events(repository, "project-a")
        if event["event_type"] == "reference_identity_conflict"
    ]
    assert conflict_events[-1]["detail"]["override_requested"] is True
    assert conflict_events[-1]["detail"]["override_reason"]


def test_provider_identifier_conflict_is_audited_and_returns_domain_conflict(
    sequenced_service,
):
    literature, repository, client = sequenced_service
    requested = "10.5555/identity.requested"
    client.doi_records[requested] = _crossref_record("10.5555/identity.received")

    with pytest.raises(MedicalWritingLiteratureConflictError, match="needs_review"):
        literature.import_reference(
            "project-a",
            MedicalWritingReferenceImportRequest(
                source_input=requested,
                override_validation=True,
                override_reason="医学经理要求保留来源标识矛盾的完整审计记录，不执行导入。",
                idempotency_key="provider-id-conflict",
            ),
        )

    assert literature.library("project-a").references == []
    event = _audit_events(repository, "project-a")[-1]
    assert event["event_type"] == "reference_identity_conflict"
    assert event["detail"]["requested"] == requested
    assert event["detail"]["received"] == "10.5555/identity.received"
    assert event["detail"]["override_reason"]


def test_identity_conflict_is_exposed_as_api_409_not_500(sequenced_service):
    literature, _, client = sequenced_service
    first_doi = "10.5555/identity.api-conflict-a"
    second_doi = "10.5555/identity.api-conflict-b"
    client.doi_records[first_doi] = _crossref_record(first_doi)
    client.doi_records[second_doi] = _crossref_record(second_doi)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"\s*on_event is deprecated.*",
            category=DeprecationWarning,
        )
        from services.api.app import main as app_main

    api = TestClient(app_main.app)
    with patch.object(app_main, "medical_writing_literature_service", literature):
        first = api.post(
            "/api/projects/proj_rux_03_002/medical-writing/literature/imports",
            json={
                "source_input": first_doi,
                "idempotency_key": "api-identity-conflict-a",
            },
        )
        conflict = api.post(
            "/api/projects/proj_rux_03_002/medical-writing/literature/imports",
            json={
                "source_input": second_doi,
                "idempotency_key": "api-identity-conflict-b",
            },
        )

    assert first.status_code == 200, first.text
    assert conflict.status_code == 409, conflict.text
    assert "needs_review" in conflict.json()["detail"]


def test_same_title_different_year_is_not_merged(sequenced_service):
    literature, _, client = sequenced_service
    first_doi = "10.5555/identity.year-2024"
    second_doi = "10.5555/identity.year-2025"
    client.doi_records[first_doi] = _crossref_record(first_doi, year=2024)
    client.doi_records[second_doi] = _crossref_record(second_doi, year=2025)

    literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=first_doi,
            idempotency_key="same-title-year-2024",
        ),
    )
    literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=second_doi,
            idempotency_key="same-title-year-2025",
        ),
    )

    assert len(literature.library("project-a").references) == 2


def test_same_title_year_with_different_strong_ids_requires_review_or_separate_override(
    sequenced_service,
):
    literature, repository, client = sequenced_service
    first_doi = "10.5555/identity.same-title-a"
    second_doi = "10.5555/identity.same-title-b"
    client.doi_records[first_doi] = _crossref_record(first_doi)
    client.doi_records[second_doi] = _crossref_record(second_doi)
    literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=first_doi,
            idempotency_key="weak-conflict-first",
        ),
    )

    with pytest.raises(MedicalWritingLiteratureConflictError, match="needs_review"):
        literature.import_reference(
            "project-a",
            MedicalWritingReferenceImportRequest(
                source_input=second_doi,
                idempotency_key="weak-conflict-rejected",
            ),
        )
    assert len(literature.library("project-a").references) == 1

    overridden = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=second_doi,
            override_validation=True,
            override_reason="医学经理核对全文后确认是同题同年但不同的两篇独立论文。",
            idempotency_key="weak-conflict-separate",
        ),
    )
    assert overridden.created is True
    assert overridden.reference.validation_status == "overridden"
    assert len(literature.library("project-a").references) == 2
    assert any(
        event["event_type"] == "reference_weak_identity_override_separate"
        for event in _audit_events(repository, "project-a")
    )


@pytest.mark.parametrize(
    ("source_input", "record_kind", "malformed", "message"),
    [
        (
            "10.5555/malformed.crossref",
            "doi",
            {
                "DOI": "10.5555/malformed.crossref",
                "title": ["Malformed Crossref metadata"],
                "author": "not-a-list",
                "container-title": {"unexpected": "shape"},
                "published-print": {"date-parts": {"bad": "shape"}},
                "URL": "https://doi.org/10.5555/malformed.crossref",
            },
            "元数据缺少作者",
        ),
        (
            "71000006",
            "pmid",
            {
                "uid": "71000006",
                "title": "Malformed PubMed metadata.",
                "authors": "not-a-list",
                "articleids": {"doi": "10.5555/not-a-list"},
                "pubdate": {"unexpected": "shape"},
            },
            "元数据缺少作者",
        ),
    ],
)
def test_malformed_provider_metadata_becomes_reviewable_not_runtime_error(
    sequenced_service,
    source_input,
    record_kind,
    malformed,
    message,
):
    literature, _, client = sequenced_service
    if record_kind == "doi":
        client.doi_records[source_input] = malformed
    else:
        client.pmid_records[source_input] = malformed

    result = literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=source_input,
            idempotency_key=f"malformed-{record_kind}-0001",
        ),
    )

    assert result.reference.validation_status == "needs_review"
    assert message in result.reference.validation_warnings


def test_metadata_with_invalid_title_shape_returns_domain_error(sequenced_service):
    literature, _, client = sequenced_service
    doi = "10.5555/malformed.title"
    client.doi_records[doi] = {
        "DOI": doi,
        "title": {"unexpected": "shape"},
        "author": [],
    }
    with pytest.raises(MedicalWritingLiteratureError, match="title is required"):
        literature.import_reference(
            "project-a",
            MedicalWritingReferenceImportRequest(
                source_input=doi,
                idempotency_key="malformed-title-0001",
            ),
        )


def test_identity_graph_is_project_scoped_and_replay_remains_idempotent(
    sequenced_service,
):
    literature, _, client = sequenced_service
    doi = "10.5555/identity.project-scope"
    pmid = "71000007"
    client.doi_records[doi] = _crossref_record(doi)
    client.pmid_records[pmid] = _pubmed_record(pmid, doi="")
    request = MedicalWritingReferenceImportRequest(
        source_input=doi,
        idempotency_key="cross-project-same-request",
    )

    project_a = literature.import_reference("project-a", request)
    project_a_replay = literature.import_reference("project-a", request)
    project_b = literature.import_reference("project-b", request)
    literature.import_reference(
        "project-a",
        MedicalWritingReferenceImportRequest(
            source_input=pmid,
            idempotency_key="cross-project-pmid-a",
        ),
    )

    assert project_a_replay.model_dump() == project_a.model_dump()
    assert project_a.reference.reference_id != project_b.reference.reference_id
    assert len(literature.library("project-a").references) == 1
    assert len(literature.library("project-b").references) == 1
