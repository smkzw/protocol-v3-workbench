#!/usr/bin/env python3
"""Prepare recoverable evidence directories for the locked final 4x3 E2E matrix.

This harness is preparation-only. It performs no API calls, launches no tester,
creates no product projects, copies no runtime, deletes nothing, and never
creates PASS.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


SCRIPT_PATH = Path(__file__).resolve()
WORKSPACE_ROOT = SCRIPT_PATH.parents[2]
PRODUCT_ROOT = WORKSPACE_ROOT.parents[1]
DEFAULT_RUNTIME_ROOT = PRODUCT_ROOT / "runtime"
FORBIDDEN_WORKBENCH_RUNTIME = WORKSPACE_ROOT / "runtime"
DEFAULT_CONFIG_PATH = SCRIPT_PATH.with_name("mw_final_4x3_matrix.json")
ALLOWED_RUN_ROOT = (
    WORKSPACE_ROOT / "runs/execution/mw_final_4x3_harness_20260727"
)
ROUND_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

LOCKED_TESTERS = {
    "A": (
        "Codex subAgent/gpt-5.6-luna-high",
        "gpt-5.6-luna",
    ),
    "B": ("pi/aishuo/cms-model", "aishuo/cms-model"),
    "C": ("codebuddy cli/hy3", "hy3"),
    "D": (
        "pi/google-antigravity/gemini-3.6-flash",
        "google-antigravity/gemini-3.6-flash",
    ),
}

LOCKED_SLOTS = {
    "A1": ("A", "慢性阻塞性肺疾病", "III", "吸入", "greenfield"),
    "A2": ("A", "α1-抗胰蛋白酶缺乏症", "I", "口服", "synopsis_import"),
    "A3": ("A", "不伴鼻息肉的慢性鼻窦炎", "II", "鼻喷", "greenfield"),
    "B1": ("B", "2型糖尿病", "III", "口服", "synopsis_import"),
    "B2": ("B", "发作性睡病", "I", "口服", "greenfield"),
    "B3": ("B", "过敏性结膜炎", "II", "眼用滴剂", "synopsis_import"),
    "C1": ("C", "重度抑郁障碍", "III", "口服", "greenfield"),
    "C2": ("C", "C3肾小球病", "II", "口服", "synopsis_import"),
    "C3": ("C", "脂溢性皮炎", "I", "外用泡沫", "greenfield"),
    "D1": ("D", "帕金森病", "III", "口服", "synopsis_import"),
    "D2": ("D", "杜氏肌营养不良", "IIb", "口服", "greenfield"),
    "D3": ("D", "玫瑰痤疮", "I", "外用乳膏", "synopsis_import"),
}


class HarnessError(RuntimeError):
    """Raised when a preparation gate fails closed."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HarnessError(f"expected JSON object: {path}")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_hhmm(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise HarnessError(f"invalid HH:MM time: {value}") from exc


