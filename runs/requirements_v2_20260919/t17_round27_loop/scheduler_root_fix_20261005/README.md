# 调度器串行根治 — 20261005（主会话亲做）

## 实测裁决链（全部本机实证）
1. oMLX balanced 档动态上限不计内核可逐出的文件缓存：27.4GiB 可用仍判 18.9GiB 上限，31.25GiB 翻译模型被拒（几天来"拒绝变体"真根因）。aggressive 档实测加载后仍余 ~32GiB → 配置 memory_guard_tier=aggressive，ensure 自动对齐（审计）。
2. 双模型"加载时装得下、生成时装不下"：aggressive 下 dawncr0w+GUI-MTPLX 加载共存成功，但 MTPLX 生成时懒加载权重 → swap 22GB 爆炸（0928 同型）。**共存旁路（20261004e）删除，恢复严格串行。**
3. 切换顺序结构性根因：旧序"先启动MTPLX→再排空对侧"使冷加载与对侧卸载并发（第二起爆炸，owner实抓）→ **反转为先排空→等内存实际归还→再启动**。
4. OCR 永久驻留缺口（owner实抓"为什么OCR一直没卸载"）：排空只卸 managed_model_id → 改为 drain_unload_models 清单全卸（dawncr0w+GLM-OCR）。

## 代码（services/api/app/model_lifecycle_orchestrator.py + config）
- 删除：_coexistence_bypass、_host_available_bytes、coexistence 配置段。
- 新增：_authorized_takeover_identity（owner授权：空闲+MTPLX家族探针确认→接管停机，CLI优先/SIGTERM兜底/绝不SIGKILL外来进程/不确认即拒绝）；_authorized_reuse_identity（健康外来监听者授权复用=从GUI调用）；_takeover_stop；_ensure_omlx_guard_tier；_await_memory_recovered+_vm_stat_available_bytes；排空先于启动（needs_start延迟）；排空清卸全部受管模型（含OCR）。
- 配置：mtplx_takeover段、omlx.drain_unload_models、omlx.memory_guard_tier=aggressive、mtplx.start_memory_min_bytes=36GiB。
- 状态缓存重建：orchestrator_state.json → {}（备份 .pre-serial-rootfix-20261005）。

## 测试
- 删 test_model_lifecycle_coexistence_bypass.py；新增 test_model_lifecycle_serial_takeover.py（7用例：接管/禁用时拒绝/非MTPLX拒签/停不确认fail-closed无SIGKILL/复用/档位对齐）。
- test_model_phase_arbiter 回滚用例改写为更强新契约（被否决的切换根本不启动）。
- 全绿：serial_takeover 7 + ownership_reconcile 12 + acceptance orchestrator/arbiter 45 = 64 passed。

## 真机验证
- 真实 ensure(translation) 全链 4.5s：接管判定（探针+空闲）→CLI优雅停GUI服务器(3.78s确认)→翻译就绪（actions.log 11:55:05-09 完整审计）。
- 反向切换（design→translation 往返）由恢复后的 LOOP 全链自检验证（节点③④⑤即真实串行切换）。

## 事故记录（诚实）
- 本根治过程中的实测实验本身触发一次爆swap（共存验证时MTPLX生成懒加载）与一次切换窗口叠加（旧序并发根因）——均已定位为设计证据并体现在最终代码。
