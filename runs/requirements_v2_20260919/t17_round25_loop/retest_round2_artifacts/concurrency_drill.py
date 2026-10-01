"""round25 真实并发压测：翻译/分诊双负载经 5301 产品入口（/api/ai-gateway/probe）。

- 负载甲: 循环 probe profile=translation_body_local_omlx (oMLX 8001, translation 相位)
- 负载乙: 循环 probe profile=independent_ai__mtplx_qwen38_local (MTPLX 8002, triage 相位)
- 两负载各自串行循环，持续 600s；探针为产品探测入口（返回单个小 JSON 对象；
  生命周期内部探针由 config probe_max_tokens=8 硬上限约束）。
- 采样线程每 5s 记录: 8001 /admin/api/models 中 loaded=true 的模型集合，
  8002 端口存活。两者同时有模型驻留 => 双载样本。
- 全部请求/样本写 JSONL；汇总写 stdout。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:5301"
PROFILES = {
    "translation": "translation_body_local_omlx",
    "triage": "independent_ai__mtplx_qwen38_local",
}
DURATION_S = 600.0
SAMPLE_INTERVAL_S = 5.0
REQUEST_TIMEOUT_S = 900.0  # 排队等待本身不算错误，客户端耐心等

stop_at = time.monotonic() + DURATION_S
lock = threading.Lock()
results = []


def record(kind: str, **kw) -> None:
    entry = {"kind": kind, "ts": datetime.now().isoformat(timespec="milliseconds"), **kw}
    with lock:
        results.append(entry)


def probe_once(phase: str) -> None:
    profile = PROFILES[phase]
    body = json.dumps({"profile_id": profile}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/ai-gateway/probe", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.monotonic()
    status, detail = None, None
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            status = resp.status
            detail = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            detail = json.loads(exc.read().decode("utf-8"))
        except Exception:
            detail = {"detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        status = -1
        detail = {"detail": f"{type(exc).__name__}: {exc}"}
    elapsed = time.monotonic() - t0
    record("request", phase=phase, status=status, elapsed_s=round(elapsed, 3),
           passed=(isinstance(detail, dict) and detail.get("passed")) or None,
           failure=(detail.get("detail") if isinstance(detail, dict) and status != 200 else None))


def sample_arbiter() -> None:
    try:
        with urllib.request.urlopen(f"{BASE}/api/model-lifecycle/status", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        arb = d.get("arbiter") or {}
        record("arbiter", current=arb.get("current"), users=arb.get("users"),
               queue=arb.get("queue"))
    except Exception as exc:  # noqa: BLE001
        record("arbiter", error=f"{type(exc).__name__}: {exc}")


def sample_once() -> None:
    sample_arbiter()
    omlx_loaded: list[str] = []
    omlx_ok = False
    mtplx_up = False
    try:
        with urllib.request.urlopen("http://127.0.0.1:8001/admin/api/models", timeout=10) as r:
            models = json.loads(r.read().decode("utf-8")).get("models", [])
        omlx_ok = True
        omlx_loaded = [m.get("id") for m in models if m.get("loaded")]
    except Exception:
        omlx_ok = False
    try:
        with urllib.request.urlopen("http://127.0.0.1:8002/v1/models", timeout=5) as r:
            mtplx_up = r.status == 200
    except Exception:
        mtplx_up = False
    record("sample", omlx_up=omlx_ok, omlx_loaded=omlx_loaded, mtplx_up=mtplx_up,
           co_resident=bool(omlx_loaded) and mtplx_up)


def load_loop(phase: str) -> None:
    n = 0
    while time.monotonic() < stop_at:
        probe_once(phase)
        n += 1
    record("load_done", phase=phase, iterations=n)


def sampler_loop() -> None:
    while time.monotonic() < stop_at:
        sample_once()
        time.sleep(SAMPLE_INTERVAL_S)
    sample_once()


def main() -> int:
    print(f"drill start {datetime.now().isoformat()} duration={DURATION_S}s", flush=True)
    threads = [threading.Thread(target=load_loop, args=("translation",), name="load-A"),
               threading.Thread(target=load_loop, args=("triage",), name="load-B"),
               threading.Thread(target=sampler_loop, name="sampler")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out_file = OUT / "concurrency_drill_events.jsonl"
    with lock:
        with open(out_file, "w", encoding="utf-8") as fh:
            for e in results:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        reqs = [e for e in results if e["kind"] == "request"]
        samples = [e for e in results if e["kind"] == "sample"]
    summary = {
        "total_requests": len(reqs),
        "by_phase": {},
        "co_resident_samples": sum(1 for s in samples if s.get("co_resident")),
        "samples": len(samples),
    }
    for phase in PROFILES:
        rs = [r for r in reqs if r["phase"] == phase]
        ok = [r for r in rs if r["status"] == 200 and r.get("passed")]
        bad = [r for r in rs if not (r["status"] == 200 and r.get("passed"))]
        summary["by_phase"][phase] = {
            "count": len(rs), "ok": len(ok), "non_ok": len(bad),
            "max_elapsed_s": max((r["elapsed_s"] for r in rs), default=0.0),
            "min_elapsed_s": min((r["elapsed_s"] for r in rs), default=0.0),
            "errors": [{"status": r["status"], "detail": r.get("failure")} for r in bad[:10]],
        }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    (OUT / "concurrency_drill_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"events -> {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
