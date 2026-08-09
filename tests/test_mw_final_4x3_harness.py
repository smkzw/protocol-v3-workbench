from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/qc/mw_final_4x3_harness.py"
CONFIG = ROOT / "scripts/qc/mw_final_4x3_matrix.json"
PROMPT_ROOT = ROOT / "prompts/final_4x3_e2e_20260727"
SPEC = importlib.util.spec_from_file_location("mw_final_4x3_harness", SCRIPT)
assert SPEC and SPEC.loader
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def valid_schedule(config: dict) -> dict:
    tester_map = {item["code"]: item for item in config["testers"]}
    starts = {
        "A": "2026-07-27T09:00:00+08:00",
        "B": "2026-07-27T08:31:00+08:00",
        "C": "2026-07-27T09:00:00+08:00",
        "D": "2026-07-27T09:00:00+08:00",
    }
    return {
        "schema_version": "mw-final-4x3-schedule-2026-07-27.1",
        "slots": [
            {
                "slot": slot["slot"],
                "declared_tester": tester_map[slot["tester_code"]][
                    "declared_identity"
                ],
                "requested_selector": tester_map[slot["tester_code"]][
                    "requested_selector"
                ],
                "thinking_level": tester_map[slot["tester_code"]].get(
                    "thinking_level"
                ),
                "planned_start_at": starts[slot["tester_code"]],
                "operation": "initial_pass",
                "outside_preferred_window_reason": None,
            }
            for slot in config["slots"]
        ],
    }


def test_locked_matrix_is_exact_and_has_12_unique_indications() -> None:
    result = HARNESS.validate_config(load_config())
    assert result == {
        "status": "VALID",
        "tester_count": 4,
        "slot_count": 12,
        "unique_indication_count": 12,
    }


def test_current_tester_a_prompt_package_matches_locked_luna_identity() -> None:
    config = load_config()
    tester_a = next(item for item in config["testers"] if item["code"] == "A")
    assignment = json.loads(
        (PROMPT_ROOT / "MATRIX_ASSIGNMENT.json").read_text(encoding="utf-8")
    )
    assigned_a = assignment["testers"][0]
    route_guard = (PROMPT_ROOT / "ROUTE_TIME_GUARD.md").read_text(
        encoding="utf-8"
    )
    readme = (PROMPT_ROOT / "README.md").read_text(encoding="utf-8")
    launch_prompt = (
        PROMPT_ROOT / "TESTER_A_CODEX_SUBAGENT_LUNA_HIGH.md"
    ).read_text(encoding="utf-8")

    assert assigned_a["tester"] == tester_a["declared_identity"]
    assert assigned_a["requested_selector"] == tester_a["requested_selector"]
    assert assigned_a["reasoning_effort"] == tester_a["thinking_level"]
    assert "Codex subAgent `gpt-5.6-luna`" in route_guard
    assert "Alibaba Preferred Window" not in route_guard
    assert "TESTER_A_CODEX_SUBAGENT_LUNA_HIGH.md" in readme
    assert tester_a["declared_identity"] in launch_prompt


def test_default_runtime_root_matches_product_root_not_workbench_runtime() -> None:
    resolved = HARNESS.resolve_runtime_root()
    expected = (ROOT.parents[1] / "runtime").resolve(strict=False)
    assert resolved == {
        "path": expected,
        "mode": "DEFAULT_PRODUCT_RUNTIME",
    }
    assert resolved["path"] != (ROOT / "runtime").resolve(strict=False)


def test_explicit_test_runtime_override_stays_inside_system_temp(
    tmp_path: Path,
) -> None:
    test_base = tmp_path / "runtime-boundary"
    runtime = test_base / "slot-A1/runtime"
    resolved = HARNESS.resolve_runtime_root(
        runtime,
        test_runtime_base=test_base,
    )
    assert resolved == {
        "path": runtime.resolve(strict=False),
        "mode": "TEST_RUNTIME_OVERRIDE",
    }


