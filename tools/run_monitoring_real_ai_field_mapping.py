#!/usr/bin/env python3
"""Run one isolated real-product monitoring field-mapping benchmark."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Any, Callable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.api.app.ai_gateway import AiProvider  # noqa: E402
from services.api.app.listing_file_parser import (  # noqa: E402
    LISTING_PARSER_VERSION,
    parse_listing_file,
)
from services.api.app.monitoring_ai_contracts import (  # noqa: E402
    MonitoringAiInputRevision,
    MonitoringAiJobStatus,
    MonitoringAiSourceBinding,
)
from services.api.app.monitoring_ai_field_profiler import (  # noqa: E402
    FIELD_PROFILE_SCHEMA_VERSION,
    MonitoringAIFieldProfiler,
)
from services.api.app.monitoring_ai_repository import MonitoringAiRepository  # noqa: E402
from services.api.app.monitoring_ai_service import (  # noqa: E402
    MonitoringAiRuntimeBinding,
    MonitoringAiService,
)
from services.api.app.monitoring_batch_diff import normalize_listing_sheets  # noqa: E402
from services.api.app.monitoring_batch_repository import (  # noqa: E402
    MonitoringBatchRepository,
)


RESULT_SCHEMA_VERSION = "monitoring_real_ai_field_mapping_benchmark_v1"
BENCHMARK_MAPPING_REVISION = "benchmark-source-normalization-v1"
MAX_FAILURE_RESPONSE_CHARACTERS = 32_000
_TERMINAL_JOB_STATUSES = {
    MonitoringAiJobStatus.COMPLETED,
    MonitoringAiJobStatus.FAILED,
    MonitoringAiJobStatus.BLOCKED,
    MonitoringAiJobStatus.STALE_INPUT,
    MonitoringAiJobStatus.CANCELLED,
}
_ABSOLUTE_LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])/(?:Users|private|tmp|var|Volumes|home|opt)"
    r"(?:/[^\s\"'<>|,;:]*)*"
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|"
    r"password|authorization)\b\s*(?:=|:)\s*([^\s,;]+)"
)
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


@dataclass(frozen=True)
class BenchmarkConfig:
    project_id: str
    listing_path: Path
    domain: str
    chunk_index: int
    chunk_size: int
    output_dir: Path


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _redact_text(value: str, known_paths: Sequence[Path] = ()) -> str:
    redacted = str(value)
    for path in sorted(
        {str(Path(item).expanduser().resolve()) for item in known_paths},
        key=len,
        reverse=True,
    ):
        redacted = redacted.replace(path, "<local-path>")
    redacted = _ABSOLUTE_LOCAL_PATH_RE.sub("<local-path>", redacted)
    redacted = _BEARER_TOKEN_RE.sub("Bearer <redacted>", redacted)
    redacted = _SENSITIVE_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}=<redacted>",
        redacted,
    )
    return redacted


def _redact_value(value: Any, known_paths: Sequence[Path] = ()) -> Any:
    if isinstance(value, str):
        return _redact_text(value, known_paths)
    if isinstance(value, Mapping):
        return {
            str(key): _redact_value(item, known_paths)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, known_paths) for item in value]
    return value


def _write_result(
    output_dir: Path,
    payload: Mapping[str, Any],
    *,
    known_paths: Sequence[Path] = (),
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "RESULT.json"
    temporary_path = output_dir / ".RESULT.json.tmp"
    redacted = _redact_value(dict(payload), known_paths)
    serialized = json.dumps(
        redacted,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    if _ABSOLUTE_LOCAL_PATH_RE.search(serialized):
        raise RuntimeError("benchmark result still contains a local absolute path")
    with temporary_path.open("w", encoding="utf-8") as stream:
        stream.write(serialized)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary_path, result_path)
    return result_path


def _validate_config(config: BenchmarkConfig) -> tuple[str, Path, str]:
    project_id = str(config.project_id).strip()
    if not project_id:
        raise ValueError("project-id is required")
    listing_path = Path(config.listing_path).expanduser().resolve()
    if not listing_path.is_file():
        raise FileNotFoundError(f"listing file is unavailable: {listing_path}")
    domain = str(config.domain).strip().upper()
    if not domain:
        raise ValueError("domain is required")
    if not isinstance(config.chunk_size, int) or not 1 <= config.chunk_size <= 12:
        raise ValueError("chunk-size must be an integer from 1 to 12")
    if not isinstance(config.chunk_index, int) or config.chunk_index < 1:
        raise ValueError("chunk-index must be a positive 1-based integer")
    return project_id, listing_path, domain


def _freeze_full_listing_batch(
    repository: MonitoringBatchRepository,
    *,
    project_id: str,
    listing_path: Path,
    source_sha256: str,
) -> tuple[str, int, tuple[str, ...]]:
    content = listing_path.read_bytes()
    sheets = parse_listing_file(listing_path.name, content)
    normalized_rows = normalize_listing_sheets(sheets)
    if not normalized_rows:
        raise ValueError("listing contains no normalizable data rows")
    domains = tuple(
        sorted(
            {
                str(row["domain"]).strip().upper()
                for row in normalized_rows
                if str(row["domain"]).strip()
            }
        )
    )
    if not domains:
        raise ValueError("listing contains no normalized domains")

    source = repository.register_source(
        project_id=project_id,
        source_entry_id=f"benchmark-listing:{source_sha256[:24]}",
        validation_id=f"benchmark-content-check:{source_sha256[:24]}",
        validation_revision=1,
        validator_version="benchmark-basic-content-check-v1",
        validation_use_status="allowed",
        role="edc_data_listing",
        source_class="raw_full_snapshot",
        file_path=listing_path,
        file_name=listing_path.name,
        parser_version=LISTING_PARSER_VERSION,
        technical_status="passed",
    )
    batch = repository.create_batch(
        project_id=project_id,
        idempotency_key=f"benchmark:{source_sha256}:create",
        expected_domains=domains,
    ).batch
    batch = repository.attach_source(
        batch_id=batch.batch_id,
        source_id=source.source_id,
        expected_version=batch.version,
        idempotency_key=f"benchmark:{source_sha256}:attach",
    ).batch
    batch = repository.replace_rows(
        batch_id=batch.batch_id,
        rows=normalized_rows,
        expected_version=batch.version,
        idempotency_key=f"benchmark:{source_sha256}:rows",
    ).batch
    batch = repository.transition_batch(
        batch_id=batch.batch_id,
        target_state="parsed",
        expected_version=batch.version,
        idempotency_key=f"benchmark:{source_sha256}:parsed",
    ).batch
    batch = repository.record_validation_evidence(
        batch_id=batch.batch_id,
        mapping_revision=BENCHMARK_MAPPING_REVISION,
        mapping={
            "schema_version": "benchmark_source_normalization_v1",
            "parser_version": LISTING_PARSER_VERSION,
            "scope": "all_parsed_listing_rows",
        },
        expected_domains=domains,
        full_snapshot_proof={
            "confirmed": True,
            "basis": "all parser-produced listing sheets and rows were normalized",
            "confirmed_by": "benchmark_runner",
            "source_content_sha256": source_sha256,
        },
        expected_version=batch.version,
        idempotency_key=f"benchmark:{source_sha256}:validation-evidence",
    ).batch
    for state in ("validated", "confirmed", "frozen"):
        batch = repository.transition_batch(
            batch_id=batch.batch_id,
            target_state=state,
            expected_version=batch.version,
            idempotency_key=f"benchmark:{source_sha256}:{state}",
        ).batch
    return batch.batch_id, len(normalized_rows), domains


def _select_profile_chunk(
    full_profile: Mapping[str, Any],
    *,
    domain: str,
    chunk_index: int,
    chunk_size: int,
) -> dict[str, Any]:
    domain_fields = sorted(
        (
            deepcopy(field)
            for field in full_profile["fields"]
            if str(field.get("domain", "")).strip().upper() == domain
        ),
        key=lambda field: (
            str(field["field"]).strip().casefold(),
            str(field["field"]).strip(),
        ),
    )
    if not domain_fields:
        available = sorted(
            {
                str(field.get("domain", "")).strip()
                for field in full_profile["fields"]
                if str(field.get("domain", "")).strip()
            }
        )
        raise ValueError(
            f"domain {domain!r} has no profiled fields; available domains: "
            f"{', '.join(available)}"
        )
    chunk_total = (len(domain_fields) + chunk_size - 1) // chunk_size
    if chunk_index > chunk_total:
        raise ValueError(
            f"chunk-index {chunk_index} exceeds {domain} chunk total {chunk_total}"
        )
    start = (chunk_index - 1) * chunk_size
    fields = domain_fields[start : start + chunk_size]
    field_names = {str(field["field"]).strip() for field in fields}
    relationships = [
        deepcopy(relationship)
        for relationship in full_profile.get("relationships", [])
        if (
            str(relationship.get("domain", "")).strip().upper() == domain
            and {
                str(relationship.get("left_field", "")).strip(),
                str(relationship.get("right_field", "")).strip(),
            }.intersection(field_names)
        )
    ]
    chunk = {
        key: deepcopy(value)
        for key, value in full_profile.items()
        if key not in {"fields", "relationships"}
    }
    chunk.update(
        {
            "scope": "complete_profile_chunk",
            "full_profile_sha256": str(full_profile["profile_sha256"]),
            "full_input_sha256": str(full_profile["input_sha256"]),
            "full_field_count": len(full_profile["fields"]),
            "domain": domain,
            "domain_field_count": len(domain_fields),
            "domain_field_names": [
                str(field["field"]).strip()
                for field in domain_fields
            ],
            "chunk_index": chunk_index,
            "chunk_total": chunk_total,
            "chunk_size_limit": chunk_size,
            "fields": fields,
            "relationships": relationships,
        }
    )
    return chunk


def _evidence_summary(evidence: Any) -> dict[str, Any]:
    raw = dict(evidence.raw_fields)
    safe_raw_keys = (
        "domain",
        "field",
        "inferred_type",
        "total_rows",
        "non_empty_count",
        "null_rate",
        "unique_value_count",
        "values_redacted",
        "paired_relationships",
        "profile_sha256",
        "payload_policy",
    )
    return {
        "evidence_id": evidence.evidence_id,
        "locator": evidence.locator,
        "profile": {key: raw[key] for key in safe_raw_keys if key in raw},
    }


def _candidate_summaries(candidates: Sequence[Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for candidate in candidates:
        evidence_by_id = {
            evidence.evidence_id: _evidence_summary(evidence)
            for evidence in candidate.evidence
        }
        mappings = []
        for mapping in candidate.structured_payload.get("field_mappings", []):
            evidence_ids = list(mapping.get("evidence_ids", []))
            mappings.append(
                {
                    "domain": mapping.get("domain", ""),
                    "source_field": mapping.get("source_field", ""),
                    "recommended_role": mapping.get("recommended_role", ""),
                    "field_kind": mapping.get("field_kind", ""),
                    "confidence": mapping.get("confidence"),
                    "uncertainty": mapping.get("uncertainty", ""),
                    "user_action": mapping.get("user_action", ""),
                    "related_fields": list(mapping.get("related_fields", [])),
                    "standards_reference": mapping.get("standards_reference"),
                    "derivation_lineage": mapping.get("derivation_lineage"),
                    "evidence_ids": evidence_ids,
                    "evidence_summary": [
                        evidence_by_id[evidence_id]
                        for evidence_id in evidence_ids
                        if evidence_id in evidence_by_id
                    ],
                }
            )
        summaries.append(
            {
                "candidate_id": candidate.candidate_id,
                "candidate_type": candidate.candidate_type,
                "title": candidate.title,
                "field_mappings": mappings,
                "evidence_count": len(candidate.evidence),
            }
        )
    return summaries


def _failure_attempt_summaries(
    repository: MonitoringAiRepository,
    *,
    project_id: str,
    job_id: str,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for attempt in repository.attempts(project_id, job_id):
        response = attempt.get("response")
        response_text = (
            json.dumps(response, ensure_ascii=False, sort_keys=True)
            if response is not None
            else ""
        )
        summaries.append(
            {
                "attempt_number": attempt["attempt_number"],
                "outcome": attempt["outcome"],
                "failure_code": attempt["failure_code"],
                "failure_message": attempt["failure_message"],
                "response_model": attempt["response_model"],
                "response_sha256": attempt["response_sha256"],
                "response_excerpt": response_text[
                    :MAX_FAILURE_RESPONSE_CHARACTERS
                ],
                "response_truncated": (
                    len(response_text) > MAX_FAILURE_RESPONSE_CHARACTERS
                ),
            }
        )
    return summaries


def run_benchmark(
    config: BenchmarkConfig,
    *,
    runtime_resolver: Callable[[], MonitoringAiRuntimeBinding] | None = None,
    provider_factory: Callable[[dict[str, str]], AiProvider] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Execute one isolated benchmark and always write RESULT.json."""

    started = monotonic()
    output_dir = Path(config.output_dir).expanduser().resolve()
    known_paths: list[Path] = [output_dir]
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "success": False,
        "run": {
            "project_id": str(config.project_id).strip(),
            "domain": str(config.domain).strip().upper(),
            "chunk_index": config.chunk_index,
            "chunk_size": config.chunk_size,
        },
        "source": {
            "file_name": Path(config.listing_path).name,
            "content_sha256": "",
        },
        "profile": {
            "schema_version": FIELD_PROFILE_SCHEMA_VERSION,
            "row_count": 0,
            "domain_count": 0,
            "field_count": 0,
        },
        "target_chunk": {},
        "job": {"status": "not_submitted"},
        "candidates": [],
        "elapsed_seconds": 0.0,
    }
    exit_code = 1
    temporary_root_path: Path | None = None
    try:
        project_id, listing_path, domain = _validate_config(config)
        known_paths.append(listing_path)
        source_sha256 = _sha256_file(listing_path)
        result["source"] = {
            "file_name": listing_path.name,
            "content_sha256": source_sha256,
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(
            prefix=".monitoring-field-mapping-benchmark-",
            dir=output_dir,
        ) as temporary_root:
            temporary_root_path = Path(temporary_root).resolve()
            known_paths.append(temporary_root_path)
            batch_repository = MonitoringBatchRepository(
                temporary_root_path / "monitoring_batches.sqlite3",
                temporary_root_path / "batch_objects",
            )
            batch_id, normalized_row_count, domains = _freeze_full_listing_batch(
                batch_repository,
                project_id=project_id,
                listing_path=listing_path,
                source_sha256=source_sha256,
            )
            snapshot = MonitoringAIFieldProfiler(
                batch_repository
            ).profile_frozen_batch(batch_id)
            full_profile = snapshot.to_ai_payload()
            chunk_profile = _select_profile_chunk(
                full_profile,
                domain=domain,
                chunk_index=config.chunk_index,
                chunk_size=config.chunk_size,
            )
            result["profile"] = {
                "schema_version": snapshot.schema_version,
                "profile_sha256": snapshot.profile_sha256,
                "input_sha256": snapshot.input_sha256,
                "row_count": normalized_row_count,
                "domain_count": len(domains),
                "field_count": len(snapshot.fields),
                "relationship_count": len(snapshot.relationships),
            }
            result["target_chunk"] = {
                "domain": domain,
                "domain_field_count": chunk_profile["domain_field_count"],
                "chunk_index": chunk_profile["chunk_index"],
                "chunk_total": chunk_profile["chunk_total"],
                "chunk_size_limit": chunk_profile["chunk_size_limit"],
                "field_count": len(chunk_profile["fields"]),
                "field_names": [
                    str(field["field"]) for field in chunk_profile["fields"]
                ],
                "relationship_count": len(chunk_profile["relationships"]),
            }

            frozen_batch = batch_repository.load_diff_ready_batch(batch_id)
            input_revision = MonitoringAiInputRevision(
                project_id=project_id,
                batch_revision=f"{batch_id}:v{frozen_batch.version}",
                mapping_revision=frozen_batch.mapping_revision or "",
                sources=tuple(
                    MonitoringAiSourceBinding(
                        source_entry_id=source_entry_id,
                        source_content_sha256=content_sha256,
                    )
                    for source_entry_id, content_sha256 in (
                        frozen_batch.source_bindings
                    )
                ),
            )
            ai_repository = MonitoringAiRepository(
                temporary_root_path / "monitoring_ai.sqlite3"
            )
            service_kwargs: dict[str, Any] = {}
            if runtime_resolver is not None:
                service_kwargs["runtime_resolver"] = runtime_resolver
            if provider_factory is not None:
                service_kwargs["provider_factory"] = provider_factory
            service = MonitoringAiService(ai_repository, **service_kwargs)
            business_key = (
                f"benchmark:{source_sha256}:{domain}:"
                f"{config.chunk_index:04d}-of-{chunk_profile['chunk_total']:04d}"
            )
            job = service.submit_listing_field_mapping(
                project_id=project_id,
                input_revision=input_revision,
                field_profile=chunk_profile,
                business_key=business_key,
            )

            owner = f"benchmark-{source_sha256[:16]}"
            for _ in range(job.max_attempts + 1):
                current = ai_repository.get(project_id, job.job_id)
                if current.status in _TERMINAL_JOB_STATUSES:
                    job = current
                    break
                run_result = service.run_next(owner)
                if run_result.job is not None:
                    job = run_result.job
                if not run_result.processed and not run_result.lease_lost:
                    raise RuntimeError("monitoring AI worker made no progress")
            else:
                job = ai_repository.get(project_id, job.job_id)

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
                candidates = ai_repository.candidates(project_id, job.job_id)
                result["candidates"] = _candidate_summaries(candidates)
                result["success"] = True
                exit_code = 0
            else:
                result["error"] = {
                    "type": "MonitoringAiJobFailure",
                    "code": job.failure_code or job.status.value,
                    "message": job.failure_message or "monitoring AI job did not complete",
                }
                result["failure_attempts"] = _failure_attempt_summaries(
                    ai_repository,
                    project_id=project_id,
                    job_id=job.job_id,
                )
    except Exception as exc:
        result["error"] = {
            "type": type(exc).__name__,
            "code": "benchmark_execution_failed",
            "message": str(exc),
        }
    finally:
        result["elapsed_seconds"] = round(monotonic() - started, 6)
        if temporary_root_path is not None:
            known_paths.append(temporary_root_path)
        _write_result(output_dir, result, known_paths=known_paths)
    return exit_code, _redact_value(result, known_paths)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run an isolated real-provider medical-monitoring field-mapping "
            "benchmark from an original listing."
        )
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--listing", required=True, type=Path)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--chunk-index", required=True, type=int)
    parser.add_argument("--chunk-size", required=True, type=int)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    exit_code, _ = run_benchmark(
        BenchmarkConfig(
            project_id=args.project_id,
            listing_path=args.listing,
            domain=args.domain,
            chunk_index=args.chunk_index,
            chunk_size=args.chunk_size,
            output_dir=args.output_dir,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
