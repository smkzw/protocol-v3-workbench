#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.eligibility import RAW_INTAKE_PROJECTS
from services.api.app.eligibility_artifact_store import EligibilityArtifactStore
from services.api.app.eligibility_evidence_tasks import EligibilityEvidenceTaskService
from services.api.app.eligibility_evidence_worker import EligibilityEvidenceWorker
from services.api.app.eligibility_raw_intake import EligibilityRawProjectIntakeService
from services.api.app.ocr_gateway import (
    LocalOcrGateway,
    OCR_PROFILE_MODELS,
    OcrGatewaySettings,
    validate_ocr_profile_model,
)
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore


def canonical_configs():
    return {
        config.project_id: config
        for config in RAW_INTAKE_PROJECTS.values()
    }


def build_worker() -> EligibilityEvidenceWorker:
    runtime_dir = Path(
        os.environ.get("WORKBENCH_RUNTIME_DIR", ROOT / "runtime")
    ).expanduser().resolve()
    artifact_root = Path(
        os.environ.get(
            "WORKBENCH_ELIGIBILITY_ARTIFACT_DIR",
            runtime_dir / "eligibility_artifacts",
        )
    ).expanduser()
    profile_version = os.environ.get(
        "WORKBENCH_EVIDENCE_PROFILE_VERSION",
        "ocr-glm-v1",
    )
    model = None
    if profile_version in OCR_PROFILE_MODELS:
        model = os.environ.get("WORKBENCH_OCR_MODEL", "GLM-OCR-bf16")
        validate_ocr_profile_model(profile_version, model)
    child_profiles = ()
    if profile_version == "pdf-render-200dpi-v1":
        configured = os.environ.get("WORKBENCH_PDF_OCR_CHILD_PROFILES", "")
        child_profiles = tuple(
            item.strip() for item in configured.split(",") if item.strip()
        )
        if not child_profiles:
            raise ValueError(
                "WORKBENCH_PDF_OCR_CHILD_PROFILES is required for PDF render workers"
            )
    configs = canonical_configs()
    intake = EligibilityRawProjectIntakeService()
    allowed_roots = tuple(
        Path(config.raw_subject_root).expanduser().resolve(strict=True)
        for config in configs.values()
    )
    gateway = None
    if profile_version in OCR_PROFILE_MODELS:
        gateway = LocalOcrGateway(
            OcrGatewaySettings(
                allowed_roots=allowed_roots,
                base_url=os.environ.get(
                    "WORKBENCH_OCR_BASE_URL", "http://127.0.0.1:8000/v1"
                ),
                model=model,
                timeout_seconds=float(
                    os.environ.get("WORKBENCH_OCR_TIMEOUT_SECONDS", "120")
                ),
                api_key=os.environ.get("WORKBENCH_OCR_API_KEY", ""),
            )
        )
    def resolve(job):
        config = configs.get(str(job["project_id"]))
        if config is None:
            raise KeyError("eligibility evidence project is not configured")
        return intake.resolve_subject_source_path(
            config,
            str(job["subject_id"]),
            str(job["source_id"]),
            str(job["source_revision"]),
        )

    return EligibilityEvidenceWorker(
        store=SqliteRuntimeStore(runtime_dir / "workbench_runtime.sqlite3"),
        artifact_store=EligibilityArtifactStore(artifact_root),
        source_resolver=resolve,
        ocr_gateway=gateway,
        profile_version=profile_version,
        ocr_child_profiles=child_profiles,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the local durable eligibility evidence worker."
    )
    parser.add_argument("--worker-id", default=f"local-worker-{os.getpid()}")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    worker = build_worker()
    while True:
        result = worker.run_once(args.worker_id)
        if result is not None:
            print(
                json.dumps(
                    EligibilityEvidenceTaskService.public_job(result),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                flush=True,
            )
        if args.once:
            return 0
        if result is None:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
