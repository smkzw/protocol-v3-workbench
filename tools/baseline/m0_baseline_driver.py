"""M0-3 基线驱动器（reboot包 20261017）：对3个dev项目各触发一次全文初稿并记录指标。

用法：PYTHONPATH=services/api:. python3 tools/baseline/m0_baseline_driver.py
输出：eval/reports/baseline_m0/baseline_report.md + 每项目 job 状态 JSON。
项目选择（领域分散、均处writing阶段=语料门已过+设计已确认）：
  A=proj_user_66e969133cc8（芦可替尼乳膏/AD/III期/外用——真实基准项目）
  B=proj_user_30ddc897be83（PMO-KZ301/绝经后骨质疏松/III期/注射——合成场景）
  C=proj_user_bea8fdc28bdc（KZ-SUI701/压力性尿失禁/口服——合成场景）
"""
import json, time, urllib.request, urllib.error, sys, os

BASE = "http://127.0.0.1:5301"
PROJECTS = [
    ("A-rux-ad", "proj_user_66e969133cc8"),
    ("B-pmo", "proj_user_30ddc897be83"),
    ("C-sui", "proj_user_bea8fdc28bdc"),
]
OUT = os.path.join(os.path.dirname(__file__), "..", "..", "eval", "reports", "baseline_m0")


def api(method, path, payload=None, timeout=60):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(payload).encode() if payload else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            return r.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def trigger_full_draft(pid):
    key = f"m0-baseline-{pid}-{int(time.time())}"
    return api("POST", f"/api/projects/{pid}/medical-writing/full-drafts",
               {"actor": "medical_manager", "idempotency_key": key}, timeout=120)


def poll_job(pid, job_id, budget_s=4*3600):
    t0 = time.time()
    while time.time() - t0 < budget_s:
        st, body = api("GET", f"/api/projects/{pid}/medical-writing/full-drafts/{job_id}", timeout=30)
        if st == 200:
            status = body.get("status")
            if status in ("completed", "failed", "cancelled"):
                return body, time.time() - t0
        elif st == 404:
            # 某些版本状态在durable jobs
            st2, body2 = api("GET", f"/api/jobs/{job_id}", timeout=30)
            if st2 == 200 and body2.get("status") in ("completed", "failed", "cancelled"):
                return body2, time.time() - t0
        time.sleep(60)
    return {"status": "poll_timeout"}, time.time() - t0


def summarize(tag, pid, job, elapsed):
    cov = job.get("coverage") or {}
    rep = {
        "tag": tag, "project_id": pid, "job_status": job.get("status"),
        "elapsed_s": round(elapsed),
        "generated": cov.get("generated_count"), "partial": cov.get("partial_count"),
        "skipped": cov.get("skipped_count"), "required_review": cov.get("required_review_count"),
    }
    return rep


def main():
    os.makedirs(OUT, exist_ok=True)
    results = []
    for tag, pid in PROJECTS:
        print(f"[{tag}] 触发全文初稿 {pid}", flush=True)
        st, resp = trigger_full_draft(pid)
        print(f"[{tag}] 触发返回 {st}: {json.dumps(resp)[:200]}", flush=True)
        if st not in (200, 201, 202):
            results.append({"tag": tag, "project_id": pid, "error": f"trigger {st}: {str(resp)[:200]}"})
            continue
        job_id = resp.get("job_id") or resp.get("id") or ""
        job, elapsed = poll_job(pid, job_id)
        rep = summarize(tag, pid, job, elapsed)
        results.append(rep)
        print(f"[{tag}] 终态 {rep}", flush=True)
    with open(os.path.join(OUT, "baseline_raw.json"), "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("BASELINE_DONE")


if __name__ == "__main__":
    main()
