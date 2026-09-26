"""A19 recoverable starting points for writing-reference slices (0927V1 §7).

Builds named starts through REAL service chains only:

- ``F1`` 方案已抽取: repository → DocumentService.ingest →
  ExtractionService.extract → validation override (medical-manager decision
  through the product API) → PreparationBatchService.create/run_pending.
- ``F2`` 候选译文已保存: repository seed via PUBLIC repository write APIs
  (the repo's own durable-jobs test precedent) → WritingReferenceTranslation-
  Service + deterministic offline composite pipeline →
  TranslationBatchService.create/run_pending until candidates are ready
  (durable job complete). No network, no models.
- ``F3`` 工作稿已保存: MedicalWritingAuthoringJourneyService.create →
  save_stage_draft (framing) through the real authoring journey.

Every start carries a manifest (format, schema/contract versions, source
digests, declared boundary fakes, state digest). Reload = SQLite file copy
into a per-test dir + manifest validation; schema drift raises
StartManifestMismatch (rebuild or explicit migrate — never silent, never a
raw-SQL status rewrite). The module itself contains no SQL statements: all
reads and writes go through product services and repository APIs.

Boundary fakes (declared per start in ``boundary_fakes``): the document
download HTTP boundary (``_ControlledDocumentClient``, the repo's documented
preparation-batch test pattern) and the upstream search/journey/preparation
lookup collaborators for F2 (the repo's translation test pattern). Business
state changes always flow through product services.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from packages.contracts.workbench_contracts.models import (
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingAuthoringJourneyDraftSaveRequest,
    MedicalWritingStudyFraming,
    WritingReferenceDocumentArtifact,
    WritingReferenceDocumentIngestRequest,
    WritingReferenceDocumentValidationRecord,
    WritingReferenceExtractedSpan,
    WritingReferenceExtractionResult,
    WritingReferencePreparationBatchCreateRequest,
    WritingReferencePublicDocument,
    WritingReferenceTranslationBatchCreateRequest,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_durable_jobs import DurableJobStore
from services.api.app.writing_reference import (
    WritingReferenceDocumentService,
    WritingReferenceExtractionService,
    WritingReferenceTranslationService,
)
from services.api.app.writing_reference_preparation_batch import (
    WritingReferencePreparationBatchService,
)
from services.api.app.writing_reference_repository import (
    SCHEMA_VERSION,
    WritingReferenceRepository,
)
from services.api.app.writing_reference_translation_batch import (
    WritingReferenceTranslationBatchService,
)
from tests._composite_pipeline_fixture import (
    build_deterministic_pipeline,
    wire_pipeline_calls_to_runner,
)
from tests.test_writing_reference_extraction import pdf_fixture
from tests.test_writing_reference_repository import NOW, snapshot
from tests.test_writing_reference_translation_batch import (
    FakeJourneyService,
    FakePreparationService,
    FakeTranslationRunner,
    GLOSSARY_VERSION,
    NCT_ID,
    PROJECT_ID,
    SNAPSHOT_ID,
)

MANIFEST_FORMAT = "writing_reference_start/1"
BUILDER_VERSION = "1"
REPO_ROOT = Path(__file__).resolve().parents[2]

F1_PROJECT_ID = "proj_user_0f1e2d3c4b5a"
F1_SNAPSHOT_ID = "wref_search_f1_locked"
F1_NCT_ID = "NCT04567890"
F3_PROJECT_ID = "proj_user_9a8b7c6d5e4f"

_START_KINDS = ("F1", "F2", "F3")


class StartManifestMismatch(Exception):
    """Manifest identity does not match the tree/DB — rebuild explicitly."""


@dataclass
class StartHandle:
    dir: Path
    manifest: dict

    @property
    def repo_path(self) -> Path:
        return self.dir / "writing_reference.sqlite3"

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


@dataclass
class LoadedStart:
    dir: Path
    repo_path: Path
    manifest: dict


# ------------------------------------------------------------ boundary fakes


class _ControlledDocumentClient:
    """Stands in for the public-document HTTP download boundary only."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def fetch_binary(self, url: str, *, accept: str):
        self.calls.append(url)
        return SimpleNamespace(payload=self.payload, final_url=url,
                               content_type="application/pdf")


