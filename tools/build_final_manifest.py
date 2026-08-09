#!/usr/bin/env python3
"""Consolidate all confirmed obesity/overweight protocol candidates into a single final manifest."""
from __future__ import annotations
import json, os, re, csv

BASE = "runs/execution/mw_protocol_structure_corpus_exec_20260719/worker_03_scan"

with open(os.path.join(BASE, "phase2_confirmed.json")) as f:
    ph2 = json.load(f)
with open(os.path.join(BASE, "phase3_confirmed.json")) as f:
    ph3 = json.load(f)
with open(os.path.join(BASE, "phase3_confirmed_supplement.json")) as f:
    ph3_supp = json.load(f)
with open(os.path.join(BASE, "downloads_manifest_enriched.json")) as f:
    mani_main = {r["nct"]: r for r in json.load(f)}
with open(os.path.join(BASE, "phase3_supplement_manifest.json")) as f:
    mani_supp = {r["nct"]: r for r in json.load(f)}


def analyze_notes(official_title, conditions, interventions_str, first_pages_sample):
    notes = []
    low = (official_title or "").lower()
    cond_low = " ".join(conditions).lower()
    iv_low = (interventions_str or "").lower()
    sample_low = (first_pages_sample or "").lower()
    blob = " ".join([low, cond_low, iv_low, sample_low])

    rare_kw = {
        "Prader-Willi syndrome": ["prader-willi", "prader willi"],
        "POMC/PCSK1/LEPR/MC4R genetic obesity": ["pomc", "pcsk1", "lepr", "mc4r", "pro-opiomelanocortin", "melanocortin 4 receptor"],
        "Bardet-Biedl syndrome": ["bardet-biedl", "bardet biedl"],
    }
    for label, kws in rare_kw.items():
        if any(k in blob for k in kws):
            notes.append(f"Rare/syndromic obesity population: {label}")
    if any(k in blob for k in ["steatohepatitis", "nash "]) or ("non-alcoholic steatohepatitis" in blob.replace("-", " ")):
        notes.append("Primary indication is NASH; obesity/overweight is an inclusion criterion or comorbidity, not the primary indication")
    # T2D: only flag if T2D is a PRIMARY condition (not just an exclusion criterion mention)
    if "type 2 diabetes" in cond_low or "type 2 diabetes mellitus" in cond_low:
        notes.append("Type 2 Diabetes Mellitus is a registered primary condition (obesity with T2DM cohort)")
    # If title explicitly excludes T2D, note that
    if "without type 2 diabetes" in low or "without diabetes" in low or "non-diabetic" in low:
        notes.append("Study explicitly EXCLUDES Type 2 Diabetes (general obesity/overweight population)")
    # Title-mention of T2D comorbidity (even if conditions array doesn't list it)
    if ("type 2 diabetes" in low or "type 2 diabetes mellitus" in low) and not any(
        "EXCLUDES Type 2 Diabetes" in n for n in notes
    ):
        notes.append("Official title indicates obesity/overweight WITH Type 2 Diabetes comorbidity (T2DM cohort)")
    # Special populations
    if "adolescent" in low or "pediatric" in low or "children" in low or "pubertal" in low:
        notes.append("Pediatric/adoolescent obesity population (not adult-only general obesity)")
    return notes


