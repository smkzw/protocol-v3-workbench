#!/usr/bin/env python3
"""Check or advance a field-mapping run through the public monitoring API."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Optional
from urllib import error, parse, request


RequestJson = Callable[[str, str, Optional[dict[str, Any]], float], Any]
TERMINAL_ACTIONS = frozenset({"check", "adopt", "confirm"})


class CutoverError(RuntimeError):
    """A controlled cutover gate rejected the requested action."""


@dataclass(frozen=True)
class CutoverOptions:
    base_url: str
    project_id: str
    batch_id: str
    action: str
    actor: str
    reason: str
    expected_project_version: int | None
    timeout_seconds: float


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_request(
    method: str,
    url: str,
    body: dict[str, Any] | None,
    timeout_seconds: float,
) -> Any:
    payload = None
    headers = {"Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    http_request = request.Request(
        url,
        data=payload,
        headers=headers,
        method=method,
    )
    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            raw = response.read()
    except error.HTTPError as exc:
        raw = exc.read()
        detail: Any
        try:
            detail = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = raw.decode("utf-8", errors="replace")
        raise CutoverError(
            f"{method} {url} returned HTTP {exc.code}: {detail}"
        ) from exc
    except error.URLError as exc:
        raise CutoverError(f"{method} {url} failed: {exc.reason}") from exc
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CutoverError(f"{method} {url} returned non-JSON content") from exc


def _api_path(options: CutoverOptions, suffix: str) -> str:
    project_id = parse.quote(options.project_id, safe="")
    return (
        f"{options.base_url.rstrip('/')}/api/projects/{project_id}/modules/"
        f"medical-monitoring/ai/{suffix.lstrip('/')}"
    )


def _status_summary(status: dict[str, Any]) -> dict[str, Any]:
    details = list(status.get("job_details") or [])
    status_counts: dict[str, int] = {}
    for item in details:
        job = dict(item.get("job") or {})
        job_status = str(job.get("status") or "unknown")
        status_counts[job_status] = status_counts.get(job_status, 0) + 1

    job_count = int(status.get("job_count") or 0)
    all_completed = (
        job_count > 0
        and len(details) == job_count
        and status_counts == {"completed": job_count}
    )
    candidate_count = 0
    candidate_count_violations: list[str] = []
    if all_completed:
        for item in details:
            job = dict(item.get("job") or {})
            candidates = list(item.get("candidates") or [])
            candidate_count += len(candidates)
            if len(candidates) != 1:
                candidate_count_violations.append(
                    str(job.get("job_id") or "")
                )
    return {
        "project_id": status.get("project_id"),
        "batch_id": status.get("batch_id"),
        "profile_sha256": status.get("profile_sha256"),
        "input_sha256": status.get("input_sha256"),
        "field_count": int(status.get("field_count") or 0),
        "job_count": job_count,
        "status_counts": status_counts,
        "candidate_count": candidate_count,
        "candidate_count_violation_job_ids": candidate_count_violations,
        "all_completed": all_completed,
        "draft_id": (status.get("draft") or {}).get("draft_id"),
        "draft_status": (status.get("draft") or {}).get("status"),
        "active_mapping_revision": (
            status.get("active_mapping") or {}
        ).get("mapping_revision"),
        "active_project_version": int(
            (status.get("active_mapping") or {}).get("project_version") or 0
        ),
    }


def _idempotency_key(
    *,
    project_id: str,
    batch_id: str,
    profile_sha256: str,
    draft_version: int,
) -> str:
    raw = (
        f"{project_id}|{batch_id}|{profile_sha256}|{draft_version}"
    ).encode("utf-8")
    return f"monitoring-mapping-cutover-{hashlib.sha256(raw).hexdigest()[:32]}"


def run_cutover(
    options: CutoverOptions,
    *,
    requester: RequestJson = _json_request,
) -> dict[str, Any]:
    if options.action not in TERMINAL_ACTIONS:
        raise CutoverError(f"unsupported action: {options.action}")
    if options.action != "check" and len(options.reason.strip()) < 10:
        raise CutoverError(
            "adopt/confirm requires a specific reason of at least 10 characters"
        )

    status_url = _api_path(options, "field-mapping-status")
    status_url = (
        f"{status_url}?{parse.urlencode({'batch_id': options.batch_id})}"
    )
    status = requester("GET", status_url, None, options.timeout_seconds)
    if not isinstance(status, dict):
        raise CutoverError("field-mapping-status returned an invalid payload")
    summary = _status_summary(status)
    evidence: dict[str, Any] = {
        "schema_version": "monitoring_mapping_api_cutover_v1",
        "checked_at": _utc_now(),
        "action": options.action,
        "base_url": options.base_url.rstrip("/"),
        "project_id": options.project_id,
        "batch_id": options.batch_id,
        "status_summary": summary,
        "requests": [],
        "result": "checked",
    }
    if options.action == "check":
        return evidence
    if not summary["all_completed"]:
        raise CutoverError(
            f"mapping run is incomplete: {summary['status_counts']}"
        )
    if summary["candidate_count_violation_job_ids"]:
        raise CutoverError(
            "completed mapping jobs must each expose exactly one candidate"
        )
    profile_sha256 = str(summary["profile_sha256"] or "").strip().lower()
    if len(profile_sha256) != 64:
        raise CutoverError("mapping status is missing a valid profile SHA-256")

    adopt_body = {
        "batch_id": options.batch_id,
        "full_profile_sha256": profile_sha256,
        "actor": options.actor,
        "reason": options.reason.strip(),
    }
    adopt_url = _api_path(options, "field-mapping-runs/adopt")
    evidence["requests"].append(
        {"method": "POST", "path": "/field-mapping-runs/adopt"}
    )
    draft = requester(
        "POST",
        adopt_url,
        adopt_body,
        options.timeout_seconds,
    )
    if not isinstance(draft, dict):
        raise CutoverError("field-mapping-runs/adopt returned an invalid payload")
    semantic_quality = dict(draft.get("semantic_quality") or {})
    disposition = str(
        semantic_quality.get("activation_disposition") or ""
    )
    evidence["adopted_draft"] = {
        "draft_id": draft.get("draft_id"),
        "version": draft.get("version"),
        "status": draft.get("status"),
        "semantic_quality": semantic_quality,
    }
    evidence["result"] = "adopted"
    if disposition == "reject" or semantic_quality.get("status") == "blocked":
        evidence["result"] = "blocked_by_semantic_quality"
        return evidence
    if options.action == "adopt":
        return evidence

    draft_id = str(draft.get("draft_id") or "").strip()
    draft_version = int(draft.get("version") or 0)
    if not draft_id or draft_version < 1:
        raise CutoverError("adopted draft is missing its identity or version")
    expected_project_version = options.expected_project_version
    if expected_project_version is None:
        expected_project_version = summary["active_project_version"]
    confirm_body = {
        "expected_version": draft_version,
        "confirmed_by": options.actor,
        "confirmation_reason": options.reason.strip(),
        "idempotency_key": _idempotency_key(
            project_id=options.project_id,
            batch_id=options.batch_id,
            profile_sha256=profile_sha256,
            draft_version=draft_version,
        ),
        "expected_project_version": expected_project_version,
    }
    confirm_url = _api_path(
        options,
        f"mapping-drafts/{parse.quote(draft_id, safe='')}/confirm",
    )
    evidence["requests"].append(
        {
            "method": "POST",
            "path": f"/mapping-drafts/{draft_id}/confirm",
            "expected_version": draft_version,
            "expected_project_version": expected_project_version,
        }
    )
    revision = requester(
        "POST",
        confirm_url,
        confirm_body,
        options.timeout_seconds,
    )
    if not isinstance(revision, dict):
        raise CutoverError("mapping draft confirmation returned invalid payload")
    evidence["confirmed_revision"] = revision
    evidence["result"] = "confirmed_and_activated"
    return evidence


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8911")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument(
        "--action",
        choices=sorted(TERMINAL_ACTIONS),
        default="check",
        help="Default check is read-only; adopt/confirm call the public API.",
    )
    parser.add_argument("--actor", default="medical_manager")
    parser.add_argument("--reason", default="")
    parser.add_argument("--expected-project-version", type=int)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--evidence-path", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    options = CutoverOptions(
        base_url=args.base_url,
        project_id=args.project_id,
        batch_id=args.batch_id,
        action=args.action,
        actor=args.actor,
        reason=args.reason,
        expected_project_version=args.expected_project_version,
        timeout_seconds=args.timeout_seconds,
    )
    try:
        evidence = run_cutover(options)
    except CutoverError as exc:
        print(json.dumps({"result": "error", "message": str(exc)}, ensure_ascii=False))
        return 2
    if args.evidence_path is not None:
        _write_evidence(args.evidence_path, evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    if evidence["result"] == "blocked_by_semantic_quality":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
