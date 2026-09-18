"""Diagnostic main import in a fresh child; never starts ASGI lifespan.

Not a product acceptance test. Audit rejects writes outside disposable runtime,
external processes and network connections. Runtime is retained for inspection.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path(tempfile.mkdtemp(prefix="main-import-", dir=Path(__file__).parent))
CHILD = r"""
import json, os, sys
from pathlib import Path
runtime = Path(os.environ["WORKBENCH_RUNTIME_DIR"]).resolve()
def inside(path):
    if isinstance(path, int):
        return True
    target = Path(os.fsdecode(path)).resolve()
    return target == runtime or runtime in target.parents
def audit(event, args):
    if event in {"socket.connect", "socket.bind", "subprocess.Popen", "os.system", "os.posix_spawn"}:
        raise PermissionError("isolation denied: " + event)
    if event == "sqlite3.connect" and str(args[0]) != ":memory:" and not inside(args[0]):
        raise PermissionError("isolation denied: SQLite outside test runtime")
    if event == "open":
        path, mode, flags = args
        writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        if writing and not inside(path):
            raise PermissionError("isolation denied: write outside test runtime")
        if not isinstance(path, int):
            parts = Path(os.fsdecode(path)).parts
            if any(p in {".codex", ".hermes", ".omp", ".pi", ".config"} for p in parts):
                raise PermissionError("isolation denied: private configuration read")
    if event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.truncate"}:
        if not inside(args[0]):
            raise PermissionError("isolation denied: filesystem mutation")
    if event in {"os.rename", "os.link", "os.symlink"}:
        if not all(inside(p) for p in args[:2]):
            raise PermissionError("isolation denied: filesystem relocation")
sys.addaudithook(audit)
import app.main as main
assert main.RUNTIME_DIR == runtime
print(json.dumps({"import": "passed", "runtime": str(runtime),
                  "routes": len(main.app.routes), "lifespan_started": False}))
"""
env = {k: v for k, v in os.environ.items()
       if k in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT"}}
env.update(
    PYTHONPATH=f"{ROOT / 'services/api'}:{ROOT / 'packages'}:{ROOT}",
    PYTHONDONTWRITEBYTECODE="1",
    PYTHONNOUSERSITE="1",
    WORKBENCH_RUNTIME_DIR=str(RUNTIME),
    WORKBENCH_AI_SETTINGS_PATH=str(RUNTIME / "ai-settings.json"),
    WORKBENCH_AI_ROLE_SETTINGS_PATH=str(RUNTIME / "role-settings.json"),
    WORKBENCH_ELIGIBILITY_ARTIFACT_DIR=str(RUNTIME / "eligibility"),
    WORKBENCH_INCLUDE_REFERENCE_PROJECTS="false",
)
result = subprocess.run([sys.executable, "-c", CHILD], cwd=ROOT, env=env,
                        capture_output=True, text=True, timeout=60)
print(json.dumps({"returncode": result.returncode, "runtime": str(RUNTIME),
                  "stdout": result.stdout, "stderr": result.stderr}, ensure_ascii=False))
sys.exit(result.returncode)
