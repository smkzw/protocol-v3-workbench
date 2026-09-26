#!/usr/bin/env python3
"""切片闭环证明 HTTP 段 v2：在正文节（方案摘要 cms_synopsis_summary）走
编辑→保存→服务端确认与版本hash→重开→下载保留。真实5301，无mock。"""
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
SEC = "mwsec_greenfield_proj_user_97189da36a75_64f059a1079a8aca"  # 方案概要（正文渲染节，rev>=1工作稿）
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
            return {"status": resp.status, "elapsed_s": round(time.time() - t0, 3),
                    "headers": dict(resp.headers.items()),
                    "body": body if raw else json.loads(body)}
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = body.decode("utf-8", "replace")[:300]
        return {"status": e.code, "elapsed_s": round(time.time() - t0, 3), "body": parsed, "headers": {}}


def step(name, ok, detail):
    R["steps"].append({"step": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + " :: " + json.dumps(detail, ensure_ascii=False)[:500])


def hdr(h):
    return {k.lower(): v for k, v in h.items()}


# S0 起点
wc = req("GET", f"/api/projects/{PROJ}/medical-writing/working-copies/{SEC}")
b = wc["body"]
rev0 = b["revision"]
doc_id = b["document_id"]
para_blocks = [x for x in b["content_blocks"] if x["block_type"] == "paragraph"]
target = para_blocks[0] if para_blocks else next(x for x in b["content_blocks"] if x.get("text"))
step("S0_fixture起点_正文节工作稿", wc["status"] == 200 and rev0 >= 1,
     {"revision": rev0, "authority": b["content_authority_state"], "blocks": len(b["content_blocks"]),
      "paragraph_blocks": len(para_blocks), "target_text_head": target.get("text", "")[:50],
      "updated_at": b["updated_at"]})
assert wc["status"] == 200 and rev0 >= 1, "正文节fixture不可用"
(TMP / "wc_body_before.json").write_text(json.dumps(b, ensure_ascii=False, indent=1))

blocks = b["content_blocks"]

# S1 负例：过期 revision 必须被拒
neg = req("POST", f"/api/projects/{PROJ}/medical-writing/working-copies/{SEC}",
          {"document_id": doc_id, "expected_revision": rev0 - 1, "content_blocks": blocks,
           "actor": "medical_manager", "idempotency_key": f"slice-neg2-0927v1-{int(time.time())}"}, timeout=30)
step("S1_负例_过期revision被拒409", neg["status"] == 409, {"status": neg["status"], "body": str(neg["body"])[:160]})

# S2 编辑：目标段落 text+rich_text 追加标记（唯一允许字段）
edited = copy.deepcopy(blocks)
tb = next(x for x in edited if x["block_id"] == target["block_id"])
old_text = tb["text"]
new_text = old_text + MARK
tb["text"] = new_text
# rich_text: 根节点 content[*] 含 paragraph，需要把 text node 追加进叶子段落
def append_text_to_node(node):
    if isinstance(node, dict):
        if node.get("type") == "text":
            node["text"] = node["text"] + MARK
            return True
        for c in node.get("content", []) or []:
            if append_text_to_node(c):
                return True
    return False
# 找到与原文等长的叶子文本节点追加（rich_text 是 doc > content[paragraph] > content[text]）
rt_ok = False
for c in tb.get("rich_text", {}).get("content", []):
    if append_text_to_node(c):
        rt_ok = True
        break
payload_sha = hashlib.sha256(json.dumps(edited, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
step("S2_本地编辑", rt_ok and tb["text"] == new_text, {"old_head": old_text[:40], "new_tail": new_text[-24:], "payload_sha256": payload_sha})

# S3 保存
save = req("POST", f"/api/projects/{PROJ}/medical-writing/working-copies/{SEC}",
           {"document_id": doc_id, "expected_revision": rev0, "content_blocks": edited,
            "actor": "medical_manager", "idempotency_key": f"slice-loop2-0927v1-{int(time.time())}"}, timeout=60)
sb = save.get("body", {})
step("S3_保存_服务端回执", save["status"] == 200 and sb.get("revision") == rev0 + 1,
     {"status": save["status"], "revision": sb.get("revision"), "updated_at": sb.get("updated_at"),
      "updated_by": sb.get("updated_by"), "elapsed_s": save["elapsed_s"]})
assert save["status"] == 200, "正文节保存失败"
(TMP / "save_body_receipt.json").write_text(json.dumps(sb, ensure_ascii=False, indent=1))

# S4 重开：服务端确认内容与版本
reopen = req("GET", f"/api/projects/{PROJ}/medical-writing/working-copies/{SEC}")
rb = reopen["body"]
rtb = next(x for x in rb["content_blocks"] if x["block_id"] == target["block_id"])
reopen_sha = hashlib.sha256(json.dumps(rb["content_blocks"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
step("S4_重开_服务端确认与版本hash一致", reopen["status"] == 200 and rb["revision"] == rev0 + 1
     and rtb["text"] == new_text and reopen_sha == payload_sha,
     {"revision": rb["revision"], "text_tail": rtb["text"][-24:],
      "server_content_sha256": reopen_sha, "matches_submitted": reopen_sha == payload_sha})

# S5 下载：版本hash回执 == 实际字节，且编辑保留在 DOCX
dl1 = req("GET", f"/api/projects/{PROJ}/medical-writing/document.docx?mode=draft_preview", timeout=180, raw=True)
h1 = hdr(dl1["headers"])
docx1 = TMP / "body_download_1.docx"
docx1.write_bytes(dl1["body"])
sha_actual = hashlib.sha256(dl1["body"]).hexdigest()
sha_hdr = h1.get("x-medical-writing-docx-sha256", "")
snap_hdr = h1.get("x-medical-writing-source-snapshot-sha256", "")
marker_in_docx = False
try:
    with zipfile.ZipFile(docx1) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
        marker_in_docx = MARK in xml
except Exception:
    pass
step("S5_下载_版本hash与编辑保留", dl1["status"] == 200 and sha_hdr == sha_actual and marker_in_docx,
     {"status": dl1["status"], "bytes": len(dl1["body"]), "elapsed_s": dl1["elapsed_s"],
      "docx_sha256_header": sha_hdr, "docx_sha256_actual": sha_actual, "hash_match": sha_hdr == sha_actual,
      "marker_in_docx": marker_in_docx, "source_snapshot_sha256": snap_hdr[:16] + "…",
      "disposition_utf8": h1.get("content-disposition", "")[-80:]})

# S6 重开后再下载：字节稳定=保留
dl2 = req("GET", f"/api/projects/{PROJ}/medical-writing/document.docx?mode=draft_preview", timeout=180, raw=True)
sha2 = hashlib.sha256(dl2["body"]).hexdigest()
(TMP / "body_download_2.docx").write_bytes(dl2["body"])
step("S6_重开再下载_保留稳定", dl2["status"] == 200 and sha2 == sha_actual == sha_hdr,
     {"status": dl2["status"], "bytes2": len(dl2["body"]), "sha256_2": sha2, "stable": sha2 == sha_actual})

json.dump(R, open(TMP / "http_loop_body_result.json", "w"), ensure_ascii=False, indent=1)
ok_all = all(s["ok"] for s in R["steps"])
print("ALL_OK" if ok_all else "HAS_FAILURE")
sys.exit(0 if ok_all else 1)
