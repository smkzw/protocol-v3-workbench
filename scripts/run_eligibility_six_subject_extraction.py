#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_eligibility_six_subject_matrix import FIXED_COHORT  # noqa: E402
from services.api.app.eligibility import (  # noqa: E402
    RAW_INTAKE_PROJECTS,
    _review_source_rows,
    raw_intake_service,
)
from services.api.app.eligibility_artifact_store import (  # noqa: E402
    ArtifactAlreadyExistsError,
    EligibilityArtifactMetadata,
    EligibilityArtifactStore,
)
from services.api.app.eligibility_evidence_tasks import (  # noqa: E402
    EligibilityEvidenceTaskService,
    EvidenceSourceIdentity,
)
from services.api.app.eligibility_evidence_worker import (  # noqa: E402
    EligibilityEvidenceWorker,
)
from services.api.app.ocr_gateway import (  # noqa: E402
    LocalOcrGateway,
    OCR_PROFILE_MODELS,
    OcrGatewaySettings,
)
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore  # noqa: E402


SCHEMA_VERSION = "eligibility_six_subject_extraction_status_v1"
ALLOWED_PROFILES = frozenset(OCR_PROFILE_MODELS)
ACTIVE_RUNTIME_DIR = (ROOT / "runtime").resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def validate_isolated_paths(runtime_dir: Path, artifact_dir: Path) -> None:
    runtime = runtime_dir.expanduser().resolve()
    artifacts = artifact_dir.expanduser().resolve()
    if any(
        path == ACTIVE_RUNTIME_DIR or _is_relative_to(path, ACTIVE_RUNTIME_DIR)
        for path in (runtime, artifacts)
    ):
        raise ValueError("six-subject extraction cannot use the active runtime")
    source_roots = tuple(
        Path(RAW_INTAKE_PROJECTS[project_id].raw_subject_root)
        .expanduser()
        .resolve(strict=True)
        for project_id in FIXED_COHORT
    )
    if any(
        _is_relative_to(runtime, root)
        or _is_relative_to(artifacts, root)
        or _is_relative_to(root, runtime)
        or _is_relative_to(root, artifacts)
        for root in source_roots
    ):
        raise ValueError("runtime and artifact paths must be isolated from sources")


def load_manifests() -> Dict[str, list[Any]]:
    manifests: Dict[str, list[Any]] = {}
    for project_id, subject_ids in FIXED_COHORT.items():
        config = RAW_INTAKE_PROJECTS[project_id]
        manifests[project_id] = [
            raw_intake_service.subject_manifest(config, subject_id)
            for subject_id in subject_ids
        ]
    return manifests


def planned_counts(manifests: Mapping[str, Sequence[Any]]) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for project_manifests in manifests.values():
        for manifest in project_manifests:
            for source in manifest.sources:
                if source.source_type == "pdf":
                    counts["pdf_text_extraction"] += 1
                    counts["pdf_page_render"] += 1
                    counts["expected_pdf_ocr_children"] += int(
                        source.expected_unit_count
                    )
                elif source.source_type == "image":
                    counts["direct_image_ocr"] += 1
                elif source.source_type in {"doc", "docx"}:
                    counts["blocked_document_sources"] += 1
                elif source.source_type == "archive":
                    counts["blocked_archive_sources"] += 1
                else:
                    counts["blocked_unclassified_sources"] += 1
    counts["expected_ocr_calls"] = (
        counts["expected_pdf_ocr_children"] + counts["direct_image_ocr"]
    )
    return dict(sorted(counts.items()))


def register_sources(
    store: SqliteRuntimeStore,
    manifests: Mapping[str, Sequence[Any]],
) -> None:
    for project_id, project_manifests in manifests.items():
        for manifest in project_manifests:
            store.replace_eligibility_subject_sources(
                project_id,
                manifest.subject_id,
                manifest.subject_source_revision,
                _review_source_rows(manifest),
            )


def _source_identities(manifest: Any) -> tuple[EvidenceSourceIdentity, ...]:
    return tuple(
        EvidenceSourceIdentity(
            source_id=source.source_id,
            source_revision=source.source_revision,
            media_class=source.source_type,
        )
        for source in manifest.sources
    )


