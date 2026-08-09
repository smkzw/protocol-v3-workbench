#!/usr/bin/env python3
import os, json, re
import pypdf
BASE = "runs/execution/mw_protocol_structure_corpus_exec_20260719/worker_03_scan"
DL = os.path.join(BASE, "downloads")
with open(os.path.join(BASE, "phase3_supplement_manifest.json")) as f:
    mani = json.load(f)
for rec in mani:
    nct = rec["nct"]
    path = os.path.join(DL, f"{nct}_Prot.pdf")
    r = pypdf.PdfReader(path)
    pages = len(r.pages)
    rec["pages_pypdf"] = pages
    text = ""
    for i in range(min(2, pages)):
        try:
            text += (r.pages[i].extract_text() or "") + "\n"
        except Exception:
            pass
    rec["first_pages_sample"] = text[:600]
    print(f"{nct}: pages(pypdf)={pages}  sample={text[:200].replace(chr(10),' | ')}")
with open(os.path.join(BASE, "phase3_supplement_manifest.json"),"w") as f:
    json.dump(mani, f, indent=2, ensure_ascii=False)
