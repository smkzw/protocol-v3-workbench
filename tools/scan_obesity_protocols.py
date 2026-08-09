#!/usr/bin/env python3
"""
worker_03 helper: scan ClinicalTrials.gov for industry-sponsored Obesity/Overweight
Phase II and Phase III interventional studies and confirm which have a publicly
downloadable original Study Protocol PDF (ProvidedDocs / large-docs).

Output: two JSON files with confirmed candidates.
Run: python3 tools/scan_obesity_protocols.py
"""
from __future__ import annotations
import urllib.request, urllib.parse, urllib.error, json, time, sys, os

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) hermes-worker03/1.0"
OUT_DIR = "runs/execution/mw_protocol_structure_corpus_exec_20260719/worker_03_scan"
os.makedirs(OUT_DIR, exist_ok=True)


def fetch_v2(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def list_studies(phase, page_size=100, max_pages=10):
    params = {
        "query.cond": "Obesity OR Overweight",
        "filter.advanced": f"AREA[Phase]({phase}) AND AREA[StudyType](INTERVENTIONAL) AND AREA[LeadSponsorClass]INDUSTRY",
        "fields": "NCTId,BriefTitle,OfficialTitle,Phase,LeadSponsorName,LeadSponsorClass,OverallStatus,StudyType,Condition,InterventionName,InterventionType,StartDate,PrimaryCompletionDate,CompletionDate",
        "pageSize": str(page_size),
    }
    out, token = [], None
    for _ in range(max_pages):
        p = dict(params)
        if token:
            p["pageToken"] = token
        url = "https://clinicaltrials.gov/api/v2/studies?" + urllib.parse.urlencode(p)
        d = fetch_v2(url)
        out.extend(d.get("studies", []))
        token = d.get("nextPageToken")
        if not token:
            break
        time.sleep(0.25)
    return out


def study_detail(nct):
    url = f"https://clinicaltrials.gov/api/v2/studies/{nct}"
    return fetch_v2(url)


def head(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.headers.get("Content-Length"), r.headers.get("Content-Type")
    except urllib.error.HTTPError as e:
        return e.code, None, None
    except Exception as e:
        return "ERR", str(e)[:60], None


RANK = {"COMPLETED": 0, "TERMINATED": 1, "ACTIVE_NOT_RECRUITING": 2, "WITHDRAWN": 3,
        "RECRUITING": 4, "UNKNOWN": 5, "NOT_YET_RECRUITING": 6, "SUSPENDED": 7,
        "ENROLLING_BY_INVITATION": 8, "AVAILABLE": 9}


def candidate_from(s):
    ps = s["protocolSection"]
    im = ps.get("identificationModule", {})
    sm = ps.get("statusModule", {})
    dm = ps.get("designModule", {})
    scm = ps.get("sponsorCollaboratorsModule", {})
    cm = ps.get("conditionsModule", {})
    aim = ps.get("armsInterventionsModule", {})
    ivs = aim.get("interventions", [])
    return {
        "nct": im.get("nctId"),
        "brief_title": im.get("briefTitle", ""),
        "official_title": im.get("officialTitle", ""),
        "phases": dm.get("phases", []),
        "study_type": dm.get("studyType", ""),
        "sponsor": scm.get("leadSponsor", {}).get("name", ""),
        "sponsor_class": scm.get("leadSponsor", {}).get("class", ""),
        "status": sm.get("overallStatus", ""),
        "conditions": cm.get("conditions", []),
        "interventions": [{"name": i.get("name", ""), "type": i.get("type", "")} for i in ivs][:5],
        "start_date": sm.get("startDateStruct", {}).get("date", "") if sm.get("startDateStruct") else "",
    }


def scan_phase(phase, target=10, sponsor_cap=80, per_sponsor=3):
    print(f"\n=== Scanning {phase} industry Obesity/Overweight trials ===", flush=True)
    studies = list_studies(phase)
    print(f"  fetched {len(studies)} studies", flush=True)

    sponsor_to_ncts = {}
    for s in studies:
        c = candidate_from(s)
        sponsor_to_ncts.setdefault(c["sponsor"], []).append(c)
    # prefer completed, oldest by NCT digits (lower = older)
    for sp in sponsor_to_ncts:
        sponsor_to_ncts[sp].sort(key=lambda c: (RANK.get(c["status"], 9), c["nct"]))

    confirmed, examined = [], []
    sponsors_seen_in_confirmed = set()
    sponsors_tried = 0
    for sp, cands in sponsor_to_ncts.items():
        if len(confirmed) >= target:
            break
        if sponsors_tried >= sponsor_cap:
            break
        sponsors_tried += 1
        # only check up to per_sponsor studies per sponsor; skip if already confirmed for this sponsor
        if sp in sponsors_seen_in_confirmed:
            continue
        for c in cands[:per_sponsor]:
            nid = c["nct"]
            try:
                d = study_detail(nid)
            except Exception as e:
                examined.append({"nct": nid, "sponsor": sp, "error": f"{type(e).__name__}: {str(e)[:60]}"})
                continue
            ds = d.get("documentSection") or {}
            ldm = ds.get("largeDocumentModule") or {}
            docs = ldm.get("largeDocs") or []
            prot_docs = [x for x in docs if x.get("hasProtocol")]
            rec = {"nct": nid, "sponsor": sp, "status": c["status"], "brief_title": c["brief_title"],
                   "official_title": c["official_title"], "phases": c["phases"],
                   "conditions": c["conditions"], "interventions": c["interventions"],
                   "start_date": c["start_date"],
                   "has_results": d.get("hasResults"),
                   "docs_module_present": bool(docs),
                   "docs_inventory": [{"abbr": x.get("typeAbbrev"), "filename": x.get("filename"),
                                      "date": x.get("date"), "upload": x.get("uploadDate"),
                                      "hasProtocol": x.get("hasProtocol"), "hasSap": x.get("hasSap"),
                                      "hasIcf": x.get("hasIcf"), "size": x.get("size")} for x in docs]}
            if prot_docs:
                prot = prot_docs[0]
                digits = nid[3:]
                last2 = digits[-2:]
                fn = prot.get("filename", "Prot_000.pdf")
                dl = f"https://cdn.clinicaltrials.gov/large-docs/{last2}/{nid}/{fn}"
                st, clen, ctype = head(dl)
                rec.update({"prot_doc_date": prot.get("date"),
                            "prot_doc_upload": prot.get("uploadDate"),
                            "prot_filename": fn,
                            "prot_size_api": prot.get("size"),
                            "prot_dl_url": dl,
                            "prot_head_status": st,
                            "prot_head_size": clen,
                            "prot_head_type": ctype,
                            "role": "Original Study Protocol (provided document)"})
                confirmed.append(rec)
                sponsors_seen_in_confirmed.add(sp)
                print(f"  [+] {sp[:40]:42s} {nid}  date={prot.get('date')}  bytes={clen}", flush=True)
                break
            else:
                examined.append(rec)
            time.sleep(0.12)
    print(f"  -> sponsors tried={sponsors_tried}, examined={len(examined)}, confirmed with Prot doc={len(confirmed)}", flush=True)
    return confirmed, examined, len(studies), len(sponsor_to_ncts)


def main():
    ph2_conf, ph2_exam, ph2_total, ph2_sponsors = scan_phase("PHASE2", target=12, sponsor_cap=100, per_sponsor=4)
    ph3_conf, ph3_exam, ph3_total, ph3_sponsors = scan_phase("PHASE3", target=12, sponsor_cap=100, per_sponsor=4)

    summary = {
        "phase2": {"studies_fetched": ph2_total, "unique_industry_sponsors": ph2_sponsors,
                   "confirmed_with_protocol": len(ph2_conf),
                   "confirmed_sponsors": sorted({c["sponsor"] for c in ph2_conf})},
        "phase3": {"studies_fetched": ph3_total, "unique_industry_sponsors": ph3_sponsors,
                   "confirmed_with_protocol": len(ph3_conf),
                   "confirmed_sponsors": sorted({c["sponsor"] for c in ph3_conf})},
    }
    with open(os.path.join(OUT_DIR, "phase2_confirmed.json"), "w") as f:
        json.dump(ph2_conf, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT_DIR, "phase2_examined.json"), "w") as f:
        json.dump(ph2_exam, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT_DIR, "phase3_confirmed.json"), "w") as f:
        json.dump(ph3_conf, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT_DIR, "phase3_examined.json"), "w") as f:
        json.dump(ph3_exam, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT_DIR, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print("\n=== SUMMARY ===", flush=True)
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    print(f"\nOutputs in {OUT_DIR}/", flush=True)


if __name__ == "__main__":
    main()
