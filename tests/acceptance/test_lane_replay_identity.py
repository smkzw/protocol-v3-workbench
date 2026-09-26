"""REPLAY lane identity counterexamples (0927V1 three-lane plan; A14/A15).

- A14: a healthy service whose build id matches the tree is REUSED; nothing
  is killed (neither the reused service nor any other listener).
- A15: the same port answering with a different build id is refused as an
  impostor; the lane starts its OWN instance (private runtime, own port) and
  never touches the existing listener.

The identity functions live in the gate module; the spawn step is injectable
so tests stay offline and never launch the real app. The default spawn (used
by --plan replay in production) launches the real backend on a private port.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.acceptance import _gate_testkit as kit


class _IdentityServer:
    """Minimal stand-in for /api/runtime-readiness on an ephemeral port."""

    def __init__(self, build_id: str):
        self.build_id = build_id
        self.port: int | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> "_IdentityServer":
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                payload = json.dumps({
                    "backend_build_id": outer.build_id,
                    "runtime_dir_marker": outer.build_id,
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):  # silence
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def alive(self) -> bool:
        import urllib.request
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/api/runtime-readiness",
                    timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def test_a14_healthy_same_source_service_reused_and_not_killed():
    gate = kit.load_gate_module()
    good = _IdentityServer("api-goodbuild").start()
    bystander = _IdentityServer("api-whatever").start()
    try:
        probe = gate.probe_service_identity(
            f"http://127.0.0.1:{good.port}", expected_build_id="api-goodbuild")
        assert probe["identity_ok"] is True, probe
        decision = gate.ensure_replay_service(
            root=None, expected_build_id="api-goodbuild",
            preferred_port=good.port)
        assert decision["reused"] is True, decision
        assert decision["port"] == good.port, decision
        # reuse never kills: the reused service AND the bystander still answer
        assert good.alive(), "reused service was killed"
        assert bystander.alive(), "an unrelated listener was killed"
    finally:
        good.stop()
        bystander.stop()


def test_a15_same_port_different_source_refused_own_instance_started():
    gate = kit.load_gate_module()
    impostor = _IdentityServer("api-OTHER-SOURCE").start()
    try:
        def own_spawn(runtime_dir):
            own = _IdentityServer("api-goodbuild").start()
            return own.port, own.stop, {"kind": "injected"}

        decision = gate.ensure_replay_service(
            root=None, expected_build_id="api-goodbuild",
            preferred_port=impostor.port, spawn=own_spawn)
        assert decision["reused"] is False, decision
        assert any("build_id" in reason or "identity" in reason
                   for reason in decision["refusal_reasons"]), decision
        assert decision["port"] != impostor.port, decision
        assert decision["identity_ok"] is True, decision
        assert decision["runtime_dir"], decision
        # the impostor listener was never touched
        assert impostor.alive(), "existing listener was killed"
    finally:
        impostor.stop()
