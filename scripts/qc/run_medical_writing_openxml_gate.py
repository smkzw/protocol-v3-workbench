#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from typing import Any


VALIDATOR_SCHEMA = "openxml_docx_validation_v1"
GATE_SCHEMA = "medical_writing_openxml_gate_v1"
VALIDATOR_NAME = "DocumentFormat.OpenXml"
VALIDATOR_VERSION = "3.5.1"
FILE_FORMAT_VERSION = "Microsoft365"


def run_validator(validator: Path, path: Path) -> dict[str, Any]:
    if not validator.is_file():
        raise RuntimeError(f"validator binary does not exist: {validator}")
    if not path.is_file():
        raise RuntimeError(f"DOCX does not exist: {path}")
    process = subprocess.run(
        [str(validator), str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"validator failed for {path}: returncode={process.returncode}; "
            f"stderr={process.stderr.strip()[:500]}"
        )
    payload = json.loads(process.stdout)
    if payload.get("Status") == "validator_error":
        raise RuntimeError(
            f"validator could not read {path}: {payload.get('Message')}"
        )
    expected = {
        "SchemaVersion": VALIDATOR_SCHEMA,
        "Validator": VALIDATOR_NAME,
        "ValidatorVersion": VALIDATOR_VERSION,
        "FileFormatVersion": FILE_FORMAT_VERSION,
    }
    mismatches = {
        key: (value, payload.get(key))
        for key, value in expected.items()
        if payload.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"unexpected validator identity: {mismatches}")
    return payload


def error_signature(error: dict[str, Any]) -> str:
    fields = (
        error.get("Id"),
        error.get("Description"),
        error.get("ErrorType"),
        error.get("Part"),
        error.get("Path"),
        error.get("Node"),
    )
    return json.dumps(fields, ensure_ascii=False, separators=(",", ":"))


def signature_digest(signatures: set[str]) -> str:
    digest = hashlib.sha256()
    for signature in sorted(signatures):
        digest.update(signature.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def parse_named_path(value: str) -> tuple[str, Path]:
    name, separator, path = value.partition("=")
    if not separator or not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError("expected NAME=PATH")
    return name.strip(), Path(path).resolve()


def parse_pair(value: str) -> tuple[str, Path, Path]:
    name, separator, pair = value.partition("=")
    source, pair_separator, candidate = pair.partition(":")
    if (
        not separator
        or not pair_separator
        or not name.strip()
        or not source.strip()
        or not candidate.strip()
    ):
        raise argparse.ArgumentTypeError("expected NAME=SOURCE:CANDIDATE")
    return name.strip(), Path(source).resolve(), Path(candidate).resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validator", required=True, type=Path)
    parser.add_argument("--generated", action="append", default=[], type=parse_named_path)
    parser.add_argument("--passthrough", action="append", default=[], type=parse_pair)
    parser.add_argument("--imported-edit", action="append", default=[], type=parse_pair)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    validator = args.validator.resolve()
    results: list[dict[str, Any]] = []

    for name, path in args.generated:
        validation = run_validator(validator, path)
        passed = validation["ErrorCount"] == 0
        results.append(
            {
                "name": name,
                "contract": "generated_zero_errors",
                "passed": passed,
                "path": str(path),
                "sha256": validation["Sha256"],
                "bytes": validation["Bytes"],
                "error_count": validation["ErrorCount"],
                "errors": validation["Errors"],
            }
        )

    for contract, pairs in (
        ("imported_passthrough_identical", args.passthrough),
        ("imported_edit_no_new_errors", args.imported_edit),
    ):
        for name, source, candidate in pairs:
            source_validation = run_validator(validator, source)
            candidate_validation = run_validator(validator, candidate)
            source_signatures = {
                error_signature(error) for error in source_validation["Errors"]
            }
            candidate_signatures = {
                error_signature(error) for error in candidate_validation["Errors"]
            }
            new_errors = candidate_signatures - source_signatures
            resolved_errors = source_signatures - candidate_signatures
            sha_identical = (
                source_validation["Sha256"] == candidate_validation["Sha256"]
            )
            passed = not new_errors
            if contract == "imported_passthrough_identical":
                passed = passed and sha_identical
            results.append(
                {
                    "name": name,
                    "contract": contract,
                    "passed": passed,
                    "source": {
                        "path": str(source),
                        "sha256": source_validation["Sha256"],
                        "bytes": source_validation["Bytes"],
                        "error_count": source_validation["ErrorCount"],
                        "error_signature_sha256": signature_digest(source_signatures),
                    },
                    "candidate": {
                        "path": str(candidate),
                        "sha256": candidate_validation["Sha256"],
                        "bytes": candidate_validation["Bytes"],
                        "error_count": candidate_validation["ErrorCount"],
                        "error_signature_sha256": signature_digest(
                            candidate_signatures
                        ),
                    },
                    "sha256_identical": sha_identical,
                    "new_error_count": len(new_errors),
                    "resolved_error_count": len(resolved_errors),
                    "new_errors": [json.loads(item) for item in sorted(new_errors)],
                }
            )

    report = {
        "schema_version": GATE_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "host": {
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "validator": {
            "path": str(validator),
            "sha256": hashlib.sha256(validator.read_bytes()).hexdigest(),
            "license": "MIT",
            "document_format_openxml_version": VALIDATOR_VERSION,
            "file_format_version": FILE_FORMAT_VERSION,
        },
        "status": "pass" if results and all(item["passed"] for item in results) else "fail",
        "case_count": len(results),
        "passed_count": sum(bool(item["passed"]) for item in results),
        "failed_count": sum(not bool(item["passed"]) for item in results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "case_count": report["case_count"],
                "passed_count": report["passed_count"],
                "failed_count": report["failed_count"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