def normalize_phase(phase: str) -> str:
    if phase == "I":
        return "I"
    if phase in {"II", "IIa", "IIb"}:
        return "II"
    if phase == "III":
        return "III"
    raise HarnessError(f"unsupported phase in locked matrix: {phase}")


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if config.get("schema_version") != "mw-final-4x3-harness-config-2026-07-27.2":
        errors.append("unexpected schema_version")
    if config.get("timezone") != "Asia/Shanghai":
        errors.append("timezone must be Asia/Shanghai")

    testers = config.get("testers")
    tester_map: dict[str, dict[str, Any]] = {}
    if not isinstance(testers, list):
        errors.append("testers must be a list")
    else:
        for tester in testers:
            if not isinstance(tester, dict) or not isinstance(tester.get("code"), str):
                errors.append("each tester must be an object with a code")
                continue
            code = tester["code"]
            if code in tester_map:
                errors.append(f"duplicate tester code: {code}")
            tester_map[code] = tester

    if set(tester_map) != set(LOCKED_TESTERS):
        errors.append(f"tester codes must be {sorted(LOCKED_TESTERS)}")
    for code, expected in LOCKED_TESTERS.items():
        tester = tester_map.get(code, {})
        observed = (
            tester.get("declared_identity"),
            tester.get("requested_selector"),
        )
        if observed != expected:
            errors.append(
                f"tester {code} identity/selector mismatch: {observed!r} != {expected!r}"
            )
        if code in {"A", "D"} and tester.get("thinking_level") != "high":
            errors.append(f"tester {code} thinking_level mismatch: expected 'high'")

    slots = config.get("slots")
    slot_map: dict[str, dict[str, Any]] = {}
    if not isinstance(slots, list):
        errors.append("slots must be a list")
    else:
        for slot in slots:
            if not isinstance(slot, dict) or not isinstance(slot.get("slot"), str):
                errors.append("each slot must be an object with a slot id")
                continue
            slot_id = slot["slot"]
            if slot_id in slot_map:
                errors.append(f"duplicate slot: {slot_id}")
            slot_map[slot_id] = slot

    if set(slot_map) != set(LOCKED_SLOTS):
        errors.append(f"slot ids must be {sorted(LOCKED_SLOTS)}")
    for slot_id, expected in LOCKED_SLOTS.items():
        slot = slot_map.get(slot_id, {})
        observed = (
            slot.get("tester_code"),
            slot.get("indication"),
            slot.get("phase"),
            slot.get("administration_route"),
            slot.get("project_route"),
        )
        if observed != expected:
            errors.append(f"slot {slot_id} mismatch: {observed!r} != {expected!r}")

    indications = [slot.get("indication") for slot in slot_map.values()]
    if len(indications) != 12 or len(set(indications)) != 12:
        errors.append("the 12 locked indications must be unique")

    for code in LOCKED_TESTERS:
        phases: set[str] = set()
        for slot in slot_map.values():
            if slot.get("tester_code") == code:
                try:
                    phases.add(normalize_phase(str(slot.get("phase"))))
                except HarnessError as exc:
                    errors.append(str(exc))
        if phases != {"I", "II", "III"}:
            errors.append(f"tester {code} must cover I/II/III; got {sorted(phases)}")

    if config.get("perspectives") != ["lazy_medical_writer", "engineer"]:
        errors.append("perspectives must be lazy_medical_writer then engineer")

    required_evidence = config.get("required_evidence")
    if not isinstance(required_evidence, list) or not required_evidence:
        errors.append("required_evidence must be a non-empty list")
    elif "PASS.md" in required_evidence:
        errors.append("PASS.md must be gated separately, not a placeholder")
    pass_artifact = config.get("pass_artifact")
    if not isinstance(pass_artifact, dict):
        errors.append("pass_artifact must be an object")
    elif (
        pass_artifact.get("path") != "PASS.md"
        or pass_artifact.get("creation_policy")
        != "forbidden_by_harness_until_full_external_gate"
    ):
        errors.append("PASS.md creation policy is not fail-closed")

    clean_state = config.get("clean_state")
    if not isinstance(clean_state, dict):
        errors.append("clean_state must be an object")
    else:
        if clean_state.get("inventory_mode") != "metadata_only_no_file_content_read":
            errors.append("clean-state inventory must remain metadata-only")
        if clean_state.get("runtime_root_policy") != {
            "default": "product_root/runtime",
            "product_root_relative_to_workbench": "../..",
            "test_override": "explicit_system_temp_root_only",
            "workbench_runtime_forbidden": True,
        }:
            errors.append("clean-state runtime root policy is not locked")
        if clean_state.get("deletion_policy") != "plan_only_no_delete_commands_emitted":
            errors.append("clean-state deletion policy must remain plan-only")
        surfaces = clean_state.get("inventory_surfaces")
        if not isinstance(surfaces, list) or not surfaces:
            errors.append("clean-state inventory_surfaces must be a non-empty list")
        else:
            for raw in surfaces:
                rel = Path(str(raw))
                if rel.is_absolute() or ".." in rel.parts:
                    errors.append(f"unsafe runtime inventory surface: {raw}")
                if rel.parts and rel.parts[0] == "runtime":
                    errors.append(
                        f"runtime inventory surfaces must be relative to runtime root: {raw}"
                    )

    for source in config.get("authoritative_sources", []):
        if not isinstance(source, dict):
            errors.append("authoritative source entries must be objects")
            continue
        if source.get("drift_policy") not in {"block", "record_only"}:
            errors.append(f"invalid source drift policy: {source!r}")
        if not SHA256_RE.fullmatch(str(source.get("sha256", ""))):
            errors.append(f"invalid source sha256: {source.get('path')}")

    if errors:
        raise HarnessError("config validation failed:\n- " + "\n- ".join(errors))
    return {
        "status": "VALID",
        "tester_count": len(tester_map),
        "slot_count": len(slot_map),
        "unique_indication_count": len(set(indications)),
    }


