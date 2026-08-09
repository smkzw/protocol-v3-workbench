from __future__ import annotations

import hashlib
import json
import signal
import socket
import stat
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from scripts.qc import mw_final_e2e_runtime as RUNTIME
from scripts.qc import mw_isolated_runtime_baseline as BASELINE
from services.api.app.runtime_readiness import BACKEND_BUILD_ID


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def make_prepared_run(
    tmp_path: Path,
    *,
    round_id: str = "round-01",
    slot: str = "A1",
    perspective: str = "lazy_medical_writer",
) -> tuple[Path, Path]:
    run_root = tmp_path / "locked-run-root"
    run_dir = run_root / "rounds" / round_id / "slots" / slot / perspective
    run_dir.mkdir(parents=True)
    write_json(
        run_root / "rounds" / round_id / "ROUND_MANIFEST.json",
        {
            "schema_version": "mw-final-4x3-round-manifest-2026-07-27.2",
            "status": "PREPARED_NOT_EXECUTED",
            "round_id": round_id,
        },
    )
    write_json(
        run_dir / "EXPECTED_EVIDENCE.json",
        {
            "schema_version": "mw-final-4x3-expected-evidence-2026-07-27.1",
            "status": "NOT_STARTED",
            "slot": slot,
            "perspective": perspective,
        },
    )
    return run_root, run_dir