class _FrozenJourneyLock:
    """Read-only stand-in for the authoring journey lock/snapshot lookups.

    Shape mirrors the real journey read surface consumed by the preparation
    service (search_plan / corpus_triage / framing / picos), with a REAL
    MedicalWritingStudyFraming so the study-facts hash binds actual facts.
    """

    def __init__(self, framing=None, picos=None) -> None:
        self._framing = framing
        self._picos = picos
        self.states: dict[str, SimpleNamespace] = {}

    def lock(self, project_id: str, snapshot_id: str,
             retained_ids: list[str]) -> None:
        self.states[project_id] = SimpleNamespace(
            revision=1,
            search_plan=SimpleNamespace(latest_snapshot_id=snapshot_id),
            corpus_triage=SimpleNamespace(
                status="finalized",
                snapshot_id=snapshot_id,
                retained_candidate_ids=retained_ids,
            ),
            framing=self._framing,
            picos=self._picos,
            framing_draft=None,
            picos_draft=None,
            discovery_basket_projection=None,
        )

    def get(self, project_id: str) -> SimpleNamespace:
        return self.states[project_id]


# ------------------------------------------------------------- identity bits


def current_repo_schema_version() -> int:
    return SCHEMA_VERSION


def current_api_contract_version() -> str:
    contract = REPO_ROOT / "packages" / "contracts" / "workbench_contracts" / \
        "runtime_contract.json"
    doc = json.loads(contract.read_text(encoding="utf-8"))
    return str(doc["api_contract_version"])