def verify_authoritative_sources(
    config: dict[str, Any],
    workspace_root: Path,
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    blocking: list[str] = []
    root = workspace_root.resolve()
    for source in config.get("authoritative_sources", []):
        rel = Path(source["path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise HarnessError(f"unsafe authoritative source path: {rel}")
        path = root / rel
        exists = path.is_file()
        observed = sha256_file(path) if exists else None
        matches = observed == source["sha256"]
        receipt = {
            "path": source["path"],
            "expected_sha256": source["sha256"],
            "observed_sha256": observed,
            "exists": exists,
            "matches": matches,
            "drift_policy": source["drift_policy"],
        }
        receipts.append(receipt)
        if source["drift_policy"] == "block" and not matches:
            blocking.append(source["path"])
    if blocking:
        raise HarnessError(
            "blocking source drift or missing source: " + ", ".join(blocking)
        )
    return receipts


def parse_schedule_timestamp(value: str, timezone_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HarnessError(f"invalid planned_start_at: {value}") from exc
    if parsed.tzinfo is None:
        raise HarnessError(f"planned_start_at must include UTC offset: {value}")
    return parsed.astimezone(ZoneInfo(timezone_name))


def in_wrapped_window(current: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def evaluate_schedule(
    config: dict[str, Any],
    schedule: dict[str, Any],
) -> list[dict[str, Any]]:
    if schedule.get("schema_version") != "mw-final-4x3-schedule-2026-07-27.1":
        raise HarnessError("unexpected schedule schema_version")
    entries = schedule.get("slots")
    if not isinstance(entries, list):
        raise HarnessError("schedule slots must be a list")

    slot_map = {item["slot"]: item for item in config["slots"]}
    tester_map = {item["code"]: item for item in config["testers"]}
    schedule_map: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("slot"), str):
            raise HarnessError("each schedule entry must include a slot id")
        slot_id = entry["slot"]
        if slot_id in schedule_map:
            raise HarnessError(f"duplicate schedule slot: {slot_id}")
        schedule_map[slot_id] = entry
    if set(schedule_map) != set(slot_map):
        missing = sorted(set(slot_map) - set(schedule_map))
        extra = sorted(set(schedule_map) - set(slot_map))
        raise HarnessError(f"schedule must cover exactly 12 slots; missing={missing}, extra={extra}")

    decisions: list[dict[str, Any]] = []
    for slot_id in sorted(slot_map):
        scenario = slot_map[slot_id]
        entry = schedule_map[slot_id]
        tester = tester_map[scenario["tester_code"]]
        if entry.get("declared_tester") != tester["declared_identity"]:
            raise HarnessError(f"{slot_id} declared tester mismatch")
        if entry.get("requested_selector") != tester["requested_selector"]:
            raise HarnessError(f"{slot_id} requested selector mismatch")
        if entry.get("thinking_level") != tester.get("thinking_level"):
            raise HarnessError(f"{slot_id} thinking level mismatch")
        operation = entry.get("operation")
        if operation not in {"initial_pass", "follow_up", "remediation"}:
            raise HarnessError(f"{slot_id} has invalid operation: {operation}")

        local = parse_schedule_timestamp(
            str(entry.get("planned_start_at", "")),
            config["timezone"],
        )
        decision = "ALLOW"
        reason = "exact static identity and legal local time"
        current = local.timetz().replace(tzinfo=None)

        blackout = tester.get("blackout_window")
        if blackout:
            start = parse_hhmm(blackout["start"])
            end = parse_hhmm(blackout["end"])
            minute = current.hour * 60 + current.minute
            start_minute = start.hour * 60 + start.minute
            end_minute = end.hour * 60 + end.minute
            if start_minute <= minute <= end_minute:
                decision = "DEFER"
                reason = "aishuo Beijing blackout; resume only from 08:31"

        preferred = tester.get("preferred_window")
        if preferred and not in_wrapped_window(
            current,
            parse_hhmm(preferred["start"]),
            parse_hhmm(preferred["end"]),
        ):
            outside_reason = entry.get("outside_preferred_window_reason")
            if preferred.get("outside_requires_reason") and not (
                isinstance(outside_reason, str) and outside_reason.strip()
            ):
                decision = "DEFER"
                reason = "outside Alibaba preferred window without recorded reason"
            else:
                reason = "outside Alibaba preferred window with recorded reason"

        decisions.append(
            {
                "slot": slot_id,
                "tester_code": scenario["tester_code"],
                "declared_tester": tester["declared_identity"],
                "requested_selector": tester["requested_selector"],
                "thinking_level": tester.get("thinking_level"),
                "operation": operation,
                "planned_start_at_input": entry["planned_start_at"],
                "planned_start_at_beijing": local.isoformat(),
                "decision": decision,
                "reason": reason,
                "runtime_identity_verification": "REQUIRED_AT_ACTUAL_LAUNCH",
            }
        )
    return decisions


def inventory_path(path: Path, runtime_root: Path) -> dict[str, Any]:
    rel = path.relative_to(runtime_root)
    result: dict[str, Any] = {
        "path": rel.as_posix(),
        "exists": False,
        "inventory_mode": "metadata_only",
        "content_hash": "NOT_COLLECTED",
    }
    try:
        root_stat = path.lstat()
    except FileNotFoundError:
        return result
    except OSError as exc:
        result["error"] = str(exc)
        return result

    result["exists"] = True
    result["mtime_ns"] = root_stat.st_mtime_ns
    result["mode"] = stat.filemode(root_stat.st_mode)
    if stat.S_ISLNK(root_stat.st_mode):
        result["type"] = "symlink"
        result["symlink_target"] = os.readlink(path)
        return result
    if stat.S_ISREG(root_stat.st_mode):
        result["type"] = "file"
        result["bytes"] = root_stat.st_size
        return result
    if not stat.S_ISDIR(root_stat.st_mode):
        result["type"] = "other"
        return result

    file_count = 0
    directory_count = 1
    symlink_count = 0
    total_bytes = 0
    errors: list[str] = []
    for current_root, dirs, files in os.walk(path, followlinks=False):
        directory_count += len(dirs)
        for name in dirs + files:
            item = Path(current_root) / name
            try:
                item_stat = item.lstat()
            except OSError as exc:
                errors.append(f"{item.relative_to(path)}: {exc}")
                continue
            if stat.S_ISLNK(item_stat.st_mode):
                symlink_count += 1
            elif stat.S_ISREG(item_stat.st_mode):
                file_count += 1
                total_bytes += item_stat.st_size
    result.update(
        {
            "type": "directory",
            "directory_count": directory_count,
            "file_count": file_count,
            "symlink_count": symlink_count,
            "total_bytes": total_bytes,
        }
    )
    if errors:
        result["errors"] = errors
    return result


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _validated_system_temp_base(path: Path) -> Path:
    system_temp = Path(tempfile.gettempdir()).resolve()
    resolved = path.expanduser().resolve(strict=False)
    if not _is_within(resolved, system_temp):
        raise HarnessError(
            f"test root must stay under system temporary directory {system_temp}"
        )
    return resolved


def resolve_runtime_root(
    runtime_root: Path | None = None,
    *,
    test_runtime_base: Path | None = None,
) -> dict[str, Any]:
    default_root = DEFAULT_RUNTIME_ROOT.resolve(strict=False)
    forbidden = FORBIDDEN_WORKBENCH_RUNTIME.resolve(strict=False)
    if default_root == forbidden:
        raise HarnessError("internal runtime root resolution collapsed to workbench/runtime")

    if runtime_root is None:
        return {"path": default_root, "mode": "DEFAULT_PRODUCT_RUNTIME"}

    candidate = runtime_root.expanduser().resolve(strict=False)
    if candidate == forbidden:
        raise HarnessError("workbench/runtime is forbidden as an authoritative runtime")
    if candidate == default_root:
        return {"path": default_root, "mode": "EXPLICIT_PRODUCT_RUNTIME"}
    if test_runtime_base is None:
        raise HarnessError(
            "non-product runtime override requires an explicit test_runtime_base"
        )
    test_base = _validated_system_temp_base(test_runtime_base)
    if not _is_within(candidate, test_base):
        raise HarnessError(f"runtime override must stay under test root {test_base}")
    return {"path": candidate, "mode": "TEST_RUNTIME_OVERRIDE"}


def resolve_output_root(
    output_root: Path,
    *,
    test_output_base: Path | None = None,
) -> Path:
    allowed = ALLOWED_RUN_ROOT.resolve(strict=False)
    resolved = output_root.expanduser().resolve(strict=False)
    if _is_within(resolved, allowed):
        return resolved
    if test_output_base is not None:
        test_base = _validated_system_temp_base(test_output_base)
        if _is_within(resolved, test_base):
            return resolved
    raise HarnessError(f"output root must stay under {allowed}")


def safe_runtime_child(runtime_root: Path, raw: str) -> Path:
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        raise HarnessError(f"unsafe runtime inventory path: {raw}")
    parent = (runtime_root / rel.parent).resolve(strict=False)
    if not _is_within(parent, runtime_root):
        raise HarnessError(f"runtime inventory path escapes root: {raw}")
    return parent / rel.name


def build_readonly_inventory(
    config: dict[str, Any],
    runtime_root: Path,
    runtime_root_mode: str,
    generated_at: str,
) -> dict[str, Any]:
    root = runtime_root.resolve(strict=False)
    items = []
    for raw in config["clean_state"]["inventory_surfaces"]:
        items.append(inventory_path(safe_runtime_child(root, raw), root))
    return {
        "schema_version": "mw-final-4x3-readonly-inventory-2026-07-27.2",
        "status": "READ_ONLY_INVENTORY_ONLY",
        "generated_at": generated_at,
        "runtime_root": str(root),
        "runtime_root_mode": runtime_root_mode,
        "file_content_read": False,
        "database_opened": False,
        "snapshot_created": False,
        "delete_performed": False,
        "items": items,
    }


def build_snapshot_delete_plan(
    inventory: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    proposed = []
    for item in inventory["items"]:
        path = item["path"]
        suffix = Path(path).suffix.lower()
        if suffix in {".sqlite", ".sqlite3", ".db"} or ".sqlite3-" in path:
            method = "SQLITE_ONLINE_BACKUP_OR_COORDINATED_STOP_WITH_WAL_SHM"
        elif item.get("type") == "directory":
            method = "ARCHIVE_DIRECTORY_AFTER_QUIESCENCE"
        else:
            method = "COPY_AFTER_QUIESCENCE"
        proposed.append(
            {
                "source": path,
                "exists_at_inventory": item["exists"],
                "snapshot_method": method,
                "snapshot_destination": f"<verified_snapshot_root>/{path}",
                "delete_candidate_status": "REVIEW_ONLY_AFTER_VERIFIED_SNAPSHOT",
                "snapshot_executed": False,
                "delete_executed": False,
            }
        )
    return {
        "schema_version": "mw-final-4x3-snapshot-delete-plan-2026-07-27.2",
        "status": "PLAN_ONLY",
        "generated_at": generated_at,
        "runtime_root": inventory["runtime_root"],
        "runtime_root_mode": inventory["runtime_root_mode"],
        "commands_emitted": False,
        "snapshot_created": False,
        "delete_performed": False,
        "restore_preconditions": [
            "quiesce active jobs at a resumable boundary",
            "preserve SQLite base files with WAL/SHM or use online backup",
            "verify snapshot manifest and project counts read-only",
            "prove restore in an isolated runtime before any shared-state cleanup",
        ],
        "proposed_actions": proposed,
    }


def ensure_cli_output_root(path: Path) -> Path:
    return resolve_output_root(path)


def make_input_fingerprint(
    config: dict[str, Any],
    schedule: dict[str, Any],
    round_id: str,
    runtime_root: Path,
) -> str:
    return sha256_bytes(
        canonical_json(
            {
                "config": config,
                "schedule": schedule,
                "round_id": round_id,
                "runtime_root": str(runtime_root),
            }
        ).encode("utf-8")
    )


def prepare_round(
    *,
    config: dict[str, Any],
    schedule: dict[str, Any],
    workspace_root: Path,
    output_root: Path,
    round_id: str,
    generated_at: str,
    verify_sources: bool = True,
    runtime_root: Path | None = None,
    test_runtime_base: Path | None = None,
    test_output_base: Path | None = None,
) -> dict[str, Any]:
    validate_config(config)
    if not ROUND_ID_RE.fullmatch(round_id):
        raise HarnessError(f"invalid round id: {round_id}")
    decisions = evaluate_schedule(config, schedule)
    deferred = [item["slot"] for item in decisions if item["decision"] != "ALLOW"]
    if deferred:
        raise HarnessError(
            "round preparation deferred before directory creation: "
            + ", ".join(deferred)
        )

    source_receipts = (
        verify_authoritative_sources(config, workspace_root)
        if verify_sources
        else []
    )
    resolved_runtime = resolve_runtime_root(
        runtime_root,
        test_runtime_base=test_runtime_base,
    )
    output_root = resolve_output_root(
        output_root,
        test_output_base=test_output_base,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    rounds_root = output_root / "rounds"
    rounds_root.mkdir(parents=True, exist_ok=True)
    final_dir = rounds_root / round_id
    fingerprint = make_input_fingerprint(
        config,
        schedule,
        round_id,
        resolved_runtime["path"],
    )
    if final_dir.exists():
        manifest_path = final_dir / "ROUND_MANIFEST.json"
        manifest = read_json(manifest_path)
        if manifest.get("input_fingerprint") != fingerprint:
            raise HarnessError(
                f"round {round_id} already exists with different locked inputs"
            )
        return {
            "status": "REUSED_EXISTING_ROUND",
            "round_dir": str(final_dir),
            "input_fingerprint": fingerprint,
        }

    inventory = build_readonly_inventory(
        config,
        resolved_runtime["path"],
        resolved_runtime["mode"],
        generated_at,
    )
    plan = build_snapshot_delete_plan(inventory, generated_at)
    tester_map = {item["code"]: item for item in config["testers"]}
    decision_map = {item["slot"]: item for item in decisions}

    stage_dir = Path(
        tempfile.mkdtemp(prefix=f".{round_id}.staging-", dir=rounds_root)
    )
    try:
        manifest = {
            "schema_version": "mw-final-4x3-round-manifest-2026-07-27.2",
            "status": "PREPARED_NOT_EXECUTED",
            "round_id": round_id,
            "generated_at": generated_at,
            "input_fingerprint": fingerprint,
            "slot_count": 12,
            "perspective_count": 24,
            "tester_launched": False,
            "product_project_created": False,
            "product_ai_called": False,
            "runtime_modified": False,
            "docx_generator_touched": False,
            "runtime_root": str(resolved_runtime["path"]),
            "runtime_root_mode": resolved_runtime["mode"],
            "source_receipts": source_receipts,
            "schedule_decisions": decisions,
            "resume_rule": (
                "Reuse only when input_fingerprint matches; otherwise choose a new round id."
            ),
        }
        write_json(stage_dir / "ROUND_MANIFEST.json", manifest)
        write_json(stage_dir / "clean_state/READ_ONLY_INVENTORY.json", inventory)
        write_json(stage_dir / "clean_state/SNAPSHOT_DELETE_PLAN.json", plan)

        for scenario in sorted(config["slots"], key=lambda item: item["slot"]):
            slot_id = scenario["slot"]
            tester = tester_map[scenario["tester_code"]]
            slot_root = stage_dir / "slots" / slot_id
            write_json(
                slot_root / "SLOT_CONTRACT.json",
                {
                    "schema_version": "mw-final-4x3-slot-contract-2026-07-27.1",
                    "status": "NOT_STARTED",
                    "round_id": round_id,
                    "scenario": scenario,
                    "tester": {
                        "declared_identity": tester["declared_identity"],
                        "requested_selector": tester["requested_selector"],
                        "thinking_level": tester.get("thinking_level"),
                    },
                    "schedule_check": decision_map[slot_id],
                    "runtime_identity_verified": False,
                    "product_project_id": None,
                    "product_ai_output_present": False,
                },
            )
            for perspective in config["perspectives"]:
                expected = [
                    {
                        "path": path,
                        "status": "MISSING_NOT_STARTED",
                        "created_by_harness": False,
                    }
                    for path in config["required_evidence"]
                ]
                write_json(
                    slot_root / perspective / "EXPECTED_EVIDENCE.json",
                    {
                        "schema_version": (
                            "mw-final-4x3-expected-evidence-2026-07-27.1"
                        ),
                        "status": "NOT_STARTED",
                        "slot": slot_id,
                        "perspective": perspective,
                        "required_files_or_patterns": expected,
                        "pass_artifact": {
                            "path": config["pass_artifact"]["path"],
                            "status": "FORBIDDEN_UNTIL_FULL_EXTERNAL_GATE",
                            "created_by_harness": False,
                        },
                    },
                )

        forbidden = list(stage_dir.rglob(config["pass_artifact"]["path"]))
        if forbidden:
            raise HarnessError(f"harness generated forbidden PASS artifact: {forbidden}")
        os.replace(stage_dir, final_dir)
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise

    return {
        "status": "CREATED_PREPARATION_ROUND",
        "round_dir": str(final_dir),
        "input_fingerprint": fingerprint,
        "slot_count": 12,
        "perspective_count": 24,
    }


def schedule_template(config: dict[str, Any]) -> dict[str, Any]:
    tester_map = {item["code"]: item for item in config["testers"]}
    entries = []
    for scenario in sorted(config["slots"], key=lambda item: item["slot"]):
        tester = tester_map[scenario["tester_code"]]
        entries.append(
            {
                "slot": scenario["slot"],
                "declared_tester": tester["declared_identity"],
                "requested_selector": tester["requested_selector"],
                "thinking_level": tester.get("thinking_level"),
                "planned_start_at": "YYYY-MM-DDTHH:MM:SS+08:00",
                "operation": "initial_pass",
                "outside_preferred_window_reason": None,
            }
        )
    return {
        "schema_version": "mw-final-4x3-schedule-2026-07-27.1",
        "status": "TEMPLATE_REQUIRES_REAL_TIMES",
        "slots": entries,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate-config")

    template = subparsers.add_parser("write-schedule-template")
    template.add_argument(
        "--output",
        type=Path,
        default=ALLOWED_RUN_ROOT / "SCHEDULE_TEMPLATE.json",
    )

    prepare = subparsers.add_parser("prepare-round")
    prepare.add_argument("--round-id", required=True)
    prepare.add_argument("--schedule", type=Path, required=True)
    prepare.add_argument(
        "--runtime-root",
        type=Path,
        default=None,
        help="Real product runtime, or a test root under --test-runtime-base.",
    )
    prepare.add_argument(
        "--test-runtime-base",
        type=Path,
        default=None,
        help="Explicit system-temporary boundary required for test runtime overrides.",
    )
    prepare.add_argument(
        "--output-root",
        type=Path,
        default=ALLOWED_RUN_ROOT,
    )
    prepare.add_argument(
        "--generated-at",
        default=None,
        help="ISO timestamp; defaults to current Asia/Shanghai time",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = read_json(args.config)
        validation = validate_config(config)
        if args.command == "validate-config":
            validation["default_runtime_root"] = str(
                resolve_runtime_root()["path"]
            )
            validation["source_receipts"] = verify_authoritative_sources(
                config, WORKSPACE_ROOT
            )
            print(json.dumps(validation, ensure_ascii=False, indent=2))
            return 0
        if args.command == "write-schedule-template":
            output = ensure_cli_output_root(args.output)
            if output.exists():
                raise HarnessError(f"refusing to overwrite schedule template: {output}")
            write_json(output, schedule_template(config))
            print(json.dumps({"status": "CREATED", "path": str(output)}, ensure_ascii=False))
            return 0
        if args.command == "prepare-round":
            generated_at = args.generated_at or datetime.now(
                ZoneInfo(config["timezone"])
            ).isoformat()
            result = prepare_round(
                config=config,
                schedule=read_json(args.schedule),
                workspace_root=WORKSPACE_ROOT,
                output_root=args.output_root,
                round_id=args.round_id,
                generated_at=generated_at,
                runtime_root=args.runtime_root,
                test_runtime_base=args.test_runtime_base,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
    except HarnessError as exc:
        print(f"HARNESS_BLOCKED: {exc}", file=sys.stderr)
        return 2
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
