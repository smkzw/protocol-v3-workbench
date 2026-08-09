from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile


WORKBENCH_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKBENCH_ROOT))

from services.api.app.runtime_readiness import (  # noqa: E402
    API_CONTRACT_VERSION,
    BACKEND_BUILD_ID,
    RUNTIME_CONTRACT,
    RUNTIME_CONTRACT_SCHEMA,
)


SOURCE_ENTRIES = (
    "services/api/app",
    "frontend/src",
    "frontend/tests/medical_writing_runtime_readiness_qc.mjs",
    "frontend/vite.config.mjs",
    "frontend/package.json",
    "frontend/package-lock.json",
    "packages/contracts/workbench_contracts",
    "scripts/start_stable_backend.zsh",
    "scripts/start_stable_frontend.zsh",
    "scripts/qc/run_medical_writing_openxml_gate.py",
    "tools/openxml_docx_validator",
    "deploy/medical_writing_local",
    "tests/test_runtime_readiness.py",
    "tests/test_medical_writing_openxml_gate.py",
    "tests/test_medical_writing_release_verifier.py",
)

WORD_VALIDATION_SCHEMA = "medical_writing_openxml_gate_v1"
PROHIBITED_COMMERCIAL_WORD_ENGINES = {
    "aspose": "Aspose",
    "devexpress": "DevExpress",
    "gembox": "GemBox",
    "groupdocs": "GroupDocs",
    "spire": "Spire",
    "syncfusion": "Syncfusion",
    "telerik": "Telerik",
}
APPROVED_WORD_TOOLCHAIN = {
    "document_generation": "python-docx plus controlled OOXML",
    "structural_validation": "Microsoft Open XML SDK 3.5.1",
    "structural_validation_license": "MIT",
    "auxiliary_rendering": "LibreOffice render-only; never writes delivery DOCX",
    "final_acceptance": "Microsoft Word desktop",
}


def digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def commercial_word_engine_dependency_report(
    root: Path = WORKBENCH_ROOT,
) -> dict:
    findings: list[dict[str, str]] = []
    backend_root = root / "services" / "api" / "app"
    for path in sorted(backend_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as error:
            raise RuntimeError(
                f"cannot inspect production Python dependency: {path}: {error}"
            ) from error
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                root_name = module.split(".", 1)[0].lower()
                if root_name in PROHIBITED_COMMERCIAL_WORD_ENGINES:
                    findings.append(
                        {
                            "surface": "backend_python_import",
                            "engine": PROHIBITED_COMMERCIAL_WORD_ENGINES[root_name],
                            "dependency": module,
                            "path": str(path.relative_to(root)),
                        }
                    )

    package_path = root / "frontend" / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    for group in (
        "dependencies",
        "devDependencies",
        "optionalDependencies",
        "peerDependencies",
    ):
        for dependency in sorted((package.get(group) or {}).keys()):
            normalized = dependency.lower()
            for marker, engine in PROHIBITED_COMMERCIAL_WORD_ENGINES.items():
                if marker in normalized:
                    findings.append(
                        {
                            "surface": f"frontend_{group}",
                            "engine": engine,
                            "dependency": dependency,
                            "path": str(package_path.relative_to(root)),
                        }
                    )

    return {
        "status": "pass" if not findings else "fail",
        "policy": (
            "Production and release artifacts must not depend on a Word engine "
            "that requires an additional commercial license for unrestricted use."
        ),
        "approved_toolchain": APPROVED_WORD_TOOLCHAIN,
        "findings": findings,
    }


def validate_no_commercial_word_engine_dependency() -> dict:
    report = commercial_word_engine_dependency_report()
    if report["findings"]:
        summary = ", ".join(
            f"{item['engine']} ({item['path']}: {item['dependency']})"
            for item in report["findings"]
        )
        raise RuntimeError(
            f"commercial Word engine dependency is prohibited: {summary}"
        )
    return report


def frontend_build_id() -> str:
    config = RUNTIME_CONTRACT["build_fingerprint"]
    source_root = WORKBENCH_ROOT / config["frontend_source_root"]
    extensions = set(config["frontend_extensions"])
    files = [
        path
        for path in source_root.rglob("*")
        if path.is_file() and path.suffix in extensions
    ]
    files.extend(WORKBENCH_ROOT / item for item in config["frontend_additional_files"])
    digest = sha256()
    for path in sorted(files):
        relative = os.path.relpath(path, source_root).replace(os.sep, "/")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"web-{digest.hexdigest()[:int(config['digest_prefix_length'])]}"


def should_exclude_archive_path(path: Path) -> bool:
    parts = path.parts
    if "__pycache__" in parts or "logs" in parts:
        return True
    if path.name.endswith((".pyc", ".DS_Store")):
        return True
    validator_prefix = ("tools", "openxml_docx_validator")
    if parts[: len(validator_prefix)] == validator_prefix:
        remainder = parts[len(validator_prefix) :]
        if "obj" in remainder or remainder[:2] == ("bin", "Release"):
            return True
    return False


def archive_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if should_exclude_archive_path(Path(info.name)):
        return None
    return info


def release_source_inventory() -> list[dict[str, str | int]]:
    files: dict[str, Path] = {}
    for entry in SOURCE_ENTRIES:
        source = WORKBENCH_ROOT / entry
        candidates = [source] if source.is_file() else source.rglob("*")
        for path in candidates:
            if not path.is_file():
                continue
            relative = path.relative_to(WORKBENCH_ROOT)
            if should_exclude_archive_path(relative):
                continue
            files[relative.as_posix()] = path
    return [
        {
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": digest_file(path),
        }
        for relative, path in sorted(files.items())
    ]


def verification_report() -> dict:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("verify_release.py"))],
        cwd=WORKBENCH_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def validate_word_validation_report(report: dict) -> dict:
    if report.get("schema_version") != WORD_VALIDATION_SCHEMA:
        raise RuntimeError("word validation report schema is not supported")
    if report.get("status") != "pass":
        raise RuntimeError("word validation report is not passing")
    if report.get("failed_count") != 0:
        raise RuntimeError("word validation report contains failed cases")

    validator = report.get("validator")
    if not isinstance(validator, dict):
        raise RuntimeError("word validation report has no validator identity")
    if validator.get("license") != "MIT":
        raise RuntimeError("word validator must use an MIT-licensed build")
    if validator.get("document_format_openxml_version") != "3.5.1":
        raise RuntimeError("word validator version is not the pinned 3.5.1")
    if validator.get("file_format_version") != "Microsoft365":
        raise RuntimeError("word validator profile is not Microsoft365")
    if not validator.get("sha256"):
        raise RuntimeError("word validator binary SHA-256 is missing")

    results = report.get("results")
    if not isinstance(results, list) or not results:
        raise RuntimeError("word validation report has no cases")
    if report.get("case_count") != len(results):
        raise RuntimeError("word validation report case count is inconsistent")
    if any(item.get("passed") is not True for item in results):
        raise RuntimeError("word validation report contains a non-passing case")

    generated = [
        item for item in results if item.get("contract") == "generated_zero_errors"
    ]
    passthrough = [
        item
        for item in results
        if item.get("contract") == "imported_passthrough_identical"
    ]
    imported_edit = [
        item
        for item in results
        if item.get("contract") == "imported_edit_no_new_errors"
    ]
    known_count = len(generated) + len(passthrough) + len(imported_edit)
    if known_count != len(results):
        raise RuntimeError("word validation report contains an unknown contract")
    if not generated or any(item.get("error_count") != 0 for item in generated):
        raise RuntimeError("greenfield DOCX validation must be zero-error")
    if len(passthrough) < 2:
        raise RuntimeError("two real imported passthrough projects are required")
    if any(
        item.get("sha256_identical") is not True
        or item.get("new_error_count") != 0
        for item in passthrough
    ):
        raise RuntimeError("imported passthrough DOCX must be byte-identical")
    if len(imported_edit) < 2 or any(
        item.get("new_error_count") != 0 for item in imported_edit
    ):
        raise RuntimeError("two real imported edited projects are required")

    passthrough_sources = {
        item.get("source", {}).get("sha256") for item in passthrough
    }
    edit_sources = {
        item.get("source", {}).get("sha256") for item in imported_edit
    }
    passthrough_sources.discard(None)
    edit_sources.discard(None)
    real_projects = passthrough_sources & edit_sources
    if len(real_projects) < 2:
        raise RuntimeError(
            "word validation must cover two distinct imported source projects"
        )

    return {
        "status": "pass",
        "schema_version": WORD_VALIDATION_SCHEMA,
        "validator_sha256": validator["sha256"],
        "validator_license": validator["license"],
        "document_format_openxml_version": validator[
            "document_format_openxml_version"
        ],
        "file_format_version": validator["file_format_version"],
        "case_count": len(results),
        "generated_case_count": len(generated),
        "imported_passthrough_case_count": len(passthrough),
        "imported_edit_case_count": len(imported_edit),
        "distinct_imported_project_count": len(real_projects),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-pytest", required=True)
    parser.add_argument("--medical-writing-pytest", required=True)
    parser.add_argument("--browser-report", required=True)
    parser.add_argument("--word-validation-report", required=True)
    args = parser.parse_args()

    browser_report_path = Path(args.browser_report).resolve()
    browser_report = json.loads(browser_report_path.read_text(encoding="utf-8"))
    if browser_report.get("passed") is not True:
        raise RuntimeError("browser report is not passing")
    word_validation_path = Path(args.word_validation_report).resolve()
    word_validation = validate_word_validation_report(
        json.loads(word_validation_path.read_text(encoding="utf-8"))
    )
    word_engine_policy = validate_no_commercial_word_engine_dependency()
    verification = verification_report()
    if verification.get("status") != "pass":
        raise RuntimeError("release verification is not passing")

    frontend_id = frontend_build_id()
    release_id = (
        f"mw-local-20260717-{API_CONTRACT_VERSION.rsplit('-', 1)[-1]}-"
        f"{BACKEND_BUILD_ID.removeprefix('api-')[:8]}-{frontend_id.removeprefix('web-')[:8]}"
    )
    release_dir = WORKBENCH_ROOT / "releases" / "medical_writing" / release_id
    release_dir.mkdir(parents=True, exist_ok=False)
    archive_path = release_dir / f"{release_id}_source.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for entry in SOURCE_ENTRIES:
            source = WORKBENCH_ROOT / entry
            archive.add(source, arcname=entry, recursive=True, filter=archive_filter)
    source_inventory = release_source_inventory()
    source_inventory_path = release_dir / "source_inventory.json"
    source_inventory_path.write_text(
        json.dumps(
            {
                "schema_version": "medical_writing_release_source_inventory_v1",
                "file_count": len(source_inventory),
                "files": source_inventory,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = {
        "release_id": release_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "deployment_scope": "local_private_medical_writing",
        "user_url": "http://127.0.0.1:5174/",
        "backend_url": "http://127.0.0.1:8911/",
        "runtime_contract_schema": RUNTIME_CONTRACT_SCHEMA,
        "api_contract_version": API_CONTRACT_VERSION,
        "backend_build_id": BACKEND_BUILD_ID,
        "frontend_build_id": frontend_id,
        "runtime_schema_version": verification["runtime_schema_version"],
        "required_capability_count": verification["required_capability_count"],
        "independent_ai": verification["independent_ai"],
        "word_engine_policy": word_engine_policy,
        "test_evidence": {
            "full_pytest": args.full_pytest,
            "medical_writing_pytest": args.medical_writing_pytest,
            "browser_report": str(browser_report_path.relative_to(WORKBENCH_ROOT)),
            "browser_passed": True,
            "word_validation_report": str(
                word_validation_path.relative_to(WORKBENCH_ROOT)
            ),
            "word_validation": word_validation,
        },
        "source_archive": archive_path.name,
        "source_archive_sha256": digest_file(archive_path),
        "source_inventory": source_inventory_path.name,
        "source_inventory_sha256": digest_file(source_inventory_path),
        "source_inventory_file_count": len(source_inventory),
        "excluded_from_archive": [
            "runtime databases and audit stores",
            "AI keys and private environment files",
            "real protocol/listing source documents",
            "node_modules and generated frontend dist",
            "temporary screenshots and deployment logs",
            "commercial Word engine trials and binaries",
            "OpenXML validator intermediate obj and duplicate bin/Release outputs",
        ],
        "rollback_boundary": (
            "Stop 5174/8911, verify this archive SHA-256, restore code only, then run the target "
            "release manage.zsh restart and verify. Do not overwrite runtime databases or source documents."
        ),
        "sites_boundary": (
            "No public Site was created. The current FastAPI/SQLite/local-document/private-AI system "
            "remains on the local/intranet privatization track."
        ),
        "verification": verification,
    }
    manifest_path = release_dir / "release_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    checksums_path = release_dir / "SHA256SUMS"
    checksums_path.write_text(
        f"{digest_file(archive_path)}  {archive_path.name}\n"
        f"{digest_file(source_inventory_path)}  {source_inventory_path.name}\n"
        f"{digest_file(manifest_path)}  {manifest_path.name}\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