def seed_jobs(
    store: SqliteRuntimeStore,
    manifests: Mapping[str, Sequence[Any]],
    *,
    profile_version: str,
    max_new_jobs: int,
) -> Dict[str, int]:
    if profile_version not in ALLOWED_PROFILES:
        raise ValueError("OCR profile is not allowlisted")
    service = EligibilityEvidenceTaskService(store)
    counts: Counter[str] = Counter()
    stop = False
    for project_id, project_manifests in manifests.items():
        for manifest in project_manifests:
            identities = _source_identities(manifest)
            for source in manifest.sources:
                specifications = []
                if source.source_type == "pdf":
                    specifications = [
                        ("pdf_text_extraction", "pdf-text-pymupdf-v1"),
                        ("pdf_page_render", "pdf-render-200dpi-v1"),
                    ]
                elif source.source_type == "image":
                    specifications = [("ocr", profile_version)]
                else:
                    counts[f"blocked_{source.source_type}"] += 1
                for job_kind, job_profile in specifications:
                    if counts["created"] >= max_new_jobs:
                        stop = True
                        break
                    result = service.create_job(
                        project_id=project_id,
                        subject_id=manifest.subject_id,
                        subject_source_revision=manifest.subject_source_revision,
                        sources=identities,
                        source_id=source.source_id,
                        job_kind=job_kind,
                        profile_version=job_profile,
                        idempotency_key=(
                            "six-subject-extraction-v1:"
                            f"{manifest.subject_source_revision}:"
                            f"{source.source_id}:{job_kind}:{job_profile}"
                        ),
                        priority=0,
                        max_attempts=3,
                    )
                    counts["replayed" if result["replayed"] else "created"] += 1
                    counts[f"job_kind_{job_kind}"] += 1
                if stop:
                    break
            if stop:
                break
        if stop:
            break
    return dict(sorted(counts.items()))


def _source_resolver(job: Dict[str, object]) -> Path:
    project_id = str(job["project_id"])
    config = RAW_INTAKE_PROJECTS.get(project_id)
    if config is None or project_id not in FIXED_COHORT:
        raise KeyError("eligibility evidence project is not in the fixed cohort")
    return raw_intake_service.resolve_subject_source_path(
        config,
        str(job["subject_id"]),
        str(job["source_id"]),
        str(job["source_revision"]),
    )


def build_workers(
    store: SqliteRuntimeStore,
    artifact_store: EligibilityArtifactStore,
    *,
    profile_version: str,
    base_url: str,
    timeout_seconds: float,
) -> Dict[str, EligibilityEvidenceWorker]:
    allowed_roots = tuple(
        Path(RAW_INTAKE_PROJECTS[project_id].raw_subject_root)
        .expanduser()
        .resolve(strict=True)
        for project_id in FIXED_COHORT
    )
    gateway = LocalOcrGateway(
        OcrGatewaySettings(
            allowed_roots=allowed_roots,
            base_url=base_url,
            model=OCR_PROFILE_MODELS[profile_version],
            timeout_seconds=timeout_seconds,
            api_key=os.environ.get("WORKBENCH_OCR_API_KEY", ""),
        )
    )
    text_worker = EligibilityEvidenceWorker(
        store=store,
        artifact_store=artifact_store,
        source_resolver=_source_resolver,
        profile_version="pdf-text-pymupdf-v1",
    )
    render_worker = EligibilityEvidenceWorker(
        store=store,
        artifact_store=artifact_store,
        source_resolver=_source_resolver,
        profile_version="pdf-render-200dpi-v1",
        ocr_child_profiles=(profile_version,),
    )
    ocr_worker = EligibilityEvidenceWorker(
        store=store,
        artifact_store=artifact_store,
        source_resolver=_source_resolver,
        ocr_gateway=gateway,
        profile_version=profile_version,
    )
    return {
        "text": text_worker,
        "render": render_worker,
        "ocr": ocr_worker,
    }


def run_workers(
    workers: Iterable[EligibilityEvidenceWorker],
    *,
    max_worker_runs: int,
) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    run_token = uuid4().hex[:12]
    for stage_index, worker in enumerate(workers, start=1):
        while counts["worker_runs"] < max_worker_runs:
            result = worker.run_once(
                f"six-subject-{run_token}-stage-{stage_index}"
            )
            if result is None:
                break
            counts["worker_runs"] += 1
            counts[f"result_{result['status']}"] += 1
        if max_worker_runs is not None and counts["worker_runs"] >= max_worker_runs:
            break
    return dict(sorted(counts.items()))


