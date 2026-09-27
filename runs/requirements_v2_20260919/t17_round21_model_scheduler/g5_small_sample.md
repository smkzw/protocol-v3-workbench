# G5 衔接 — 编排器接线 + K3 单文档小样本（2026-09-27，实现师）

批次：`wref_translation_batch_79e7f4e51e7270b75688e8e9`（项目 `proj_user_fad9f64f3151`，锁定快照 `wref_search_4d2c5d3b8476515fc38b`）
**本轮结论：共享前置校核不过 → 按 ask 预案产出批次级阻断，标记 BLOCKED，未点火（attempt 保持 3，零新派发）。**

---

## 1. 接线（响应契约不变）

| 入口 | 位置 | 改动 |
|---|---|---|
| 翻译 retry | `services/api/app/main.py:5851-5853` | （上一轮已接）`warm_translation_model()` → `ensure_phase("translation")`，try/except best-effort 不变 |
| 分诊 create | `services/api/app/main.py:8948-8950` | 本轮新增同款 best-effort `ensure_phase("triage")` |
| 分诊 retry | `services/api/app/main.py:9050-9052` | 本轮新增同款 best-effort `ensure_phase("triage")` |

- P17/P18 合同同步：`tests/acceptance/test_model_phase_scheduler_phase_contract.py` docstring 调用点审计已更新（翻译 retry + 分诊 create/retry 均走编排器；`warm_*` 保留签名、无生产调用方）；冻结常量由 `test_p_scheduler_frozen_constants_unchanged` 哨兵验证。
- FAST 定向自查：`python3 -m pytest tests/acceptance/test_model_lifecycle_orchestrator.py tests/acceptance/test_model_phase_scheduler_phase_contract.py -q` → **32 passed**（接线后复跑）。

## 2. 5301 启动与指纹核对

- 启动前实况：`lsof -nP -i :5301` 无监听（属启动而非杀重启）；8910（PID 8804）与 5186 均未触碰。
- 启动命令（HANDOFF_0924V2_BATCH1.md §一配方）：`python3.14 -m uvicorn app.main:app --host 127.0.0.1 --port 5301`，env 五件套（PYTHONPATH=services/api:.；WORKBENCH_RUNTIME_DIR / WORKBENCH_AI_SETTINGS_PATH / WORKBENCH_AI_ROLE_SETTINGS_PATH → `runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/isolated_runtime/`；WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED=1；WORKBENCH_PROTOCOL_V3_WORKFLOW_DB=<同目录>/protocol_v3_product.sqlite），日志 → 本目录 `mw_backend_5301_g5.log`。
- 指纹核对：`GET /api/runtime-readiness` → 200，`backend_build_id=api-0cb64c6ee4913599`；同仓库独立计算 `PYTHONPATH=services/api:. python3.14 -c "from app.runtime_readiness import backend_build_id; print(backend_build_id())"` → **api-0cb64c6ee4913599，与运行中服务一致**（该指纹为 services 源树 sha256，含本轮编排器接线代码）。备注：`/runtime-build.json` 是 vite(5186) 前端产物，本轮未启前端，故做的是"本地源树指纹 vs 运行中后端"双端核对；旧 build api-abc188a01c8bafa0 已被替换。

## 3. 共享前置校核（只读，未点火）

方法：经运行中 5301 的只读 GET 读取门所需全部状态（`_snapshot_scope` 的 A/B 两条权威路径 + 批次锁定快照），脚本见会话记录；journey 原文存 /tmp/k3_journey.json（会话内临时件）。

| 门条件 | 实测 | 结果 |
|---|---|---|
| 项目在册 | `GET /api/projects` 15 项含 K3 项目 | ✓ |
| A 路径：corpus_triage.status=="finalized" 且 snapshot 匹配 | `status="pending"`，`snapshot_id=""` | ✗ |
| B 路径：discovery.confirmation_id 非空 | `ct_conf_ebb394de59fb68021378` | ✓ |
| B 路径：discovery.snapshot_id==批次快照 | `wref_search_4d2c5d3b8476515fc38b` 一致 | ✓ |
| B 路径：journey.search_plan 非空且 latest_snapshot_id==批次快照 | **`search_plan` 键已存在（rev=6），但 `latest_snapshot_id=""` 空串** | ✗ |
| 附加硬校验：search_plan.latest_snapshot_id==批次快照（`writing_reference_translation_batch.py` `_snapshot_scope` 第二道） | 同上，空串≠`wref_search_4d2c...` | ✗ |

批次现状（`GET .../translation-batches/wref_translation_batch_...`）：status=failed，**attempt=3**（与 09-25 诊断一致，本轮未增），counts：830 项 = 574 failed_retryable + 排除口径另计；preparation_batch_id=`wref_prep_cc8a67c458de4225cd09ce38`。

与 09-25 `k3_gate_diag.md` 的差异：写侧缺失的 `search_plan` 键现已随 journey 序列化出现（默认空对象），但**快照关联仍为空**——门的两条路径与附加硬校验依旧全部不过。根因定性不变：写侧（from_zero bootstrap）不保证写入快照关联，读侧强校验拦截。

## 4. 批次级阻断记录（BLOCKED）

```json
{
  "verdict": "BLOCKED",
  "scope": "batch",
  "batch_id": "wref_translation_batch_79e7f4e51e7270b75688e8e9",
  "project_id": "proj_user_fad9f64f3151",
  "checked_at": "2026-09-27",
  "precheck": "shared snapshot-authority gate (_snapshot_scope A/B + locked-snapshot)",
  "failed_conditions": [
    "corpus_triage.status=pending (≠finalized)",
    "journey.search_plan.latest_snapshot_id='' ≠ batch snapshot wref_search_4d2c5d3b8476515fc38b"
  ],
  "action_taken": "none — no retry POST, no durable job, attempt stays 3",
  "unblock_path": "写侧补齐 journey.search_plan.latest_snapshot_id（或按产品裁定走 corpus_triage finalized 路径）后重跑本预检",
  "planned_small_sample_if_unblocked": "单文档=selected 范围最小研究 NCT02176291（1 个 failed_retryable 项，见 g6_k3_574_mapping.json）"
}
```

## 5. 本轮编排动作记录（actions.log 自动审计 + 本轮显式动作）

- `ensure(triage)`：status=ok（MTPLX@8002 驻留中，上一轮冷启恢复的 pid 89133，A18 探针 ≤8 token 通过）。
- `ensure(translation)`：refused `binding_base_url_mismatch`（8000 死端口漂移拒止，零动作）——**翻译本地化生效仍待用户确认 8000→8001 一次性迁移**；迁移前 K3 即使解锁门，正文也将走既有云端 fallback 链（显式配置路径，非静默切换）。
- 5301 启动为普通后端进程，不在两台受管模型服务器范围；8910 全程零触碰（监听 PID 8804 前后一致）。

## 6. 快速复核命令

```sh
curl -s http://127.0.0.1:5301/api/runtime-readiness | python3 -c "import json,sys;print(json.load(sys.stdin)['backend_build_id'])"
curl -s "http://127.0.0.1:5301/api/projects/proj_user_fad9f64f3151/medical-writing/authoring-journey" | python3 -c "import json,sys;j=json.load(sys.stdin);j=j.get('journey',j);print((j.get('search_plan') or {}).get('latest_snapshot_id'), (j.get('corpus_triage') or {}).get('status'))"
python3 -m pytest tests/acceptance/test_model_lifecycle_orchestrator.py tests/acceptance/test_model_phase_scheduler_phase_contract.py -q
```