def build(c, phase_bucket, mani):
    nct = c["nct"]
    m = mani.get(nct, {})
    ivs = c.get("interventions", [])
    iv_str = "; ".join(f"{i['name']} ({i['type']})" for i in ivs if i.get("name"))
    inv = c.get("docs_inventory", [])
    inv_str = "; ".join(f"{d['abbr']}={d['filename']}({d['date']})" for d in inv)
    pages = m.get("pages") or m.get("pages_pypdf")
    sample = m.get("first_pages_sample", "")
    notes = analyze_notes(c.get("official_title") or c.get("brief_title", ""),
                          c.get("conditions", []), iv_str, sample)
    # Determine precise document role from CT.gov metadata
    sel_doc = next((d for d in inv if d.get("filename") == c.get("prot_filename")), None)
    if sel_doc and sel_doc.get("hasProtocol") and sel_doc.get("hasSap"):
        doc_role = "Combined Protocol+SAP document (CT.gov ProvidedDocs, typeAbbrev=Prot_SAP, hasProtocol=true AND hasSap=true in single file)"
        notes.append("Document role caveat: this is a MERGED Protocol+SAP file (single PDF), not a pure protocol")
    elif sel_doc and sel_doc.get("hasProtocol") and not sel_doc.get("hasSap"):
        doc_role = "Original Study Protocol (CT.gov ProvidedDocs, typeAbbrev=Prot, hasProtocol=true, hasSap=false)"
    else:
        doc_role = "Original Study Protocol (CT.gov ProvidedDocs, typeAbbrev=Prot, hasProtocol=true)"
    # Classify by population: rare/syndromic (PWS, genetic) or NASH-primary or T2D-primary
    population = "general_obesity"
    for n in notes:
        nl = n.lower()
        if "rare/syndromic obesity population" in nl:
            population = "rare_syndromic_obesity"; break
        if "primary indication is nash" in nl:
            population = "nash_primary"; break
        # Only count T2D as comorbidity-class when T2D is a registered PRIMARY condition
        # (the "explicitly EXCLUDES" note must NOT trigger comorbidity classification)
        if "type 2 diabetes mellitus is a registered primary condition" in nl:
            population = "obesity_with_t2dm"; break
    return {
        "nct": nct,
        "phase_bucket": phase_bucket,
        "phases_registered": c.get("phases", []),
        "official_title": c.get("official_title") or c.get("brief_title", ""),
        "sponsor": c["sponsor"],
        "status": c["status"],
        "conditions": c.get("conditions", []),
        "interventions": iv_str,
        "population_class": population,
        "document_role": doc_role,
        "document_filename": c.get("prot_filename"),
        "document_version_date": c.get("prot_doc_date"),
        "document_upload_date": c.get("prot_doc_upload"),
        "provideddocs_study_url": f"https://clinicaltrials.gov/study/{nct}",
        "download_url": c.get("prot_dl_url"),
        "bytes": m.get("bytes"),
        "sha256": m.get("sha256"),
        "pages": pages,
        "head_status": c.get("prot_head_status"),
        "docs_inventory_in_record": inv_str,
        "has_results_posted": c.get("has_results"),
        "notes": notes,
    }


final = []
for c in ph2:
    final.append(build(c, "phase2", mani_main))
for c in ph3:
    final.append(build(c, "phase3", mani_main))
for c in ph3_supp:
    final.append(build(c, "phase3", mani_supp))

# Dedup by NCT (a study could appear in both main and supplement); keep first
seen = set()
deduped = []
for r in final:
    if r["nct"] in seen:
        continue
    seen.add(r["nct"])
    deduped.append(r)

out = {
    "indication": "Obesity or Overweight",
    "scan_date": "2026-07-19",
    "source": "ClinicalTrials.gov v2 API + cdn.clinicaltrials.gov large-docs",
    "phase2_count": sum(1 for r in deduped if r["phase_bucket"] == "phase2"),
    "phase2_unique_sponsors": sorted({r["sponsor"] for r in deduped if r["phase_bucket"] == "phase2"}),
    "phase3_count": sum(1 for r in deduped if r["phase_bucket"] == "phase3"),
    "phase3_unique_sponsors": sorted({r["sponsor"] for r in deduped if r["phase_bucket"] == "phase3"}),
    "phase3_general_obesity_sponsors": sorted({r["sponsor"] for r in deduped if r["phase_bucket"] == "phase3" and r["population_class"] == "general_obesity"}),
    "candidates": deduped,
}

with open(os.path.join(BASE, "FINAL_OBESITY_PROTOCOL_CANDIDATES.json"), "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)

# CSV for easy review
with open(os.path.join(BASE, "FINAL_OBESITY_PROTOCOL_CANDIDATES.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["phase", "nct", "sponsor", "status", "official_title", "conditions",
                "interventions", "population_class", "doc_version_date", "filename",
                "download_url", "bytes", "sha256", "pages", "notes"])
    for r in deduped:
        w.writerow([r["phase_bucket"], r["nct"], r["sponsor"], r["status"],
                    r["official_title"][:120], ";".join(r["conditions"]),
                    r["interventions"][:100], r["population_class"],
                    r["document_version_date"], r["document_filename"],
                    r["download_url"], r["bytes"], r["sha256"], r["pages"],
                    " | ".join(r["notes"])])

print(f"Total candidates: {len(deduped)}")
print(f"Phase II: {out['phase2_count']} candidates, {len(out['phase2_unique_sponsors'])} unique sponsors")
print(f"Phase III: {out['phase3_count']} candidates, {len(out['phase3_unique_sponsors'])} unique sponsors")
print(f"Phase III general-obesity sponsors: {len(out['phase3_general_obesity_sponsors'])}")
print("\nPhase II sponsors:")
for s in out["phase2_unique_sponsors"]:
    print(f"  - {s}")
print("\nPhase III sponsors:")
for s in out["phase3_unique_sponsors"]:
    cls = "general" if s in out["phase3_general_obesity_sponsors"] else "rare/comorbidity"
    print(f"  - {s}  ({cls})")
print(f"\nArtifacts: FINAL_OBESITY_PROTOCOL_CANDIDATES.json + .csv")
