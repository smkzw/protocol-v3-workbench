import json, hashlib, os, sys
root = "runs/mw_protocol_v3_3r5a_3r7a_fresh_review_20260913"
snap = os.path.join(root, "snapshot")
man = json.load(open(os.path.join(root, "artifact_manifest.json")))
files = man["files"]
print("manifest file count:", len(files))
missing, mismatch, ok = [], [], 0
for f in files:
    p = os.path.join(snap, f["path"])
    if not os.path.exists(p):
        missing.append(f["path"]); continue
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    if h != f["sha256"]:
        mismatch.append((f["path"], h, f["sha256"]))
    else:
        ok += 1
print("ok:", ok, "missing:", len(missing), "mismatch:", len(mismatch))
for m in missing: print("MISSING", m)
for m in mismatch: print("MISMATCH", m[0], "\n  snap:", m[1], "\n  man :", m[2])
# also list snapshot files not in manifest
mset = {f["path"] for f in files}
extra = []
for dp, dn, fn in os.walk(snap):
    for n in fn:
        rel = os.path.relpath(os.path.join(dp, n), snap)
        if rel not in mset and not rel.startswith("."):
            extra.append(rel)
print("extra files in snapshot not in manifest:", len(extra))
for e in sorted(extra)[:40]: print("EXTRA", e)
