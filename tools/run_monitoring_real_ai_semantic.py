#!/usr/bin/env python3
"""Run one isolated real-product monitoring semantic-AI benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.api.app.monitoring_ai_contracts import (  # noqa: E402
    MonitoringAiJobStatus,
    MonitoringAiTaskType,
)
from services.api.app.monitoring_ai_repository import MonitoringAiRepository  # noqa: E402
from services.api.app.monitoring_ai_service import MonitoringAiService  # noqa: E402
from services.api.app.main import (  # noqa: E402
    monitoring_ai_risk_packet_resolver,
    monitoring_ai_source_packet_resolver,
)
from tools.run_monitoring_real_ai_field_mapping import (  # noqa: E402
    _failure_attempt_summaries,
    _write_result,
)


RESULT_SCHEMA_VERSION = "monitoring_real_ai_semantic_benchmark_v1"
_RISK_TASKS = {
    MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS,
    MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
    MonitoringAiTaskType.RISK_QUESTION_ANSWER,
    MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES,
}
_TERMINAL_STATUSES = {
    MonitoringAiJobStatus.COMPLETED,
    MonitoringAiJobStatus.FAILED,
    MonitoringAiJobStatus.BLOCKED,
    MonitoringAiJobStatus.STALE_INPUT,
    MonitoringAiJobStatus.CANCELLED,
}


def _candidate_payload(candidate: Any) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "candidate_type": candidate.candidate_type,
        "title": candidate.title,
        "text": candidate.text,
        "structured_payload": candidate.structured_payload,
        "claims": [
            claim.model_dump(mode="json") for claim in candidate.claims
        ],
        "evidence": [
            {
                "evidence_id": evidence.evidence_id,
                "locator": evidence.locator,
                "quote": evidence.quote,
                "raw_fields": evidence.raw_fields,
            }
            for evidence in candidate.evidence
        ],
    }


def run_semantic_benchmark(
    *,
    project_id: str,
    task_type: MonitoringAiTaskType,
    business_key: str,
    context: dict[str, Any],
    output_dir: Path,
    risk_instance_id: str = "",
    source_ids: Sequence[str] = (),
) -> tuple[int, dict[str, Any]]:
    started = monotonic()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "success": False,
        "run": {
            "project_id": project_id,
            "task_type": task_type.value,
            "business_key": business_key,
            "input_mode": "",
        },
        "job": {"status": "not_submitted"},
        "candidates": [],
        "elapsed_seconds": 0.0,
    }
    exit_code = 1
    try:
        if task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING:
            raise ValueError("field mapping must use the field-mapping benchmark")
        if task_type == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING:
            if risk_instance_id or not source_ids:
                raise ValueError(
                    "protocol clause task requires source_ids and no risk instance"
                )
            packet = monitoring_ai_source_packet_resolver.resolve(
                project_id,
                list(source_ids),
            )
            input_payload = {
                "context": context,
                "source_ids": list(packet.source_ids),
                "evidence_packet": [
                    dict(item) for item in packet.evidence_packet
                ],
            }
            result["run"]["input_mode"] = "source_registry"
            result["run"]["source_count"] = len(packet.source_ids)
        elif task_type in _RISK_TASKS:
            if not risk_instance_id or source_ids:
                raise ValueError(
                    "risk semantic task requires risk_instance_id and no source_ids"
                )
            packet = monitoring_ai_risk_packet_resolver.resolve(
                project_id,
                risk_instance_id,
            )
            input_payload = {
                "context": {
                    "risk": dict(packet.risk_context),
                    "request": context,
                },
                "risk_instance_id": packet.risk_instance_id,
                "evidence_packet": [
                    dict(item) for item in packet.evidence_packet
                ],
            }
            result["run"]["input_mode"] = "current_risk_snapshot"
            result["run"]["risk_instance_id"] = packet.risk_instance_id
        else:
            raise ValueError(f"unsupported semantic task: {task_type.value}")

        with TemporaryDirectory(
            prefix=".monitoring-semantic-benchmark-",
            dir=output_dir,
        ) as temporary_root:
            repository = MonitoringAiRepository(
                Path(temporary_root) / "monitoring_ai.sqlite3"
            )
            revision_sha256 = packet.input_revision.revision_sha256
            service = MonitoringAiService(
                repository,
                current_revision_resolver=lambda _job: revision_sha256,
            )
            job = service.submit_task(
                project_id=project_id,
                task_type=task_type,
                input_revision=packet.input_revision,
                input_payload=input_payload,
                business_key=business_key,
            )
            owner = f"semantic-benchmark-{job.job_id[-12:]}"
            for _ in range(job.max_attempts + 1):
                current = repository.get(project_id, job.job_id)
                if current.status in _TERMINAL_STATUSES:
                    job = current
                    break
                run_result = service.run_next(owner)
                if run_result.job is not None:
                    job = run_result.job
                if not run_result.processed and not run_result.lease_lost:
                    raise RuntimeError("monitoring AI worker made no progress")
            result["job"] = {
                "job_id": job.job_id,
                "status": job.status.value,
                "attempt_count": job.attempt_count,
                "max_attempts": job.max_attempts,
                "profile_id": job.profile_id,
                "provider": job.provider,
                "requested_model": job.requested_model,
                "response_model": job.response_model,
                "prompt_version": job.prompt_version,
                "failure_code": job.failure_code,
            }
            if job.status == MonitoringAiJobStatus.COMPLETED:
                result["candidates"] = [
                    _candidate_payload(candidate)
                    for candidate in repository.candidates(
                        project_id,
                        job.job_id,
                    )
                ]
                result["success"] = True
                exit_code = 0
            else:
                result["error"] = {
                    "type": "MonitoringAiJobFailure",
                    "code": job.failure_code or job.status.value,
                    "message": (
                        job.failure_message
                        or "monitoring AI semantic job did not complete"
                    ),
                }
                result["failure_attempts"] = _failure_attempt_summaries(
                    repository,
                    project_id=project_id,
                    job_id=job.job_id,
                )
    except Exception as exc:
        result["error"] = {
            "type": type(exc).__name__,
            "code": "semantic_benchmark_execution_failed",
            "message": str(exc),
        }
    finally:
        result["elapsed_seconds"] = round(monotonic() - started, 6)
        _write_result(output_dir, result, known_paths=(output_dir,))
    return exit_code, result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--task-type",
        required=True,
        choices=[
            item.value
            for item in MonitoringAiTaskType
            if item != MonitoringAiTaskType.LISTING_FIELD_MAPPING
        ],
    )
    parser.add_argument("--business-key", required=True)
    parser.add_argument("--context-json", default="{}")
    parser.add_argument("--risk-instance-id", default="")
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    context = json.loads(args.context_json)
    if not isinstance(context, dict):
        raise ValueError("context-json must decode to an object")
    exit_code, _ = run_semantic_benchmark(
        project_id=args.project_id,
        task_type=MonitoringAiTaskType(args.task_type),
        business_key=args.business_key,
        context=context,
        output_dir=args.output_dir,
        risk_instance_id=args.risk_instance_id,
        source_ids=args.source_id,
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