def make_source_runtime(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    source = tmp_path / "source-runtime"
    source.mkdir()
    contents = {
        "ai_provider_settings.json": b'{"profile":"test"}\n',
        "ai_provider_secrets.json": b'{"api_key":"SUPER_SECRET_DO_NOT_LEAK"}\n',
        "ai_provider_master.key": b"test-master-key-material",
        "ai_role_bindings.json": b'{"roles":[]}\n',
    }
    for filename, content in contents.items():
        (source / filename).write_bytes(content)
    return source, contents


def make_fake_node(tmp_path: Path) -> Path:
    node = tmp_path / "node"
    node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    node.chmod(0o700)
    return node


class FakeProcess:
    def __init__(
        self,
        state: "FakeRuntimeState",
        pid: int,
        command: list[str],
        port: int,
        kind: str,
        environment: dict[str, str],
    ) -> None:
        self.state = state
        self.pid = pid
        self.command = command
        self.port = port
        self.kind = kind
        self.environment = environment

    def poll(self) -> int | None:
        return None if self.state.alive.get(self.pid) else 0

    def terminate(self) -> None:
        self.state.stop_pid(self.pid, signal.SIGTERM)

    def kill(self) -> None:
        self.state.stop_pid(self.pid, signal.SIGKILL)


class FakeRuntimeState:
    def __init__(self) -> None:
        self.next_pid = 41000
        self.alive: dict[int, bool] = {}
        self.identities: dict[int, dict[str, str]] = {}
        self.listeners: dict[int, set[int]] = {}
        self.processes: list[FakeProcess] = []
        self.popen_kwargs: list[dict[str, Any]] = []
        self.signals: list[tuple[int, int]] = []
        self.verify_calls = 0
        self.frontend_started_before_clean = False
        self.clean_verified = False
        self.frontend_contract_override: dict[str, Any] = {}
        self.readiness_override: dict[str, Any] = {}
        self.fail_clean_verification = False
        self.clock = 0.0

    def popen(self, command: list[str], **kwargs: Any) -> FakeProcess:
        self.next_pid += 1
        pid = self.next_pid
        kind = "api" if "uvicorn" in command else "frontend"
        port = int(command[command.index("--port") + 1])
        if kind == "frontend" and not self.clean_verified:
            self.frontend_started_before_clean = True
        command_text = "\0".join(command)
        identity = {
            "start_marker": f"fake-start-{pid}",
            "command_sha256": hashlib.sha256(
                command_text.encode("utf-8")
            ).hexdigest(),
        }
        process = FakeProcess(
            self,
            pid,
            command,
            port,
            kind,
            dict(kwargs.get("env") or {}),
        )
        self.alive[pid] = True
        self.identities[pid] = identity
        self.listeners[port] = {pid}
        self.processes.append(process)
        self.popen_kwargs.append(dict(kwargs))
        return process

    def process_identity(self, pid: int) -> dict[str, str] | None:
        if not self.alive.get(pid):
            return None
        return dict(self.identities[pid])

    def listener_pids(self, port: int) -> set[int]:
        return set(self.listeners.get(port, set()))

    def stop_pid(self, pid: int, signum: int) -> None:
        self.signals.append((pid, signum))
        self.alive[pid] = False
        for port, pids in list(self.listeners.items()):
            if pid in pids:
                pids.discard(pid)
                if not pids:
                    self.listeners.pop(port, None)

    def send_signal(self, pid: int, signum: int) -> None:
        self.stop_pid(pid, signum)

    def sleep(self, seconds: float) -> None:
        self.clock += seconds

    def monotonic(self) -> float:
        return self.clock

    def fetch_json(
        self,
        url: str,
        headers: dict[str, str] | None,
        timeout: float,
    ) -> Any:
        path = urlsplit(url).path
        if path == "/api/health":
            return {"status": "ok"}
        if path == "/runtime-build.json":
            contract = json.loads(
                RUNTIME.RUNTIME_CONTRACT_PATH.read_text(encoding="utf-8")
            )
            payload = {
                "runtimeContractSchema": contract["schema_version"],
                "apiContractVersion": contract["api_contract_version"],
                "clientContractHeader": contract["client_contract_header"],
                "expectedBackendBuildId": BACKEND_BUILD_ID,
                "frontendBuildId": "web-fake1234567890",
            }
            payload.update(self.frontend_contract_override)
            return payload
        if path == "/api/runtime-readiness":
            contract = json.loads(
                RUNTIME.RUNTIME_CONTRACT_PATH.read_text(encoding="utf-8")
            )
            payload = {
                "ready": True,
                "runtime_contract_schema": contract["schema_version"],
                "api_contract_version": contract["api_contract_version"],
                "backend_build_id": BACKEND_BUILD_ID,
                "runtime_schema_version": BASELINE.EXPECTED_RUNTIME_SCHEMA_VERSION,
            }
            payload.update(self.readiness_override)
            return payload
        raise AssertionError(f"unexpected fake HTTP request: {url}")

    def verify_startup(self, **kwargs: Any) -> dict[str, Any]:
        self.verify_calls += 1
        if any(process.kind == "frontend" for process in self.processes):
            self.frontend_started_before_clean = True
        if self.fail_clean_verification:
            raise BASELINE.BaselineError("forced clean-state verification failure")
        output = Path(kwargs["output_path"])
        write_json(
            output,
            {
                "schema_version": BASELINE.RECEIPT_SCHEMA_VERSION,
                "status": "CLEAN_STATE_VERIFIED",
                "project_count": 0,
                "secret_content_embedded": False,
                "pass_created": False,
            },
        )
        output.chmod(0o600)
        self.clean_verified = True
        return {
            "status": "CLEAN_STATE_VERIFIED",
            "receipt": str(output),
            "project_count": 0,
        }

    def hooks(self) -> RUNTIME.Hooks:
        return RUNTIME.Hooks(
            popen=self.popen,
            fetch_json=self.fetch_json,
            listener_pids=self.listener_pids,
            process_identity=self.process_identity,
            send_signal=self.send_signal,
            sleep=self.sleep,
            monotonic=self.monotonic,
            baseline_prepare=BASELINE.prepare_baseline,
            baseline_verify_startup=self.verify_startup,
        )


def start_fake(
    tmp_path: Path,
    state: FakeRuntimeState | None = None,
    *,
    round_id: str = "round-01",
    slot: str = "A1",
    perspective: str = "lazy_medical_writer",
    backend_port: int | None = None,
    frontend_port: int | None = None,
) -> tuple[dict[str, Any], FakeRuntimeState, Path, Path, dict[str, bytes]]:
    run_root, run_dir = make_prepared_run(
        tmp_path,
        round_id=round_id,
        slot=slot,
        perspective=perspective,
    )
    source, secrets = make_source_runtime(tmp_path)
    node = make_fake_node(tmp_path)
    active_state = state or FakeRuntimeState()
    result = RUNTIME.start(
        round_id=round_id,
        slot=slot,
        perspective=perspective,
        backend_port=backend_port,
        frontend_port=frontend_port,
        run_root=run_root,
        test_run_root=run_root,
        source_runtime=source,
        test_source_root=tmp_path,
        test_target_root=tmp_path,
        xcode_python=tmp_path / "fake-xcode-python",
        node_path=node,
        hooks=active_state.hooks(),
        validate_python=False,
    )
    return result, active_state, run_root, run_dir, secrets


def test_start_orders_clean_gate_before_frontend_and_writes_secret_free_receipts(
    tmp_path: Path,
) -> None:
    result, state, _, run_dir, secrets = start_fake(tmp_path)

    assert result["status"] == "RUNNING"
    assert state.verify_calls == 1
    assert state.frontend_started_before_clean is False
    assert [process.kind for process in state.processes] == ["api", "frontend"]
    assert len(state.popen_kwargs) == 2
    assert all(
        call.get("start_new_session") is True for call in state.popen_kwargs
    )
    api_environment = state.processes[0].environment
    assert "PYTHONPATH" not in api_environment
    assert api_environment["WORKBENCH_RUNTIME_DIR"] == str(
        (run_dir / "runtime").resolve()
    )
    assert api_environment["WORKBENCH_INCLUDE_REFERENCE_PROJECTS"] == "false"

    clean_receipt = run_dir / RUNTIME.CLEAN_RECEIPT_NAME
    service_receipt = run_dir / RUNTIME.SERVICE_RECEIPT_NAME
    assert stat.S_IMODE(clean_receipt.stat().st_mode) == 0o600
    assert stat.S_IMODE(service_receipt.stat().st_mode) == 0o600
    assert not list(run_dir.glob(f".{RUNTIME.SERVICE_RECEIPT_NAME}.*.tmp"))
    receipt_text = service_receipt.read_text(encoding="utf-8")
    for secret in secrets.values():
        if secret:
            assert secret.decode("utf-8", errors="ignore") not in receipt_text
    receipt = json.loads(receipt_text)
    assert receipt["state"] == "RUNNING"
    assert receipt["runtime_identity"]["runtime_identity_sha256"] == result[
        "runtime_identity_sha256"
    ]
    assert receipt["processes"]["api"]["pid"] != receipt["processes"]["frontend"]["pid"]
    assert receipt["ports"]["backend"] != receipt["ports"]["frontend"]
    assert receipt["pass_created"] is False
    assert not list(run_dir.rglob("PASS.md"))


def test_status_and_stop_use_only_receipt_pids_and_release_ports(
    tmp_path: Path,
) -> None:
    _, state, run_root, _, _ = start_fake(tmp_path)
    current = RUNTIME.status(
        round_id="round-01",
        slot="A1",
        perspective="lazy_medical_writer",
        run_root=run_root,
        test_run_root=run_root,
        hooks=state.hooks(),
    )
    assert current["status"] == "RUNNING"

    stopped = RUNTIME.stop(
        round_id="round-01",
        slot="A1",
        perspective="lazy_medical_writer",
        run_root=run_root,
        test_run_root=run_root,
        hooks=state.hooks(),
        stop_timeout_seconds=1,
    )
    assert stopped["status"] == "STOPPED"
    assert set(stopped["stopped_pids"]) == {
        process.pid for process in state.processes
    }
    assert {pid for pid, _ in state.signals} == {
        process.pid for process in state.processes
    }
    assert not state.listeners

    again = RUNTIME.stop(
        round_id="round-01",
        slot="A1",
        perspective="lazy_medical_writer",
        run_root=run_root,
        test_run_root=run_root,
        hooks=state.hooks(),
    )
    assert again["status"] == "ALREADY_STOPPED"


def test_clean_gate_failure_never_starts_frontend_and_preserves_failed_run(
    tmp_path: Path,
) -> None:
    run_root, run_dir = make_prepared_run(tmp_path)
    source, _ = make_source_runtime(tmp_path)
    node = make_fake_node(tmp_path)
    state = FakeRuntimeState()
    state.fail_clean_verification = True

    with pytest.raises(BASELINE.BaselineError, match="forced clean-state"):
        RUNTIME.start(
            round_id="round-01",
            slot="A1",
            perspective="lazy_medical_writer",
            run_root=run_root,
            test_run_root=run_root,
            source_runtime=source,
            test_source_root=tmp_path,
            test_target_root=tmp_path,
            xcode_python=tmp_path / "fake-xcode-python",
            node_path=node,
            hooks=state.hooks(),
            validate_python=False,
        )

    assert [process.kind for process in state.processes] == ["api"]
    assert state.frontend_started_before_clean is False
    assert not state.alive[state.processes[0].pid]
    assert (run_dir / "runtime").is_dir()
    receipt = json.loads(
        (run_dir / RUNTIME.SERVICE_RECEIPT_NAME).read_text(encoding="utf-8")
    )
    assert receipt["state"] == "FAILED_STOPPED"
    assert receipt["failure"]["type"] == "BaselineError"
    assert not (run_dir / RUNTIME.CLEAN_RECEIPT_NAME).exists()

    with pytest.raises(RUNTIME.RuntimeOrchestratorError, match="receipt already exists"):
        RUNTIME.start(
            round_id="round-01",
            slot="A1",
            perspective="lazy_medical_writer",
            run_root=run_root,
            test_run_root=run_root,
            hooks=state.hooks(),
            validate_python=False,
        )


def test_contract_mismatch_stops_both_processes_without_pass(
    tmp_path: Path,
) -> None:
    run_root, run_dir = make_prepared_run(tmp_path)
    source, _ = make_source_runtime(tmp_path)
    node = make_fake_node(tmp_path)
    state = FakeRuntimeState()
    state.frontend_contract_override["apiContractVersion"] = "wrong-contract"

    with pytest.raises(RUNTIME.RuntimeOrchestratorError, match="runtime-build mismatch"):
        RUNTIME.start(
            round_id="round-01",
            slot="A1",
            perspective="lazy_medical_writer",
            run_root=run_root,
            test_run_root=run_root,
            source_runtime=source,
            test_source_root=tmp_path,
            test_target_root=tmp_path,
            xcode_python=tmp_path / "fake-xcode-python",
            node_path=node,
            hooks=state.hooks(),
            validate_python=False,
        )

    assert [process.kind for process in state.processes] == ["api", "frontend"]
    assert not any(state.alive.values())
    assert not state.listeners
    receipt = json.loads(
        (run_dir / RUNTIME.SERVICE_RECEIPT_NAME).read_text(encoding="utf-8")
    )
    assert receipt["state"] == "FAILED_STOPPED"
    assert not list(run_dir.rglob("PASS.md"))


@pytest.mark.parametrize("port", [5174, 8911])
def test_start_rejects_stable_product_ports_without_creating_runtime(
    tmp_path: Path,
    port: int,
) -> None:
    run_root, run_dir = make_prepared_run(tmp_path)
    with pytest.raises(RUNTIME.RuntimeOrchestratorError, match="stable product port"):
        RUNTIME.start(
            round_id="round-01",
            slot="A1",
            perspective="lazy_medical_writer",
            backend_port=port,
            frontend_port=24002,
            run_root=run_root,
            test_run_root=run_root,
            hooks=FakeRuntimeState().hooks(),
            validate_python=False,
        )
    assert not (run_dir / "runtime").exists()
    assert not (run_dir / RUNTIME.SERVICE_RECEIPT_NAME).exists()


def test_start_rejects_duplicate_and_occupied_ports(tmp_path: Path) -> None:
    run_root, run_dir = make_prepared_run(tmp_path)
    with pytest.raises(RUNTIME.RuntimeOrchestratorError, match="must be unique"):
        RUNTIME.start(
            round_id="round-01",
            slot="A1",
            perspective="lazy_medical_writer",
            backend_port=24001,
            frontend_port=24001,
            run_root=run_root,
            test_run_root=run_root,
            hooks=FakeRuntimeState().hooks(),
            validate_python=False,
        )

    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    try:
        port = int(occupied.getsockname()[1])
        with pytest.raises(RUNTIME.RuntimeOrchestratorError, match="unavailable"):
            RUNTIME.start(
                round_id="round-01",
                slot="A1",
                perspective="lazy_medical_writer",
                backend_port=port,
                frontend_port=0,
                run_root=run_root,
                test_run_root=run_root,
                hooks=FakeRuntimeState().hooks(),
                validate_python=False,
            )
    finally:
        occupied.close()
    assert not (run_dir / "runtime").exists()


def test_different_round_slot_and_ports_cannot_start_while_runtime_is_active(
    tmp_path: Path,
) -> None:
    run_root, _ = make_prepared_run(
        tmp_path,
        round_id="round-01",
        slot="A1",
        perspective="lazy_medical_writer",
    )
    _, second_run = make_prepared_run(
        tmp_path,
        round_id="round-02",
        slot="B2",
        perspective="engineer",
    )
    source, _ = make_source_runtime(tmp_path)
    node = make_fake_node(tmp_path)
    state = FakeRuntimeState()

    RUNTIME.start(
        round_id="round-01",
        slot="A1",
        perspective="lazy_medical_writer",
        backend_port=24011,
        frontend_port=24012,
        run_root=run_root,
        test_run_root=run_root,
        source_runtime=source,
        test_source_root=tmp_path,
        test_target_root=tmp_path,
        xcode_python=tmp_path / "fake-xcode-python",
        node_path=node,
        hooks=state.hooks(),
        validate_python=False,
    )
    process_count = len(state.processes)
    verify_calls = state.verify_calls

    with pytest.raises(
        RUNTIME.RuntimeOrchestratorError,
        match="another slot/perspective runtime is active; run stop first",
    ):
        RUNTIME.start(
            round_id="round-02",
            slot="B2",
            perspective="engineer",
            backend_port=24021,
            frontend_port=24022,
            run_root=run_root,
            test_run_root=run_root,
            source_runtime=source,
            test_source_root=tmp_path,
            test_target_root=tmp_path,
            xcode_python=tmp_path / "fake-xcode-python",
            node_path=node,
            hooks=state.hooks(),
            validate_python=False,
        )
    assert len(state.processes) == process_count
    assert state.verify_calls == verify_calls
    assert not (second_run / "runtime").exists()
    assert not (second_run / RUNTIME.SERVICE_RECEIPT_NAME).exists()


def test_second_runtime_is_allowed_after_first_runtime_is_stopped(
    tmp_path: Path,
) -> None:
    run_root, _ = make_prepared_run(tmp_path, round_id="round-01", slot="A1")
    _, second_run = make_prepared_run(
        tmp_path,
        round_id="round-02",
        slot="B2",
        perspective="engineer",
    )
    source, _ = make_source_runtime(tmp_path)
    node = make_fake_node(tmp_path)
    state = FakeRuntimeState()
    RUNTIME.start(
        round_id="round-01",
        slot="A1",
        perspective="lazy_medical_writer",
        backend_port=24031,
        frontend_port=24032,
        run_root=run_root,
        test_run_root=run_root,
        source_runtime=source,
        test_source_root=tmp_path,
        test_target_root=tmp_path,
        xcode_python=tmp_path / "fake-xcode-python",
        node_path=node,
        hooks=state.hooks(),
        validate_python=False,
    )
    RUNTIME.stop(
        round_id="round-01",
        slot="A1",
        perspective="lazy_medical_writer",
        run_root=run_root,
        test_run_root=run_root,
        hooks=state.hooks(),
        stop_timeout_seconds=1,
    )

    result = RUNTIME.start(
        round_id="round-02",
        slot="B2",
        perspective="engineer",
        backend_port=24041,
        frontend_port=24042,
        run_root=run_root,
        test_run_root=run_root,
        source_runtime=source,
        test_source_root=tmp_path,
        test_target_root=tmp_path,
        xcode_python=tmp_path / "fake-xcode-python",
        node_path=node,
        hooks=state.hooks(),
        validate_python=False,
    )

    assert result["status"] == "RUNNING"
    assert (second_run / "runtime").is_dir()
    assert len(state.processes) == 4


def test_failed_stopped_receipt_without_processes_or_listeners_does_not_block(
    tmp_path: Path,
) -> None:
    run_root, failed_run = make_prepared_run(
        tmp_path,
        round_id="round-01",
        slot="A1",
    )
    _, second_run = make_prepared_run(
        tmp_path,
        round_id="round-02",
        slot="B2",
        perspective="engineer",
    )
    write_json(
        failed_run / RUNTIME.SERVICE_RECEIPT_NAME,
        {
            "schema_version": RUNTIME.RECEIPT_SCHEMA_VERSION,
            "state": "FAILED_STOPPED",
            "ports": {"backend": 24043, "frontend": 24044},
            "processes": {"api": None, "frontend": None},
        },
    )
    source, _ = make_source_runtime(tmp_path)
    node = make_fake_node(tmp_path)
    state = FakeRuntimeState()

    result = RUNTIME.start(
        round_id="round-02",
        slot="B2",
        perspective="engineer",
        backend_port=24045,
        frontend_port=24046,
        run_root=run_root,
        test_run_root=run_root,
        source_runtime=source,
        test_source_root=tmp_path,
        test_target_root=tmp_path,
        xcode_python=tmp_path / "fake-xcode-python",
        node_path=node,
        hooks=state.hooks(),
        validate_python=False,
    )

    assert result["status"] == "RUNNING"
    assert (second_run / "runtime").is_dir()


def test_stale_active_receipt_requires_proof_of_termination(
    tmp_path: Path,
) -> None:
    run_root, stale_run = make_prepared_run(
        tmp_path,
        round_id="round-01",
        slot="A1",
    )
    _, second_run = make_prepared_run(
        tmp_path,
        round_id="round-02",
        slot="B2",
        perspective="engineer",
    )
    write_json(
        stale_run / RUNTIME.SERVICE_RECEIPT_NAME,
        {
            "schema_version": RUNTIME.RECEIPT_SCHEMA_VERSION,
            "state": "RUNNING",
            "ports": {"backend": 24051, "frontend": 24052},
            "processes": {"api": None, "frontend": None},
        },
    )
    state = FakeRuntimeState()

    with pytest.raises(
        RUNTIME.RuntimeOrchestratorError,
        match="cannot be proven stopped; run stop first",
    ):
        RUNTIME.start(
            round_id="round-02",
            slot="B2",
            perspective="engineer",
            backend_port=24061,
            frontend_port=24062,
            run_root=run_root,
            test_run_root=run_root,
            hooks=state.hooks(),
            validate_python=False,
        )

    assert state.processes == []
    assert not (second_run / "runtime").exists()


def test_stale_active_receipt_with_absent_recorded_processes_does_not_block(
    tmp_path: Path,
) -> None:
    run_root, _ = make_prepared_run(tmp_path, round_id="round-01", slot="A1")
    _, second_run = make_prepared_run(
        tmp_path,
        round_id="round-02",
        slot="B2",
        perspective="engineer",
    )
    source, _ = make_source_runtime(tmp_path)
    node = make_fake_node(tmp_path)
    state = FakeRuntimeState()
    RUNTIME.start(
        round_id="round-01",
        slot="A1",
        perspective="lazy_medical_writer",
        backend_port=24071,
        frontend_port=24072,
        run_root=run_root,
        test_run_root=run_root,
        source_runtime=source,
        test_source_root=tmp_path,
        test_target_root=tmp_path,
        xcode_python=tmp_path / "fake-xcode-python",
        node_path=node,
        hooks=state.hooks(),
        validate_python=False,
    )
    for process in list(state.processes):
        state.stop_pid(process.pid, signal.SIGKILL)

    result = RUNTIME.start(
        round_id="round-02",
        slot="B2",
        perspective="engineer",
        backend_port=24081,
        frontend_port=24082,
        run_root=run_root,
        test_run_root=run_root,
        source_runtime=source,
        test_source_root=tmp_path,
        test_target_root=tmp_path,
        xcode_python=tmp_path / "fake-xcode-python",
        node_path=node,
        hooks=state.hooks(),
        validate_python=False,
    )

    assert result["status"] == "RUNNING"
    assert (second_run / "runtime").is_dir()


def test_run_path_rejects_symlink_adjacent_prefix_shared_and_invalid_identity(
    tmp_path: Path,
) -> None:
    run_root, _ = make_prepared_run(tmp_path)
    symlink_root = tmp_path / "run-link"
    symlink_root.symlink_to(run_root, target_is_directory=True)
    with pytest.raises(RUNTIME.RuntimeOrchestratorError, match="symbolic links"):
        RUNTIME._resolve_run_context(
            round_id="round-01",
            slot="A1",
            perspective="lazy_medical_writer",
            run_root=symlink_root,
            test_run_root=symlink_root,
        )

    adjacent = tmp_path / f"{run_root.name}-evil"
    adjacent.mkdir()
    with pytest.raises(RUNTIME.RuntimeOrchestratorError, match="must equal"):
        RUNTIME._resolve_run_context(
            round_id="round-01",
            slot="A1",
            perspective="lazy_medical_writer",
            run_root=adjacent,
            test_run_root=run_root,
        )

    with pytest.raises(RUNTIME.RuntimeOrchestratorError, match="locked root"):
        RUNTIME._resolve_run_root(RUNTIME.SHARED_RUNTIME)
    with pytest.raises(RUNTIME.RuntimeOrchestratorError, match="locked matrix"):
        RUNTIME._resolve_run_context(
            round_id="round-01",
            slot="Z9",
            perspective="lazy_medical_writer",
            run_root=run_root,
            test_run_root=run_root,
        )


def test_orchestration_lock_rejects_symbolic_link(tmp_path: Path) -> None:
    run_root, _ = make_prepared_run(tmp_path)
    target = tmp_path / "lock-target"
    target.write_text("", encoding="utf-8")
    (run_root / RUNTIME.LOCK_NAME).symlink_to(target)
    with pytest.raises(
        RUNTIME.RuntimeOrchestratorError,
        match="lock cannot be a symbolic link",
    ):
        with RUNTIME._root_lock(run_root):
            pytest.fail("symlink lock must not be acquired")


def test_stop_refuses_pid_reuse_before_signaling_any_process(
    tmp_path: Path,
) -> None:
    _, state, run_root, _, _ = start_fake(tmp_path)
    api = next(process for process in state.processes if process.kind == "api")
    state.identities[api.pid] = {
        "start_marker": "reused-pid",
        "command_sha256": "0" * 64,
    }
    state.signals.clear()

    with pytest.raises(RUNTIME.RuntimeOrchestratorError, match="identity changed"):
        RUNTIME.stop(
            round_id="round-01",
            slot="A1",
            perspective="lazy_medical_writer",
            run_root=run_root,
            test_run_root=run_root,
            hooks=state.hooks(),
        )
    assert state.signals == []
    assert all(state.alive.values())


def test_stop_refuses_unrelated_listener_before_signaling(
    tmp_path: Path,
) -> None:
    _, state, run_root, run_dir, _ = start_fake(tmp_path)
    receipt = json.loads(
        (run_dir / RUNTIME.SERVICE_RECEIPT_NAME).read_text(encoding="utf-8")
    )
    frontend_port = receipt["ports"]["frontend"]
    state.listeners[frontend_port].add(99999)
    state.signals.clear()

    with pytest.raises(RUNTIME.RuntimeOrchestratorError, match="not owned exclusively"):
        RUNTIME.stop(
            round_id="round-01",
            slot="A1",
            perspective="lazy_medical_writer",
            run_root=run_root,
            test_run_root=run_root,
            hooks=state.hooks(),
        )
    assert state.signals == []


def test_status_reports_degraded_without_mutating_receipt(tmp_path: Path) -> None:
    _, state, run_root, run_dir, _ = start_fake(tmp_path)
    frontend = next(
        process for process in state.processes if process.kind == "frontend"
    )
    state.stop_pid(frontend.pid, signal.SIGTERM)
    receipt_path = run_dir / RUNTIME.SERVICE_RECEIPT_NAME
    before = receipt_path.read_bytes()
    observed = RUNTIME.status(
        round_id="round-01",
        slot="A1",
        perspective="lazy_medical_writer",
        run_root=run_root,
        test_run_root=run_root,
        hooks=state.hooks(),
    )
    assert observed["status"] == "DEGRADED"
    assert receipt_path.read_bytes() == before


def test_xcode_python_is_locked_to_3_9_and_pythonpath_is_not_required() -> None:
    resolved = RUNTIME._validate_xcode_python(RUNTIME.XCODE_PYTHON)
    assert resolved == RUNTIME.XCODE_PYTHON
    assert resolved.is_file()


def test_cli_failure_is_json_and_does_not_create_pass(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root, run_dir = make_prepared_run(tmp_path)
    monkeypatch.setattr(RUNTIME, "ALLOWED_RUN_ROOT", run_root)
    result = RUNTIME.main(
        [
            "start",
            "--round-id",
            "round-01",
            "--slot",
            "A1",
            "--perspective",
            "lazy_medical_writer",
            "--backend-port",
            "5174",
        ]
    )
    assert result == 2
    payload = json.loads(capsys.readouterr().err)
    assert payload["status"] == "FAILED"
    assert not list(run_dir.rglob("PASS.md"))
