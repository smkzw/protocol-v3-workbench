from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile
from typing import Mapping, Sequence

from build_source_baseline import BaselineError, build_manifest, validate_relative_path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def safe_extract_tar(tar_path: Path, destination: Path) -> None:
    destination = destination.absolute()
    if destination.exists():
        raise BaselineError("extraction target already exists: %s" % destination)
    destination.mkdir(parents=True, exist_ok=False)
    destination_root = destination.resolve(strict=True)
    try:
        with tarfile.open(str(tar_path), "r") as archive:
            for member in archive.getmembers():
                relative = validate_relative_path(member.name)
                target = (destination_root / relative).resolve(strict=False)
                if not _within(target, destination_root):
                    raise BaselineError("tar member escapes destination: %s" % member.name)
                if member.islnk():
                    raise BaselineError("hard links are not allowed in source tar: %s" % member.name)
                if member.issym():
                    if os.path.isabs(member.linkname):
                        raise BaselineError("absolute symlink in source tar: %s" % member.name)
                    link_target = (target.parent / member.linkname).resolve(strict=False)
                    if not _within(link_target, destination_root):
                        raise BaselineError("symlink escapes destination: %s" % member.name)
                elif not member.isfile():
                    raise BaselineError("unsupported tar member type: %s" % member.name)
            archive.extractall(str(destination_root))
    except Exception:
        shutil.rmtree(str(destination), ignore_errors=True)
        raise


def verify_manifest_against_root(
    manifest: Mapping[str, object],
    root: Path,
    strict_metadata: bool = False,
) -> Mapping[str, object]:
    root = root.resolve(strict=True)
    expected_entries = {str(entry["path"]): dict(entry) for entry in manifest["entries"]}
    if len(expected_entries) != len(manifest["entries"]):
        raise BaselineError("manifest contains duplicate paths")

    for relative, expected in expected_entries.items():
        validate_relative_path(relative)
        path = root / relative
        if not path.exists() and not path.is_symlink():
            raise BaselineError("manifest path is missing: %s" % relative)
        metadata = path.lstat()
        actual_mode = stat.S_IMODE(metadata.st_mode)
        if actual_mode != int(expected["mode"]):
            raise BaselineError("mode mismatch for %s" % relative)
        if expected["type"] == "file":
            if not stat.S_ISREG(metadata.st_mode):
                raise BaselineError("expected regular file: %s" % relative)
            if metadata.st_size != int(expected["size"]):
                raise BaselineError("size mismatch for %s" % relative)
            if _sha256_file(path) != expected["sha256"]:
                raise BaselineError("sha256 mismatch for %s" % relative)
        elif expected["type"] == "symlink":
            if not stat.S_ISLNK(metadata.st_mode):
                raise BaselineError("expected symlink: %s" % relative)
            target = os.readlink(str(path))
            if target != expected["link_target"]:
                raise BaselineError("symlink target mismatch for %s" % relative)
            resolved = path.resolve(strict=True)
            if _sha256_file(resolved) != expected["resolved_sha256"]:
                raise BaselineError("symlink resolved content mismatch for %s" % relative)
        else:
            raise BaselineError("unknown manifest entry type for %s" % relative)
        if strict_metadata and metadata.st_mtime_ns != int(expected["mtime_ns"]):
            raise BaselineError("mtime mismatch for %s" % relative)

    rebuilt = build_manifest(
        root,
        task_id=str(manifest["task_id"]),
        plan_poc_paths=list(manifest.get("plan_poc_paths", [])),
    )
    rebuilt_paths = {str(entry["path"]) for entry in rebuilt["entries"]}
    expected_paths = set(expected_entries)
    if rebuilt_paths != expected_paths:
        added = sorted(rebuilt_paths - expected_paths)
        missing = sorted(expected_paths - rebuilt_paths)
        raise BaselineError("source path set changed; added=%r missing=%r" % (added, missing))
    if rebuilt["content_fingerprint"] != manifest["content_fingerprint"]:
        raise BaselineError("source content fingerprint changed")
    return {
        "root": str(root),
        "entry_count": len(expected_entries),
        "content_fingerprint": manifest["content_fingerprint"],
        "strict_metadata": strict_metadata,
    }


def verify_tar_against_manifest(
    tar_path: Path,
    manifest: Mapping[str, object],
    extraction_root: Path,
) -> Mapping[str, object]:
    safe_extract_tar(tar_path, extraction_root)
    return verify_manifest_against_root(manifest, extraction_root, strict_metadata=False)


def verify_checksum_file(snapshot_root: Path) -> Mapping[str, str]:
    snapshot_root = snapshot_root.resolve(strict=True)
    checksums = {}
    for raw_line in (snapshot_root / "manifest.sha256").read_text(encoding="utf-8").splitlines():
        digest, filename = raw_line.split("  ", 1)
        path = snapshot_root / filename
        if not path.is_file():
            raise BaselineError("checksum target missing: %s" % filename)
        actual = _sha256_file(path)
        if actual != digest:
            raise BaselineError("checksum mismatch: %s" % filename)
        checksums[filename] = digest
    if set(checksums) != {"manifest.json", "source.tar"}:
        raise BaselineError("unexpected checksum target set: %r" % sorted(checksums))
    return checksums


def verify_snapshot(snapshot_root: Path, live_root: Path, extraction_root: Path) -> Mapping[str, object]:
    snapshot_root = snapshot_root.resolve(strict=True)
    checksums = verify_checksum_file(snapshot_root)
    manifest = json.loads((snapshot_root / "manifest.json").read_text(encoding="utf-8"))
    tar_result = verify_tar_against_manifest(snapshot_root / "source.tar", manifest, extraction_root)
    live_result = verify_manifest_against_root(manifest, live_root, strict_metadata=True)
    return {
        "snapshot_root": str(snapshot_root),
        "checksums": checksums,
        "tar_verification": tar_result,
        "live_verification": live_result,
    }


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description="Verify a Protocol v3 source-only snapshot.")
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--live-root", required=True, type=Path)
    parser.add_argument("--extraction-root", required=True, type=Path)
    args = parser.parse_args(list(argv) if argv else None)
    result = verify_snapshot(args.snapshot_root, args.live_root, args.extraction_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