def status_summary(
    store: SqliteRuntimeStore,
    manifests: Mapping[str, Sequence[Any]],
) -> Dict[str, Any]:
    with store._connect() as connection:
        jobs = {
            f"{row['job_kind']}:{row['status']}": int(row["count"])
            for row in connection.execute(
                """
                SELECT job_kind, status, COUNT(*) AS count
                FROM eligibility_evidence_jobs
                GROUP BY job_kind, status
                ORDER BY job_kind, status
                """
            ).fetchall()
        }
        source_row = connection.execute(
            """
            SELECT COUNT(*) AS sources,
                   COALESCE(SUM(expected_unit_count), 0) AS expected_units
            FROM eligibility_source_revisions
            WHERE is_current = 1
            """
        ).fetchone()
        counts = {
            "current_sources": int(source_row["sources"] or 0),
            "expected_units": int(source_row["expected_units"] or 0),
            "artifacts": int(
                connection.execute(
                    "SELECT COUNT(*) FROM eligibility_evidence_artifacts"
                ).fetchone()[0]
            ),
            "evidence_spans": int(
                connection.execute(
                    "SELECT COUNT(*) FROM eligibility_evidence_spans"
                ).fetchone()[0]
            ),
            "resolved_units": int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM eligibility_source_processing_unit_state
                    WHERE processing_status IN (
                        'evidence_extracted', 'processed_no_relevant_evidence'
                    )
                    """
                ).fetchone()[0]
            ),
        }
    gate_states: Counter[str] = Counter()
    for project_id, project_manifests in manifests.items():
        for manifest in project_manifests:
            state = store.eligibility_ai_source_unit_contract_state(
                project_id=project_id,
                subject_id=manifest.subject_id,
                subject_source_revision=manifest.subject_source_revision,
            )
            gate_states[state] += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "counts": counts,
        "jobs": dict(sorted(jobs.items())),
        "ai_gate_states": dict(sorted(gate_states.items())),
        "contains_medical_decisions": False,
        "visual_qc_automatically_passed": False,
        "vlm_jobs_allowed": False,
    }


def verify_artifact_integrity(
    store: SqliteRuntimeStore,
    artifact_store: EligibilityArtifactStore,
) -> int:
    with store._connect() as connection:
        rows = connection.execute(
            """
            SELECT storage_key, content_hash, size_bytes
            FROM eligibility_evidence_artifacts
            ORDER BY project_id, artifact_id
            """
        ).fetchall()
    for row in rows:
        artifact_store.read_bytes(
            str(row["storage_key"]),
            expected_hash=str(row["content_hash"]),
            expected_size_bytes=int(row["size_bytes"]),
        )
    return len(rows)


def backfill_direct_ocr_input_artifacts(
    store: SqliteRuntimeStore,
    artifact_store: EligibilityArtifactStore,
    manifests: Mapping[str, Sequence[Any]],
    *,
    profile_version: str,
) -> int:
    created = 0
    for project_id, project_manifests in manifests.items():
        config = RAW_INTAKE_PROJECTS[project_id]
        for manifest in project_manifests:
            for source in manifest.sources:
                if source.source_type != "image":
                    continue
                with store._connect() as connection:
                    jobs = connection.execute(
                        """
                        SELECT job_id
                        FROM eligibility_evidence_jobs
                        WHERE project_id = ? AND subject_id = ?
                          AND source_id = ? AND source_revision = ?
                          AND job_kind = 'ocr' AND profile_version = ?
                          AND status = 'succeeded' AND input_artifact_id IS NULL
                        """,
                        (
                            project_id,
                            manifest.subject_id,
                            source.source_id,
                            source.source_revision,
                            profile_version,
                        ),
                    ).fetchall()
                if len(jobs) != 1:
                    raise ValueError(
                        "direct image backfill requires one succeeded OCR job"
                    )
                job_id = str(jobs[0]["job_id"])
                artifacts = store.eligibility_evidence_artifacts(
                    project_id,
                    job_id,
                )
                if any(
                    artifact["artifact_kind"] == "ocr_input_image"
                    for artifact in artifacts
                ):
                    continue
                text_artifacts = [
                    artifact
                    for artifact in artifacts
                    if artifact["artifact_kind"] == "ocr_text"
                ]
                if len(text_artifacts) != 1:
                    raise ValueError(
                        "direct image backfill requires one OCR text artifact"
                    )
                text_artifact = text_artifacts[0]
                text_body = artifact_store.read_bytes(
                    text_artifact["storage_key"],
                    expected_hash=text_artifact["content_hash"],
                    expected_size_bytes=text_artifact["size_bytes"],
                )
                text_payload = json.loads(text_body.decode("utf-8"))
                if text_payload.get("schema_version") != "eligibility_ocr_artifact_v1":
                    raise ValueError("direct image OCR artifact schema is invalid")

                source_path = raw_intake_service.resolve_subject_source_path(
                    config,
                    manifest.subject_id,
                    source.source_id,
                    source.source_revision,
                )
                source_bytes = source_path.read_bytes()
                content_hash = hashlib.sha256(source_bytes).hexdigest()
                expected_source_token = "ocrsrc_" + hashlib.sha256(
                    f"ocr-source-v1|{content_hash}".encode("ascii")
                ).hexdigest()[:16]
                if text_payload.get("source_token") != expected_source_token:
                    raise ValueError(
                        "direct image bytes do not match the completed OCR input"
                    )
                suffix = source_path.suffix.lower()
                media_type = {
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".png": "image/png",
                    ".webp": "image/webp",
                    ".tif": "image/tiff",
                    ".tiff": "image/tiff",
                }.get(suffix)
                if media_type is None:
                    raise ValueError("direct image type is not browser-reviewable")
                storage_key = "/".join(
                    (
                        project_id,
                        manifest.subject_id,
                        job_id,
                        f"ocr-input{suffix}",
                    )
                )
                expected_metadata = EligibilityArtifactMetadata(
                    storage_key=storage_key,
                    content_hash=content_hash,
                    size_bytes=len(source_bytes),
                    media_type=media_type,
                )
                try:
                    metadata = artifact_store.write(
                        storage_key,
                        source_bytes,
                        media_type,
                    )
                except ArtifactAlreadyExistsError:
                    artifact_store.read(expected_metadata)
                    metadata = expected_metadata
                artifact_id = "eligartifactinput_" + hashlib.sha256(
                    f"{job_id}|{content_hash}".encode("utf-8")
                ).hexdigest()[:24]
                store.add_eligibility_evidence_artifact(
                    {
                        "project_id": project_id,
                        "subject_id": manifest.subject_id,
                        "job_id": job_id,
                        "artifact_id": artifact_id,
                        "artifact_kind": "ocr_input_image",
                        "storage_key": metadata.storage_key,
                        "content_hash": metadata.content_hash,
                        "size_bytes": metadata.size_bytes,
                        "media_type": metadata.media_type,
                        "source_id": source.source_id,
                        "source_revision": source.source_revision,
                        "extraction_revision": text_artifact[
                            "extraction_revision"
                        ],
                        "locator": {"source_scope": "whole_image"},
                        "quality_state": "needs_visual_qc",
                    }
                )
                created += 1
    return created


def dry_run_summary(manifests: Mapping[str, Sequence[Any]]) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "dry_run",
        "plan": planned_counts(manifests),
        "contains_medical_decisions": False,
        "visual_qc_automatically_passed": False,
        "vlm_jobs_allowed": False,
    }


def bounded_limit(value: int) -> int:
    if value < 0:
        raise ValueError("job limits must be non-negative")
    return value


def parse_stages(value: str) -> tuple[str, ...]:
    stages = tuple(item.strip() for item in value.split(",") if item.strip())
    canonical_order = {"text": 0, "render": 1, "ocr": 2}
    if (
        not stages
        or len(stages) != len(set(stages))
        or any(stage not in canonical_order for stage in stages)
        or list(stages) != sorted(stages, key=canonical_order.__getitem__)
    ):
        raise ValueError(
            "stages must be a unique dependency-ordered subset of text,render,ocr"
        )
    return stages


def validate_runtime_scope(
    store: SqliteRuntimeStore,
    manifests: Mapping[str, Sequence[Any]],
) -> None:
    expected = {
        (project_id, manifest.subject_id)
        for project_id, project_manifests in manifests.items()
        for manifest in project_manifests
    }
    with store._connect() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT project_id, subject_id
            FROM eligibility_source_revisions
            WHERE is_current = 1
            UNION
            SELECT DISTINCT project_id, subject_id
            FROM eligibility_evidence_jobs
            """
        ).fetchall()
    if any((str(row["project_id"]), str(row["subject_id"])) not in expected for row in rows):
        raise ValueError("runtime contains jobs or sources outside the fixed cohort")