def _state_digest(state: dict) -> str:
    payload = json.dumps(state, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manifest_identity_ok(manifest: dict) -> None:
    if manifest.get("format") != MANIFEST_FORMAT:
        raise StartManifestMismatch(
            f"manifest format {manifest.get('format')!r} is not {MANIFEST_FORMAT}")
    if manifest.get("repo_schema_version") != current_repo_schema_version():
        raise StartManifestMismatch(
            f"repo schema moved: manifest {manifest.get('repo_schema_version')} "
            f"vs current {current_repo_schema_version()}; rebuild or migrate explicitly")
    if manifest.get("api_contract_version") != current_api_contract_version():
        raise StartManifestMismatch(
            f"api contract moved: manifest {manifest.get('api_contract_version')} "
            f"vs current {current_api_contract_version()}")


def _write_manifest(root: Path, manifest: dict) -> None:
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def _read_manifest(directory: Path) -> dict:
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ F1 chain


def _public_document(nct_id: str, payload_size: int) -> WritingReferencePublicDocument:
    return WritingReferencePublicDocument(
        document_id=f"ctgov_{nct_id}_protocol",
        nct_id=nct_id,
        document_type="protocol",
        label="PROTOCOL",
        filename=f"{nct_id}_Protocol.pdf",
        document_date="",
        declared_size=payload_size,
        download_url=(
            f"https://clinicaltrials.gov/ProvidedDocs/{nct_id[-2:]}/{nct_id}/"
            f"{nct_id}_Protocol.pdf"
        ),
    )


def _project_snapshot(project_id: str, snapshot_id: str, nct_id: str,
                      documents: list[WritingReferencePublicDocument]):
    base = snapshot()
    candidate = base.candidates[0].model_copy(
        update={
            "nct_id": nct_id,
            "study_record_url": f"https://clinicaltrials.gov/study/{nct_id}",
            "public_documents": list(documents),
        },
        deep=True,
    )
    return base.model_copy(
        update={"project_id": project_id, "snapshot_id": snapshot_id,
                "candidates": [candidate]},
        deep=True,
    )


def _f1_services(repo: WritingReferenceRepository, root: Path):
    client = _ControlledDocumentClient(pdf_fixture())
    document_service = WritingReferenceDocumentService(
        repo, client, artifact_root=root / "artifacts", clock=lambda: NOW)
    extraction_service = WritingReferenceExtractionService(
        repo, artifact_root=root / "artifacts")
    journeys = _FrozenJourneyLock(framing=_f1_framing(), picos=None)
    service = WritingReferencePreparationBatchService(
        repo, journeys, document_service, extraction_service, clock=lambda: NOW)
    return service, journeys, document_service, extraction_service


def _f1_state(service, repo: WritingReferenceRepository, root: Path,
              project_id: str) -> dict:
    batch_id = _read_manifest(root)["state"]["batch_id"]
    batch = service.get(project_id, batch_id)
    return {"project_id": project_id, "snapshot_id": batch.snapshot_id,
            "batch_id": batch.batch_id, "status": batch.status,
            "document_item_count": batch.document_item_count}


def _build_f1(root: Path, manifest: dict) -> None:
    repo = WritingReferenceRepository(root / "writing_reference.sqlite3")
    service, journeys, document_service, extraction_service = _f1_services(
        repo, root)
    payload = pdf_fixture()
    document = _public_document(F1_NCT_ID, len(payload))
    source_snapshot = _project_snapshot(
        F1_PROJECT_ID, F1_SNAPSHOT_ID, F1_NCT_ID, [document])
    repo.save_search_snapshot(
        source_snapshot,
        idempotency_key=f"fixture-f1-{F1_SNAPSHOT_ID}-snapshot")
    repo.record_relevance_decision(
        project_id=F1_PROJECT_ID,
        snapshot_id=F1_SNAPSHOT_ID,
        nct_id=F1_NCT_ID,
        relevance_status="direct_competitor",
        reason="Fixture start: locked direct competitor for offline slices.",
        actor="medical_manager",
        expected_revision=0,
        idempotency_key=f"fixture-f1-{F1_SNAPSHOT_ID}-decision",
    )
    journeys.lock(F1_PROJECT_ID, F1_SNAPSHOT_ID, [F1_NCT_ID])

    accepted_ingest = document_service.ingest(
        F1_PROJECT_ID,
        WritingReferenceDocumentIngestRequest(
            snapshot_id=F1_SNAPSHOT_ID,
            nct_id=F1_NCT_ID,
            document_id=document.document_id,
            actor="medical_manager",
            idempotency_key="fixture-f1-protocol-ingest-001",
        ),
    )
    extraction_service.extract(
        F1_PROJECT_ID,
        accepted_ingest.artifact_id,
        actor="medical_manager",
        extraction_idempotency_key="fixture-f1-protocol-extract-001",
    )
    validation = repo.document_validation(F1_PROJECT_ID, accepted_ingest.artifact_id)
    warnings = sorted(check.check_code for check in validation.checks
                      if check.outcome in {"warning", "mismatch"})
    if warnings:
        repo.override_document_validation(
            project_id=F1_PROJECT_ID,
            artifact_id=accepted_ingest.artifact_id,
            reason="Fixture start: medical manager confirmed the public protocol.",
            acknowledged_warning_codes=warnings,
            actor="medical_manager",
            expected_revision=validation.revision,
            idempotency_key="fixture-f1-validation-override-001",
        )
    accepted = service.create(
        F1_PROJECT_ID,
        WritingReferencePreparationBatchCreateRequest(
            snapshot_id=F1_SNAPSHOT_ID,
            actor="medical_manager",
            idempotency_key="fixture-f1-preparation-create-001",
        ),
    )
    service.run_pending(F1_PROJECT_ID, accepted.batch_id, "medical_manager")
    final = service.get(F1_PROJECT_ID, accepted.batch_id)
    manifest["state"] = {
        "project_id": F1_PROJECT_ID,
        "snapshot_id": F1_SNAPSHOT_ID,
        "batch_id": final.batch_id,
        "status": final.status,
        "document_item_count": final.document_item_count,
    }
    manifest["state_sha256"] = _state_digest(manifest["state"])


def _verify_f1(root: Path, manifest: dict) -> None:
    repo = WritingReferenceRepository(root / "writing_reference.sqlite3")
    service, _journeys, _document_service, _extraction_service = _f1_services(
        repo, root)
    state = manifest["state"]
    batch = service.get(state["project_id"], state["batch_id"])
    current = {"project_id": state["project_id"],
               "snapshot_id": batch.snapshot_id,
               "batch_id": batch.batch_id, "status": batch.status,
               "document_item_count": batch.document_item_count}
    if _state_digest(current) != manifest["state_sha256"]:
        raise StartManifestMismatch(
            "F1 state digest mismatch: the database content no longer matches "
            "the manifest (possible direct-SQL tampering or silent drift)")


# ------------------------------------------------------------------ F2 chain


def _seed_extraction_input(repo: WritingReferenceRepository,
                           artifact_id: str) -> None:
    """Seed via PUBLIC repository write APIs (durable-jobs test precedent)."""
    spans = [
        ("span_eligibility", "eligibility", "Participants are eligible."),
        ("span_scs", "endpoints",
         "Participants must not receive SCS within 14 days."),
    ]
    artifact_hash = hashlib.sha256(artifact_id.encode("utf-8")).hexdigest()
    artifact = WritingReferenceDocumentArtifact(
        artifact_id=artifact_id,
        project_id=PROJECT_ID,
        snapshot_id=SNAPSHOT_ID,
        nct_id=NCT_ID,
        source_document_id=f"source_{artifact_id}",
        document_type="protocol",
        filename=f"{artifact_id}.pdf",
        requested_url=f"https://clinicaltrials.gov/{artifact_id}.pdf",
        final_url=f"https://clinicaltrials.gov/{artifact_id}.pdf",
        content_type="application/pdf",
        actual_size=1024,
        content_sha256=artifact_hash,
        created_by="medical_manager",
        created_at=NOW,
    )
    repo.save_document_artifact(
        artifact,
        storage_relpath=f"safe/{artifact_id}.pdf",
        idempotency_key=f"fixture-f2-{artifact_id}-artifact",
    )
    extracted = [
        WritingReferenceExtractedSpan(
            span_id=span_id,
            project_id=PROJECT_ID,
            artifact_id=artifact_id,
            extraction_revision="extract_r1",
            physical_page=index + 1,
            block_index=index,
            source_locator=f"ctgov:{NCT_ID}:{artifact_id}:p{index + 1}:b{index}",
            ich_m11_anchor=anchor,
            source_text=text,
            source_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        for index, (span_id, anchor, text) in enumerate(spans)
    ]
    repo.save_extraction(
        WritingReferenceExtractionResult(
            artifact_id=artifact_id,
            project_id=PROJECT_ID,
            extraction_revision="extract_r1",
            parser_name="fixture_parser",
            parser_version="1",
            page_count=1,
            status="pending_visual_and_medical_structure_review",
            spans=extracted,
        ),
        idempotency_key=f"fixture-f2-{artifact_id}-extract_r1",
    )
    repo.save_document_validation(
        WritingReferenceDocumentValidationRecord(
            validation_id=f"validation_{artifact_id}",
            project_id=PROJECT_ID,
            artifact_id=artifact_id,
            revision=1,
            status="confirmed",
            document_sha256=artifact_hash,
            extraction_revision="extract_r1",
            source_state_revision=1,
            summary="Fixture start: content confirmed for offline translation.",
            actor="medical_manager",
            created_at=NOW,
        ),
        expected_revision=0,
        idempotency_key=f"fixture-f2-{artifact_id}-validation",
    )
    repo.record_extraction_review(
        project_id=PROJECT_ID,
        artifact_id=artifact_id,
        extraction_revision="extract_r1",
        decision="approved",
        confirmed_anchor_coverage=sorted({anchor for _, anchor, _ in spans}),
        unresolved_structure_issues=[],
        comment="Fixture start: structure review through the product API.",
        actor="medical_manager",
        expected_revision=0,
        idempotency_key=f"fixture-f2-{artifact_id}-structure-review",
    )


def _f2_services(repo: WritingReferenceRepository, root: Path):
    durable_store = DurableJobStore(
        root / "durable_jobs.sqlite3",
        lease_seconds=600.0,
        heartbeat_interval_seconds=30.0,
    )
    journeys = FakeJourneyService()
    journeys.lock(PROJECT_ID, SNAPSHOT_ID, [NCT_ID])
    preparation = FakePreparationService()
    preparation.set(PROJECT_ID, SNAPSHOT_ID)
    runner = FakeTranslationRunner()
    pipeline, _planner, translator, _qc = build_deterministic_pipeline()
    translator.translations = runner.TRANSLATIONS
    wire_pipeline_calls_to_runner(runner, translator)
    translation_service = WritingReferenceTranslationService(
        repo, runner, clock=lambda: NOW, chapter_pipeline=pipeline)
    batch_service = WritingReferenceTranslationBatchService(
        repo, journeys, preparation, translation_service, clock=lambda: NOW,
        chapter_pipeline=pipeline, durable_store=durable_store)
    return batch_service


def _f2_state(batch_service, root: Path) -> dict:
    state = _read_manifest(root)["state"]
    batch = batch_service.get(state["project_id"], state["batch_id"])
    return {"project_id": state["project_id"], "snapshot_id": SNAPSHOT_ID,
            "batch_id": batch.batch_id, "status": batch.status,
            "candidate_ready_count": sum(
                1 for item in batch.items
                if item.generation_status == "candidate_ready")}


def _build_f2(root: Path, manifest: dict) -> None:
    repo = WritingReferenceRepository(root / "writing_reference.sqlite3")
    source_snapshot = snapshot().model_copy(
        update={"project_id": PROJECT_ID, "snapshot_id": SNAPSHOT_ID}, deep=True)
    repo.save_search_snapshot(
        source_snapshot, idempotency_key="fixture-f2-search-snapshot")
    _seed_extraction_input(repo, "artifact_fixture_f2")
    batch_service = _f2_services(repo, root)
    batch = batch_service.create(
        PROJECT_ID,
        WritingReferenceTranslationBatchCreateRequest(
            snapshot_id=SNAPSHOT_ID,
            glossary_version=GLOSSARY_VERSION,
            anchor_filter=[],
            actor="medical_manager",
            idempotency_key="fixture-f2-translation-create-001",
        ),
    )
    batch_service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
    final = batch_service.get(PROJECT_ID, batch.batch_id)
    manifest["state"] = {
        "project_id": PROJECT_ID,
        "snapshot_id": SNAPSHOT_ID,
        "batch_id": final.batch_id,
        "status": final.status,
        "candidate_ready_count": sum(
            1 for item in final.items
            if item.generation_status == "candidate_ready"),
    }
    manifest["state_sha256"] = _state_digest(manifest["state"])


def _verify_f2(root: Path, manifest: dict) -> None:
    repo = WritingReferenceRepository(root / "writing_reference.sqlite3")
    batch_service = _f2_services(repo, root)
    if _state_digest(_f2_state(batch_service, root)) != manifest["state_sha256"]:
        raise StartManifestMismatch(
            "F2 state digest mismatch against the manifest")


# ------------------------------------------------------------------ F3 chain


def _f1_framing() -> MedicalWritingStudyFraming:
    return MedicalWritingStudyFraming(
        protocol_id="FIXTURE-01-001",
        document_title="Fixture起步点：方案已抽取",
        investigational_product="Fixture研究药物",
        indication="Fixture适应症",
        study_phase="III期",
        intrinsic_objectives=["确证性研究"],
        target_mechanism="Fixture靶点",
        design_pattern="随机、双盲、安慰剂对照",
        population_intent="Fixture目标人群",
    )


def _f3_framing() -> MedicalWritingStudyFraming:
    return MedicalWritingStudyFraming(
        protocol_id="FIXTURE-03-001",
        document_title="Fixture起步点：离线写作工作稿已保存",
        investigational_product="Fixture研究药物",
        indication="Fixture适应症",
        study_phase="III期",
        intrinsic_objectives=["确证性研究"],
        target_mechanism="Fixture靶点",
        design_pattern="随机、双盲、安慰剂对照",
        population_intent="Fixture目标人群",
    )


def _build_f3(root: Path, manifest: dict) -> None:
    service = MedicalWritingAuthoringJourneyService(
        root / "medical_writing_authoring_journey.sqlite3")
    created = service.create(
        F3_PROJECT_ID,
        MedicalWritingAuthoringJourneyCreateRequest(
            actor="medical_manager",
            idempotency_key="fixture-f3-journey-create-001",
        ),
    )
    saved = service.save_stage_draft(
        F3_PROJECT_ID,
        MedicalWritingAuthoringJourneyDraftSaveRequest(
            expected_revision=created.revision,
            stage="framing",
            framing=_f3_framing(),
            actor="medical_manager",
            idempotency_key="fixture-f3-framing-draft-save-001",
        ),
    )
    manifest["state"] = {
        "db": "medical_writing_authoring_journey.sqlite3",
        "project_id": F3_PROJECT_ID,
        "revision": saved.revision,
        "stage": "framing",
    }
    manifest["state_sha256"] = _state_digest(manifest["state"])


def _verify_f3(root: Path, manifest: dict) -> None:
    state = manifest["state"]
    service = MedicalWritingAuthoringJourneyService(root / state["db"])
    current = service.get(state["project_id"])
    current_state = {"db": state["db"], "project_id": state["project_id"],
                     "revision": current.revision, "stage": "framing"}
    if _state_digest(current_state) != manifest["state_sha256"]:
        raise StartManifestMismatch(
            "F3 state digest mismatch against the manifest")


# ----------------------------------------------------------------- public API


_BUILDERS = {"F1": _build_f1, "F2": _build_f2, "F3": _build_f3}
_VERIFIERS = {"F1": _verify_f1, "F2": _verify_f2, "F3": _verify_f3}

_BOUNDARY_FAKES = {
    "F1": ["_ControlledDocumentClient(public-document HTTP download boundary)",
           "_FrozenJourneyLock(search journey snapshot lookups)"],
    "F2": ["FakeJourneyService/FakePreparationService/FakeTranslationRunner "
           "(translation test-suite collaborators, repo precedent)",
           "extraction input seeded via PUBLIC repository write APIs"],
    "F3": [],
}


def build_start(kind: str, root: Path) -> StartHandle:
    """Build a named start through real service chains under ``root``."""
    if kind not in _START_KINDS:
        raise ValueError(f"unknown start kind {kind!r}; expected {_START_KINDS}")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    payload = pdf_fixture()
    manifest = {
        "format": MANIFEST_FORMAT,
        "start_kind": kind,
        "api_contract_version": current_api_contract_version(),
        "repo_schema_version": current_repo_schema_version(),
        "builder_version": BUILDER_VERSION,
        "source_sha256": {
            "protocol_pdf": hashlib.sha256(payload).hexdigest(),
        },
        "boundary_fakes": _BOUNDARY_FAKES[kind],
    }
    _BUILDERS[kind](root, manifest)
    _write_manifest(root, manifest)
    return StartHandle(dir=root, manifest=manifest)


def load_start_copy(source_dir: Path, target_dir: Path) -> LoadedStart:
    """Validate the manifest against CURRENT identity, then copy the SQLite
    files into ``target_dir`` for a per-test private copy."""
    source_dir, target_dir = Path(source_dir), Path(target_dir)
    manifest = _read_manifest(source_dir)
    _manifest_identity_ok(manifest)
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    # include -wal/-shm sidecars: services may keep the WAL not yet
    # checkpointed into the main db file, and a partial copy would silently
    # lose the most recent committed state
    for db_file in sorted(source_dir.glob("*.sqlite3*")):
        shutil.copy2(db_file, target_dir / db_file.name)
        copied += 1
    if not copied:
        raise StartManifestMismatch(f"no sqlite files under {source_dir}")
    # the copy is self-describing: manifest travels with the databases
    shutil.copy2(source_dir / "manifest.json", target_dir / "manifest.json")
    return LoadedStart(dir=target_dir,
                       repo_path=target_dir / "writing_reference.sqlite3",
                       manifest=manifest)


def verify_start(directory: Path) -> dict:
    """Re-read the start through product getters and compare state digests."""
    directory = Path(directory)
    manifest = _read_manifest(directory)
    _manifest_identity_ok(manifest)
    _VERIFIERS[manifest["start_kind"]](directory, manifest)
    return manifest
