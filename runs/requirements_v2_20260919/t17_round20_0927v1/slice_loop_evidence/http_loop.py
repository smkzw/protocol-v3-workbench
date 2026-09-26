#!/usr/bin/env python3
"""切片闭环证明 HTTP 段：编辑→保存→服务端确认与版本hash→重开→下载保留。
全部请求打真实 5301 后端，无任何 mock。每步超时硬顶。"""
import copy
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

BASE = "http://127.0.0.1:5301"
PROJ = "proj_user_97189da36a75"
SEC = "mwsec_greenfield_proj_user_97189da36a75_d9c1cd375c30f809"
MARK = "【切片闭环0927V1】"
TMP = Path("/tmp/slice_loop_0927v1")
R = {"steps": []}


def req(method, path, payload=None, timeout=60, raw=False):
    url = BASE + path
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            body = resp.read()
            out = {
                "status": resp.status,
                "elapsed_s": round(time.time() - t0, 3),
                "headers": {k: v for k, v in resp.headers.items() if k.startswith(("X-Medical", "Content-Disposition"))},
            }
            out["body"] = body if raw else json.loads(body)
            return out
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = body.decode("utf-8", "replace")[:300]
        return {"status": e.code, "elapsed_s": round(time.time() - t0, 3), "body": parsed, "headers": {}}


def step(name, ok, detail):
    R["steps"].append({"step": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + " :: " + json.dumps(detail, ensure_ascii=False)[:400])


# S0 起点：读工作稿（可恢复起点=已保存工作稿 revision>=1）
wc = req("GET", f"/api/projects/{PROJ}/medical-writing/working-copies/{SEC}")
rev0 = wc["body"]["revision"]
doc_id = wc["body"]["document_id"]
step("S0_fixture起点_读工作稿", wc["status"] == 200 and rev0 >= 1,
     {"revision": rev0, "authority": wc["body"]["content_authority_state"], "freeze": wc["body"]["freeze_status"],
      "updated_at": wc["body"]["updated_at"], "blocks": len(wc["body"]["content_blocks"])})
assert wc["status"] == 200, "fixture起点不可用"
(TMP / "wc_before.json").write_text(json.dumps(wc["body"], ensure_ascii=False, indent=1))

blocks = wc["body"]["content_blocks"]
head = next(b for b in blocks if b["block_type"] == "heading")
old_text = head["text"]
new_text = MARK + old_text

# S1 负例：过期 expected_revision 必须被服务端拒绝（权限/并发校验真实，非 mock）
neg = req("POST", f"/api/projects/{PROJ}/medical-writing/working-copies/{SEC}",
          {"document_id": doc_id, "expected_revision": 0, "content_blocks": blocks,
           "actor": "medical_manager", "idempotency_key": f"slice-neg-0927v1-{int(time.time())}"}, timeout=30)
step("S1_负例_过期revision被拒", neg["status"] == 409,
     {"status": neg["status"], "body": str(neg["body"])[:200]})

# S2 编辑：heading 块改 text+rich_text（源链接块唯一允许的可变字段）
edited = copy.deepcopy(blocks)
eh = next(b for b in edited if b["block_type"] == "heading")
eh["text"] = new_text
eh["rich_text"]["content"][0]["text"] = new_text
payload_sha = hashlib.sha256(json.dumps(edited, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

# S3 保存（真实业务写入路径）
save = req("POST", f"/api/projects/{PROJ}/medical-writing/working-copies/{SEC}",
           {"document_id": doc_id, "expected_revision": rev0, "content_blocks": edited,
            "actor": "medical_manager", "idempotency_key": f"slice-loop-0927v1-{int(time.time())}"}, timeout=60)
step("S3_保存", save["status"] == 200 and save["body"].get("revision") == rev0 + 1,
     {"status": save["status"], "revision": save.get("body", {}).get("revision"),
      "updated_at": save.get("body", {}).get("updated_at"), "updated_by": save.get("body", {}).get("updated_by"),
      "payload_content_sha256": payload_sha})
assert save["status"] == 200, "保存失败，闭环中断"
(TMP / "save_receipt.json").write_text(json.dumps(save["body"], ensure_ascii=False, indent=1))

# S4 服务端确认+重开：重新 GET，内容与提交一致、revision 持久
reopen = req("GET", f"/api/projects/{PROJ}/medical-writing/working-copies/{SEC}")
rt = next(b for b in reopen["body"]["content_blocks"] if b["block_type"] == "heading")
same = (rt["text"] == new_text) and (reopen["body"]["revision"] == rev0 + 1)
canonical_same = hashlib.sha256(json.dumps(reopen["body"]["content_blocks"], ensure_ascii=False, sort_keys=True).encode()).hexdigest() == payload_sha
step("S4_重开_服务端确认", reopen["status"] == 200 and same and canonical_same,
     {"revision": reopen["body"]["revision"], "text_head": rt["text"][:60],
      "content_sha256_equal": canonical_same, "updated_at": reopen["body"]["updated_at"]})

# S5 下载（版本hash回执）+ 编辑保留进 DOCX
dl1 = req("GET", f"/api/projects/{PROJ}/medical-writing/document.docx?mode=draft_preview", timeout=180, raw=True)
ok_status = dl1["status"] == 200
docx1 = TMP / "download_1.docx"
docx1.write_bytes(dl1["body"])
sha_actual = hashlib.sha256(dl1["body"]).hexdigest()
sha_hdr = dl1["headers"].get("X-Medical-Writing-Docx-Sha256", "")
disposition = dl1["headers"].get("Content-Disposition", "")
marker_in_docx = False
xml_snippet = ""
try:
    with zipfile.ZipFile(docx1) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
        marker_in_docx = MARK in xml and new_text in xml
        i = xml.find(MARK)
        xml_snippet = xml[max(0, i - 80):i + 120] if i >= 0 else ""
except Exception as e:
    xml_snippet = f"zip_error:{e}"
step("S5_下载_版本hash与编辑保留", ok_status and sha_hdr == sha_actual and marker_in_docx,
     {"status": dl1["status"], "bytes": len(dl1["body"]), "sha256_header": sha_hdr,
      "sha256_actual": sha_actual, "hash_match": sha_hdr == sha_actual,
      "marker_in_docx": marker_in_docx, "disposition": disposition[:160],
      "source_snapshot_sha256": dl1["headers"].get("X-Medical-Writing-Source-Snapshot-Sha256", "")[:16] + "…"})

# S6 再次下载（重开后再取）→ 字节一致=下载保留稳定
dl2 = req("GET", f"/api/projects/{PROJ}/medical-writing/document.docx?mode=draft_preview", timeout=180, raw=True)
sha2 = hashlib.sha256(dl2["body"]).hexdigest()
(TMP / "download_2.docx").write_bytes(dl2["body"])
step("S6_重开再下载_保留稳定", dl2["status"] == 200 and sha2 == sha_actual and sha2 == sha_hdr,
     {"status": dl2["status"], "bytes2": len(dl2["body"]), "sha256_2": sha2, "stable": sha2 == sha_actual})

json.dump(R, open(TMP / "http_loop_result.json", "w"), ensure_ascii=False, indent=1)
ok_all = all(s["ok"] for s in R["steps"])
print("ALL_OK" if ok_all else "HAS_FAILURE")
sys.exit(0 if ok_all else 1)