def validate_ocr_configuration(
    *,
    profile_version: str,
    base_url: str,
    timeout_seconds: float,
) -> None:
    if profile_version not in ALLOWED_PROFILES:
        raise ValueError("OCR profile is not allowlisted")
    allowed_roots = tuple(
        Path(RAW_INTAKE_PROJECTS[project_id].raw_subject_root)
        .expanduser()
        .resolve(strict=True)
        for project_id in FIXED_COHORT
    )
    OcrGatewaySettings(
        allowed_roots=allowed_roots,
        base_url=base_url,
        model=OCR_PROFILE_MODELS[profile_version],
        timeout_seconds=timeout_seconds,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the fixed two-project six-subject extraction queue."
    )
    parser.add_argument(
        "--mode",
        choices=("dry-run", "seed", "run", "status", "verify", "backfill"),
        default="dry-run",
    )
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--profile-version", choices=sorted(ALLOWED_PROFILES), default="ocr-glm-v1")
    parser.add_argument("--ocr-base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--ocr-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-new-jobs", type=int, default=25)
    parser.add_argument("--max-worker-runs", type=int, default=25)
    parser.add_argument(
        "--stages",
        default="text,render,ocr",
        help="Comma-separated subset of text,render,ocr in execution order.",
    )
    args = parser.parse_args()

    manifests = load_manifests()
    if args.mode == "dry-run":
        print(json.dumps(dry_run_summary(manifests), ensure_ascii=False, sort_keys=True))
        return 0
    if args.runtime_dir is None:
        parser.error("--runtime-dir is required outside dry-run mode")
    runtime_dir = args.runtime_dir.expanduser().resolve()
    artifact_dir = (
        args.artifact_dir.expanduser().resolve()
        if args.artifact_dir is not None
        else runtime_dir / "eligibility_artifacts"
    )
    validate_isolated_paths(runtime_dir, artifact_dir)
    try:
        max_new_jobs = bounded_limit(args.max_new_jobs)
        max_worker_runs = bounded_limit(args.max_worker_runs)
        stages = parse_stages(args.stages) if args.mode == "run" else ()
        if args.mode == "run":
            validate_ocr_configuration(
                profile_version=args.profile_version,
                base_url=args.ocr_base_url,
                timeout_seconds=args.ocr_timeout_seconds,
            )
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    runtime_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    store = SqliteRuntimeStore(runtime_dir / "workbench_runtime.sqlite3")
    validate_runtime_scope(store, manifests)

    if args.mode not in {"status", "verify", "backfill"}:
        register_sources(store, manifests)
        seed_jobs(
            store,
            manifests,
            profile_version=args.profile_version,
            max_new_jobs=max_new_jobs,
        )
        validate_runtime_scope(store, manifests)
    if args.mode == "run":
        workers_by_stage = build_workers(
            store,
            EligibilityArtifactStore(artifact_dir),
            profile_version=args.profile_version,
            base_url=args.ocr_base_url,
            timeout_seconds=args.ocr_timeout_seconds,
        )
        run_workers(
            (workers_by_stage[stage] for stage in stages),
            max_worker_runs=max_worker_runs,
        )
    summary = status_summary(store, manifests)
    if args.mode == "verify":
        summary["artifact_integrity_verified"] = verify_artifact_integrity(
            store,
            EligibilityArtifactStore(artifact_dir),
        )
    if args.mode == "backfill":
        summary["direct_input_artifacts_created"] = (
            backfill_direct_ocr_input_artifacts(
                store,
                EligibilityArtifactStore(artifact_dir),
                manifests,
                profile_version=args.profile_version,
            )
        )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
