"""Source excerpts, NOT a patched product implementation.
Pinned commit: ee12adc88a8110c2443393ac7b4134356053c684.
Scope: WritingReferencePreparationBatchService._frozen_scope, lines 567-662
(see source ledger for requested retrieval range).
Download: WritingReferenceDocumentService.ingest prefix ending at fetch_binary.
The latter deliberately excludes PDF validation and storage; the probe intercepts
fetch_binary before network or file IO. Imports/ALLOWED_DOCUMENT_TYPES are the
minimal harness context. No full-module Git-blob equivalence is claimed.
"""
from typing import Any, Callable

ALLOWED_DOCUMENT_TYPES = {"protocol", "protocol_sap"}

class ScopeExcerpt:
    def _frozen_scope(self, project_id: str, snapshot_id: str) -> tuple[list[str], list[dict[str, Any]]]:
        journey = self.journey_service.get(project_id)
        triage = journey.corpus_triage
        corpus_finalized = triage.status == "finalized" and triage.snapshot_id == snapshot_id
        discovery = getattr(journey, "discovery_basket_projection", None)
        discovery_confirmed = (
            discovery is not None
            and discovery.confirmation_id
            and discovery.snapshot_id == snapshot_id
            and journey.search_plan is not None
            and journey.search_plan.latest_snapshot_id == snapshot_id
        )
        if not corpus_finalized and not discovery_confirmed:
            raise ValueError(
                "preparation requires either finalized corpus triage or a "
                "confirmed discovery basket projection for the locked snapshot"
            )
        if journey.search_plan is None or journey.search_plan.latest_snapshot_id != snapshot_id:
            raise ValueError("batch preparation must use the locked search snapshot")
        if corpus_finalized:
            retained_ids = sorted(dict.fromkeys(triage.retained_candidate_ids))
        elif discovery is not None:
            retained_ids = sorted(dict.fromkeys(discovery.retained_nct_ids))
        else:
            retained_ids = []
        if not retained_ids:
            raise ValueError("confirmed basket has no retained candidates")
        snapshot = self.repository.search_snapshot(project_id, snapshot_id)
        candidates = {candidate.nct_id: candidate for candidate in snapshot.candidates}
        missing = sorted(set(retained_ids) - set(candidates))
        if missing:
            raise ValueError("retained candidates are absent from the locked snapshot: " + ", ".join(missing))
        decisions = {
            decision.nct_id: decision
            for decision in self.repository.relevance_decisions_for_snapshot(project_id, snapshot_id)
        }
        invalid = [
            nct_id for nct_id in retained_ids
            if decisions.get(nct_id) is None
            or decisions[nct_id].relevance_status not in {"direct_competitor", "indirect_reference"}
        ]
        if invalid:
            raise ValueError("retained candidates lack a current related decision: " + ", ".join(invalid))
        entries: list[dict[str, Any]] = []
        for nct_id in retained_ids:
            candidate = candidates[nct_id]
            documents = sorted(
                (document for document in candidate.public_documents
                 if document.document_type.strip().casefold() in ALLOWED_DOCUMENT_TYPES),
                key=lambda document: (document.document_type, document.document_id),
            )
            if not documents:
                entries.append({"item_kind": "study_manual_upload_required", "nct_id": nct_id,
                                "document_id": "", "document_type": "", "filename": ""})
                continue
            for document in documents:
                entries.append({
                    "item_kind": "public_document", "nct_id": nct_id,
                    "document_id": document.document_id,
                    "document_type": document.document_type.strip().casefold(),
                    "filename": document.filename, "document_date": document.document_date,
                    "upload_date": document.upload_date, "declared_size": document.declared_size,
                    "download_url": document.download_url,
                })
        return retained_ids, entries

class DownloadPrefix:
    def ingest(self, project_id, request, *, progress_callback=None):
        import hashlib
        snapshot = self.repository.search_snapshot(project_id, request.snapshot_id)
        candidate = next((item for item in snapshot.candidates if item.nct_id == request.nct_id), None)
        if candidate is None:
            raise ValueError("candidate does not belong to search snapshot")
        decision = self.repository.relevance_decision(project_id, request.snapshot_id, request.nct_id)
        if decision.relevance_status not in {"direct_competitor", "indirect_reference"}:
            raise ValueError("candidate is not approved for document ingestion")
        source_document = next((item for item in candidate.public_documents
                                if item.document_id == request.document_id), None)
        if source_document is None:
            raise ValueError("public document does not belong to candidate")
        artifact_id = "wref_doc_" + hashlib.sha256(
            (f"{project_id}|{request.snapshot_id}|{request.nct_id}|"
             f"{request.document_id}|{source_document.download_url}").encode("utf-8")
        ).hexdigest()[:20]
        try:
            return self.repository.document_artifact(project_id, artifact_id)
        except KeyError:
            pass
        if progress_callback is not None:
            progress_callback({"phase": "downloading", "current_substep": "正在下载公开 Protocol（研究方案）",
                               "completed": 0, "total": 1, "unit": "file"})
        fetched = self.client.fetch_binary(source_document.download_url, accept="application/pdf")
        # Excerpt ends here. Tests intercept fetch_binary; no downstream claim.
