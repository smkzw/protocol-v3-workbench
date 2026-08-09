#!/usr/bin/env python3
"""Use pypdf to get accurate page counts and confirm document role for each obesity protocol PDF."""
from __future__ import annotations
import os, json, re, sys
import pypdf

BASE = "runs/execution/mw_protocol_structure_corpus_exec_20260719/worker_03_scan"
DL = os.path.join(BASE, "downloads")

def analyze(path):
    try:
        r = pypdf.PdfReader(path)
    except Exception as e:
        return {"pages": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}
    info = {
        "pages": len(r.pages),
        "metadata": {k: str(v)[:200] for k, v in (r.metadata or {}).items()} if r.metadata else {},
        "encrypted": r.is_encrypted,
    }
    # Extract text from first 2 pages to confirm role (Protocol vs SAP vs ICF)
    text_bits = []
    for i in range(min(2, len(r.pages))):
        try:
            t = r.pages[i].extract_text() or ""
            text_bits.append(t)
        except Exception as e:
            text_bits.append(f"[extract err: {type(e).__name__}]")
    sample = "\n".join(text_bits)[:1500]
    info["first_pages_sample"] = sample
    low = sample.lower()
    role_signals = {
        "protocol": ("study protocol" in low) or ("protocol " in low and "version" in low) or ("protocol no" in low),
        "sap": "statistical analysis plan" in low,
        "icf": "informed consent" in low and "subject" in low,
        "amendment": "amendment" in low and ("protocol" in low),
    }
    info["role_signals"] = role_signals
    # Detect protocol version date on first 2 pages
    m = re.search(r"(?:Protocol\s+(?:amendment\s+)?(?:version|v))\s*[:\-]?\s*(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})", low)
    info["protocol_version_in_text"] = m.group(1) if m else None
    return info

with open(os.path.join(BASE, "downloads_manifest.json")) as f:
    manifest = json.load(f)

enriched = []
for rec in manifest:
    nct = rec["nct"]
    path = os.path.join(DL, f"{nct}_Prot.pdf")
    if not os.path.exists(path):
        rec["analyze_error"] = "file missing"
        enriched.append(rec)
        continue
    a = analyze(path)
    rec.update(a)
    role = "UNKNOWN"
    if a.get("role_signals", {}).get("sap") and not a.get("role_signals", {}).get("protocol"):
        role = "SAP (mismatch - flagged)"
    elif a.get("role_signals", {}).get("protocol"):
        role = "Original Study Protocol"
    elif a.get("role_signals", {}).get("icf"):
        role = "ICF (mismatch - flagged)"
    rec["inferred_role"] = role
    print(f"  {nct} pages={a.get('pages')} role={role} ver={a.get('protocol_version_in_text')}", flush=True)
    enriched.append(rec)

with open(os.path.join(BASE, "downloads_manifest_enriched.json"), "w") as f:
    json.dump(enriched, f, indent=2, ensure_ascii=False)
print(f"\nEnriched manifest written: {os.path.join(BASE, 'downloads_manifest_enriched.json')}", flush=True)
