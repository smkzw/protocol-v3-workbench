"""Cap-safe gate runner (20261008): world.run 单流 256KB 上限的根治。

用法: python3 gate_runner_capped.py <log_path> <pythonpath> <cmd> [args...]
- 以 PYTHONPATH=<pythonpath> 运行 <cmd>，完整 stdout+stderr 写入 log_path；
- 只向 stdout 回传摘要（EXIT_CODE=... LINES=... LOG=... + 末120行），
  供工作流脚本解析；自身恒 exit 0（真实退出码在 EXIT_CODE 行里）。
"""
import os
import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 4:
        print("EXIT_CODE=2 LINES=0 LOG= usage: gate_runner_capped.py <log> <pythonpath> <cmd> [args...]")
        return 0
    log_path, pythonpath, argv = sys.argv[1], sys.argv[2], sys.argv[3:]
    env = dict(os.environ)
    env["PYTHONPATH"] = pythonpath
    proc = subprocess.run(argv, capture_output=True, text=True, env=env)
    out = (proc.stdout or "") + (proc.stderr or "")
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8", errors="ignore") as fh:
            fh.write(out)
    except OSError:
        pass
    lines = out.splitlines()
    print("EXIT_CODE=%d LINES=%d LOG=%s" % (proc.returncode, len(lines), log_path))
    print("\n".join(lines[-120:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
