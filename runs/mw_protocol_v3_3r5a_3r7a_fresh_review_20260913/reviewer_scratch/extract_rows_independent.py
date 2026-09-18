# Independent extraction of SOP QC table rows (no project code used)
import re, json
from xml.etree import ElementTree as ET

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = NS["w"]
tree = ET.parse("r03_src/word/document.xml")
body = tree.getroot().find(f"{{{W}}}body")

def cell_text(tc):
    parts = []
    for p in tc.iter(f"{{{W}}}p"):
        runs = []
        for r in p.iter(f"{{{W}}}r"):
            for t in r.iter(f"{{{W}}}t"):
                runs.append(t.text or "")
            if r.find(f"{{{W}}}tab") is not None:
                runs.append("\t")
            for br in r.iter(f"{{{W}}}br"):
                runs.append("\n")
        parts.append("".join(runs))
    return "\n".join(parts)

tables = body.findall(f"{{{W}}}tbl")
print("tables:", len(tables))
rows_total = 0
report = []
for ti, tbl in enumerate(tables, 1):
    trs = tbl.findall(f"{{{W}}}tr")
    rows_total += len(trs)
    tinfo = {"table": ti, "rows": len(trs), "row_detail": []}
    for ri, tr in enumerate(trs):
        tcs = tr.findall(f"{{{W}}}tc")
        texts = [cell_text(tc) for tc in tcs]
        gridspan = []
        for tc in tcs:
            gs = tc.find(f"{{{W}}}tcPr/{{{W}}}gridSpan")
            gridspan.append(int(gs.get(f"{{{W}}}val")) if gs is not None else 1)
        vmerge = []
        for tc in tcs:
            vm = tc.find(f"{{{W}}}tcPr/{{{W}}}vMerge")
            if vm is None: vmerge.append("")
            else: vmerge.append(vm.get(f"{{{W}}}val") or "cont")
        tinfo["row_detail"].append({"ri": ri, "cells": len(tcs), "spans": gridspan, "vmerge": vmerge, "texts": texts})
    report.append(tinfo)
print("physical rows:", rows_total)
json.dump(report, open("independent_rows.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for t in report:
    first = " | ".join(c.replace("\n","⏎")[:30] for c in (t["row_detail"][0]["texts"] if t["row_detail"] else []))
    print(f"T{t['table']}: {t['rows']} rows  first_row: {first[:110]}")
