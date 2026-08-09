#!/usr/bin/env python3
"""Targeted second pass: find MORE general-population Phase III obesity protocols with provided docs,
excluding PWS/rare-syndromic studies, to push the Phase III general-obesity sponsor count >= 5."""
from __future__ import annotations
import urllib.request, urllib.parse, urllib.error, json, time, os, re

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) hermes-worker03/1.0"
BASE = "runs/execution/mw_protocol_structure_corpus_exec_20260719/worker_03_scan"


def fetch_v2(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def head(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.headers.get("Content-Length"), r.headers.get("Content-Type")
    except urllib.error.HTTPError as e:
        return e.code, None, None
    except Exception as e:
        return "ERR", str(e)[:60], None


# Already-confirmed sponsors to skip
with open(os.path.join(BASE, "phase3_confirmed.json")) as f:
    already = {c["sponsor"] for c in json.load(f)}
print("Already-confirmed Phase III sponsors:", len(already), flush=True)

# Re-list all Phase III obesity industry studies, but exclude PWS/rare by condition filter.
# CT.gov v2 AREA[ConditionSearch] doesn't support NOT easily; we'll fetch all and filter client-side.
params = {
    "query.cond": "Obesity OR Overweight",
    "filter.advanced": "AREA[Phase](PHASE3) AND AREA[StudyType](INTERVENTIONAL) AND AREA[LeadSponsorClass]INDUSTRY",
    "fields": "NCTId,BriefTitle,OfficialTitle,Phase,LeadSponsorName,OverallStatus,Condition,InterventionName,InterventionType",
    "pageSize": "100",
}
all_studies, token = [], None
for _ in range(10):
    p = dict(params)
    if token:
        p["pageToken"] = token
    url = "https://clinicaltrials.gov/api/v2/studies?" + urllib.parse.urlencode(p)
    d = fetch_v2(url)
    all_studies.extend(d.get("studies", []))
    token = d.get("nextPageToken")
    if not token:
        break
    time.sleep(0.25)
print(f"Fetched {len(all_studies)} Phase III industry obesity studies", flush=True)

RARE_KW = ["prader", "bardet", "biedl", "alstr", "pomc", "pcsk1", "lepr", "mc4r", "bardet-biedl",
           "pro-opiomelanocortin", "melanocortin"]


def is_rare(s):
    blob = json.dumps(s).lower()
    return any(k in blob for k in RARE_KW)


# rank: completed first, then by NCT asc (older)
RANK = {"COMPLETED": 0, "TERMINATED": 1, "ACTIVE_NOT_RECRUITING": 2, "WITHDRAWN": 3, "RECRUITING": 4,
        "UNKNOWN": 5, "NOT_YET_RECRUITING": 6, "SUSPENDED": 7}
candidates = []
for s in all_studies:
    ps = s["protocolSection"]
    sp = ps["sponsorCollaboratorsModule"]["leadSponsor"]["name"]
    if sp in already:
        continue
    if is_rare(s):
        continue
    nid = ps["identificationModule"]["nctId"]
    status = ps["statusModule"]["overallStatus"]
    candidates.append((RANK.get(status, 9), nid, sp, status, s))
candidates.sort()
print(f"Non-rare, non-already-confirmed Phase III candidates: {len(candidates)}", flush=True)

# Probe up to 80 candidates for provided Prot docs
new_confirmed = []
for rank, nid, sp, status, s in candidates[:120]:
    try:
        d = fetch_v2(f"https://clinicaltrials.gov/api/v2/studies/{nid}")
    except Exception:
        continue
    ds = d.get("documentSection") or {}
    ldm = ds.get("largeDocumentModule") or {}
    docs = ldm.get("largeDocs") or []
    prot = next((x for x in docs if x.get("hasProtocol")), None)
    if prot:
        digits = nid[3:]
        last2 = digits[-2:]
        fn = prot.get("filename", "Prot_000.pdf")
        dl = f"https://cdn.clinicaltrials.gov/large-docs/{last2}/{nid}/{fn}"
        st, clen, ctype = head(dl)
        if st == 200:
            rec = {
                "nct": nid, "sponsor": sp, "status": status,
                "brief_title": ps["identificationModule"].get("briefTitle", ""),
                "official_title": ps["identificationModule"].get("officialTitle", ""),
                "phases": ps.get("designModule", {}).get("phases", []),
                "conditions": ps.get("conditionsModule", {}).get("conditions", []),
                "interventions": [{"name": i.get("name", ""), "type": i.get("type", "")} for i in ps.get("armsInterventionsModule", {}).get("interventions", [])][:5],
                "prot_doc_date": prot.get("date"), "prot_doc_upload": prot.get("uploadDate"),
                "prot_filename": fn, "prot_dl_url": dl, "prot_head_status": st, "prot_head_size": clen,
                "docs_inventory": [{"abbr": x.get("typeAbbrev"), "filename": x.get("filename"), "date": x.get("date"),
                                    "hasProtocol": x.get("hasProtocol"), "hasSap": x.get("hasSap")} for x in docs],
                "has_results": d.get("hasResults"),
            }
            new_confirmed.append(rec)
            print(f"  [+] {sp[:38]:40s} {nid}  date={prot.get('date')}  bytes={clen}", flush=True)
            if len(new_confirmed) >= 6:
                break
    time.sleep(0.15)

print(f"\nNew general-population Phase III confirmed: {len(new_confirmed)}", flush=True)
with open(os.path.join(BASE, "phase3_confirmed_supplement.json"), "w") as f:
    json.dump(new_confirmed, f, indent=2, ensure_ascii=False)
print(f"Wrote {os.path.join(BASE, 'phase3_confirmed_supplement.json')}", flush=True)