def test_runtime_root_rejects_workbench_and_malicious_escape(
    tmp_path: Path,
) -> None:
    with pytest.raises(HARNESS.HarnessError, match="workbench/runtime is forbidden"):
        HARNESS.resolve_runtime_root(ROOT / "runtime")

    test_base = tmp_path / "allowed"
    outside = tmp_path / "outside"
    with pytest.raises(HARNESS.HarnessError, match="must stay under test root"):
        HARNESS.resolve_runtime_root(
            outside,
            test_runtime_base=test_base,
        )

    test_base.mkdir()
    outside.mkdir()
    (test_base / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(HARNESS.HarnessError, match="must stay under test root"):
        HARNESS.resolve_runtime_root(
            test_base / "escape/runtime",
            test_runtime_base=test_base,
        )


def test_runtime_inventory_surfaces_are_relative_to_runtime_root() -> None:
    config = load_config()
    surfaces = config["clean_state"]["inventory_surfaces"]
    assert surfaces
    assert all(not Path(item).is_absolute() for item in surfaces)
    assert all(Path(item).parts[0] != "runtime" for item in surfaces)


@pytest.mark.parametrize(
    ("target", "key", "value"),
    [
        (("testers", 0), "declared_identity", "Codex subAgent/gpt-5.6-terra-high"),
        (("testers", 1), "requested_selector", "fallback/model"),
        (("testers", 3), "thinking_level", "medium"),
        (("slots", 0), "indication", "替换适应症"),
        (("slots", 4), "phase", "II"),
        (("slots", 11), "project_route", "greenfield"),
        (("slots", 2), "administration_route", "口服"),
    ],
)
def test_locked_tester_scenario_phase_route_and_path_cannot_drift(
    target: tuple[str, int],
    key: str,
    value: str,
) -> None:
    config = load_config()
    config[target[0]][target[1]][key] = value
    with pytest.raises(HARNESS.HarnessError, match="mismatch"):
        HARNESS.validate_config(config)


def test_aishuo_blackout_is_inclusive_through_0830_and_0831_is_legal() -> None:
    config = load_config()
    schedule = valid_schedule(config)
    b_entries = [item for item in schedule["slots"] if item["slot"].startswith("B")]

    for blocked_at in (
        "2026-07-27T00:00:00+08:00",
        "2026-07-27T08:30:59+08:00",
    ):
        candidate = copy.deepcopy(schedule)
        for entry in candidate["slots"]:
            if entry["slot"].startswith("B"):
                entry["planned_start_at"] = blocked_at
        decisions = HARNESS.evaluate_schedule(config, candidate)
        assert {
            item["decision"]
            for item in decisions
            if item["slot"].startswith("B")
        } == {"DEFER"}

    assert len(b_entries) == 3
    decisions = HARNESS.evaluate_schedule(config, schedule)
    assert {
        item["decision"] for item in decisions if item["slot"].startswith("B")
    } == {"ALLOW"}


def test_subagent_has_no_artificial_time_window() -> None:
    config = load_config()
    schedule = valid_schedule(config)
    for entry in schedule["slots"]:
        if entry["slot"].startswith("A"):
            entry["planned_start_at"] = "2026-07-27T03:00:00+08:00"
    decisions = HARNESS.evaluate_schedule(config, schedule)
    assert {
        item["decision"] for item in decisions if item["slot"].startswith("A")
    } == {"ALLOW"}


def test_prepare_round_creates_recoverable_12_slot_scaffold_without_pass(
    tmp_path: Path,
) -> None:
    config = load_config()
    config["authoritative_sources"] = []
    workspace = tmp_path / "workspace"
    runtime_base = tmp_path / "runtime-boundary"
    runtime = runtime_base / "slot-runtime"
    runtime.mkdir(parents=True)
    database = runtime / "user_projects.sqlite3"
    database.write_bytes(b"read-only-inventory-fixture")
    before = database.read_bytes()
    output = workspace / "runs/execution/mw_final_4x3_harness_20260727"

    result = HARNESS.prepare_round(
        config=config,
        schedule=valid_schedule(config),
        workspace_root=workspace,
        output_root=output,
        round_id="round_001",
        generated_at="2026-07-27T09:00:00+08:00",
        verify_sources=False,
        runtime_root=runtime,
        test_runtime_base=runtime_base,
        test_output_base=tmp_path,
    )

    assert result["status"] == "CREATED_PREPARATION_ROUND"
    round_root = output / "rounds/round_001"
    assert len(list((round_root / "slots").glob("[A-D][1-3]"))) == 12
    expected = list(round_root.glob("slots/[A-D][1-3]/*/EXPECTED_EVIDENCE.json"))
    assert len(expected) == 24
    assert not list(round_root.rglob("PASS.md"))
    for path in expected:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["status"] == "NOT_STARTED"
        assert payload["pass_artifact"] == {
            "path": "PASS.md",
            "status": "FORBIDDEN_UNTIL_FULL_EXTERNAL_GATE",
            "created_by_harness": False,
        }
        assert all(
            item["status"] == "MISSING_NOT_STARTED"
            for item in payload["required_files_or_patterns"]
        )

    inventory = json.loads(
        (round_root / "clean_state/READ_ONLY_INVENTORY.json").read_text(
            encoding="utf-8"
        )
    )
    assert inventory["database_opened"] is False
    assert inventory["delete_performed"] is False
    assert inventory["snapshot_created"] is False
    assert inventory["runtime_root"] == str(runtime.resolve())
    assert inventory["runtime_root_mode"] == "TEST_RUNTIME_OVERRIDE"
    user_projects = next(
        item for item in inventory["items"] if item["path"] == "user_projects.sqlite3"
    )
    assert user_projects["exists"] is True
    assert user_projects["bytes"] == len(before)
    assert database.read_bytes() == before

    plan = json.loads(
        (round_root / "clean_state/SNAPSHOT_DELETE_PLAN.json").read_text(
            encoding="utf-8"
        )
    )
    assert plan["status"] == "PLAN_ONLY"
    assert plan["runtime_root"] == str(runtime.resolve())
    assert plan["runtime_root_mode"] == "TEST_RUNTIME_OVERRIDE"
    assert plan["commands_emitted"] is False
    assert plan["delete_performed"] is False
    assert all(
        not item["snapshot_executed"] and not item["delete_executed"]
        for item in plan["proposed_actions"]
    )


def test_prepare_round_is_idempotent_and_rejects_changed_inputs(
    tmp_path: Path,
) -> None:
    config = load_config()
    config["authoritative_sources"] = []
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime_base = tmp_path / "runtime-boundary"
    runtime = runtime_base / "slot-runtime"
    output = workspace / "runs/execution/mw_final_4x3_harness_20260727"
    schedule = valid_schedule(config)

    first = HARNESS.prepare_round(
        config=config,
        schedule=schedule,
        workspace_root=workspace,
        output_root=output,
        round_id="round_resume",
        generated_at="2026-07-27T09:00:00+08:00",
        verify_sources=False,
        runtime_root=runtime,
        test_runtime_base=runtime_base,
        test_output_base=tmp_path,
    )
    second = HARNESS.prepare_round(
        config=config,
        schedule=schedule,
        workspace_root=workspace,
        output_root=output,
        round_id="round_resume",
        generated_at="2026-07-28T09:00:00+08:00",
        verify_sources=False,
        runtime_root=runtime,
        test_runtime_base=runtime_base,
        test_output_base=tmp_path,
    )
    assert first["input_fingerprint"] == second["input_fingerprint"]
    assert second["status"] == "REUSED_EXISTING_ROUND"

    changed = copy.deepcopy(schedule)
    changed["slots"][0]["planned_start_at"] = "2026-07-28T22:00:00+08:00"
    with pytest.raises(HARNESS.HarnessError, match="different locked inputs"):
        HARNESS.prepare_round(
            config=config,
            schedule=changed,
            workspace_root=workspace,
            output_root=output,
            round_id="round_resume",
            generated_at="2026-07-28T09:00:00+08:00",
            verify_sources=False,
            runtime_root=runtime,
            test_runtime_base=runtime_base,
            test_output_base=tmp_path,
        )


def test_deferred_schedule_creates_no_round_directory(tmp_path: Path) -> None:
    config = load_config()
    config["authoritative_sources"] = []
    schedule = valid_schedule(config)
    for entry in schedule["slots"]:
        if entry["slot"].startswith("B"):
            entry["planned_start_at"] = "2026-07-27T03:00:00+08:00"
    output = tmp_path / "runs/execution/mw_final_4x3_harness_20260727"

    with pytest.raises(HARNESS.HarnessError, match="deferred"):
        HARNESS.prepare_round(
            config=config,
            schedule=schedule,
            workspace_root=tmp_path,
            output_root=output,
            round_id="blocked_round",
            generated_at="2026-07-27T03:00:00+08:00",
            verify_sources=False,
        )
    assert not (output / "rounds/blocked_round").exists()


def test_cli_output_root_is_confined_to_allowed_run_root(tmp_path: Path) -> None:
    with pytest.raises(HARNESS.HarnessError, match="must stay under"):
        HARNESS.ensure_cli_output_root(tmp_path / "outside")
