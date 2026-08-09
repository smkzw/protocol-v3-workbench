#!/usr/bin/env python3
"""Download all confirmed obesity protocol PDFs, compute SHA-256 and page counts."""
from __future__ import annotations
import json, os, re, hashlib, urllib.request, urllib.error, time

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) hermes-worker03/1.0"
BASE = "runs/execution/mw_protocol_structure_corpus_exec_20260719/worker_03_scan"
OUT = os.path.join(BASE, "downloads")
os.makedirs(OUT, exist_ok=True)

PAGE_RE = re.compile(rb"/Type\s*/Page(?![s])")

results = []
for phase in ["phase2", "phase3"]:
    with open(os.path.join(BASE, f"{phase}_confirmed.json")) as f:
        conf = json.load(f)
    for c in conf:
        nct = c["nct"]
        url = c["prot_dl_url"]
        path = os.path.join(OUT, f"{nct}_Prot.pdf")
        rec = {"nct": nct, "sponsor": c["sponsor"], "phase_bucket": phase,
               "url": url, "expected_size": c.get("prot_head_size")}
        if os.path.exists(path) and os.path.getsize(path) == c.get("prot_head_size"):
            with open(path, "rb") as f:
                data = f.read()
            rec["bytes"] = len(data)
            rec["sha256"] = hashlib.sha256(data).hexdigest()
            rec["pages"] = len(PAGE_RE.findall(data))
            rec["download_status"] = "cached"
            results.append(rec)
            print(f"  cached {nct} {c['sponsor'][:30]:32s} bytes={rec['bytes']} pages={rec['pages']}", flush=True)
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            with open(path, "wb") as f:
                f.write(data)
            rec["bytes"] = len(data)
            rec["sha256"] = hashlib.sha256(data).hexdigest()
            rec["pages"] = len(PAGE_RE.findall(data))
            rec["download_status"] = "ok"
            results.append(rec)
            print(f"  dl     {nct} {c['sponsor'][:30]:32s} bytes={rec['bytes']} pages={rec['pages']}", flush=True)
        except urllib.error.HTTPError as e:
            rec["download_status"] = f"HTTP {e.code}"
            print(f"  FAIL   {nct}: HTTP {e.code}", flush=True)
        except Exception as e:
            rec["download_status"] = f"ERR {type(e).__name__}"
            print(f"  FAIL   {nct}: {type(e).__name__} {str(e)[:60]}", flush=True)
        time.sleep(0.3)

with open(os.path.join(BASE, "downloads_manifest.json"), "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\nTotal downloaded/hashed: {len(results)} -> {os.path.join(BASE, 'downloads_manifest.json')}", flush=True)
