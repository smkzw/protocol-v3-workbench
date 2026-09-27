# LIVE演练记录（round21 生命周期编排器 · 模型员轮）

日期：2026-09-27 12:02–12:04 ｜ 工具：`runs/.../t17_round21_model_scheduler/lively_run.py` → `services/api/app/model_lifecycle_orchestrator.py`（配置 `services/api/config/model_lifecycle.json`，阈值/命令全在配置文件）
演练前只读 status 基线：oMLX@8001 healthy 0驻留；MTPLX@8002 resident、owned、pid=89133、哨兵 inflight=0；绑定旗标 translation_body=**binding_base_url_mismatch**、triage/design=binding_disabled。

## ① ensure(translation) → **拒止（符合设计，零动作）**
```
python3 lively_run.py ensure translation
→ {"status":"refused","reason":"binding_base_url_mismatch",
   "detail":"role=translation_body profile base_url='http://127.0.0.1:8000/v1' vs managed http://127.0.0.1:8001"}
```
活8910运行库的 translation_body 绑定仍指向 8000，与受管 8001 不一致 → fail-closed 拒止，两台服务器零触碰（红线3）。**翻译阶段的编排可用性卡在一次性 8000→8001 绑定迁移上，需用户确认后由实现师执行**。参考：翻译模型本体可用性上一轮已实测（mem_probe.md：冷载 3.93s、驻留 29.83GB、A18 通过），本轮未重复实测。

## ② ensure(triage) → **幂等直通 ok（0.35s）**
```
python3 lively_run.py ensure triage
→ {"status":"ok","phase":"triage","server":"mtplx","action_taken":false,"model":"mtplx-flash-next-optimized-speed"}
```
已驻留+身份四证（pidfile/cmdline/health/served id）→ 不重启不重载，仅 A18 真实探针（max_tokens=8 上限内）验证可用。

## ③ 内存压力卸载→自动恢复（真实停机/复电）
| 步骤 | 命令 | 结果 | 耗时 | 系统空闲 |
|---|---|---|---|---|
| 卸载 | `lively_run.py release triage "lively drill step3: memory-pressure unload"`（非force，前置 inflight=0） | ok, released=true；编排器自审计 drain_complete | **1.29s**（内含1.19s停机+确认；进程消失+8002零监听） | 27%→**89%**（80GB归还） |
| 恢复 | `lively_run.py ensure triage` | ok（health≠200→自动 quickstart 冷启→pidfile自动换新→A18通过） | **14.77s** | →24%（模型重驻留） |
| 终态 | 只读核验 | 新 pid=91095，phys_footprint **80GB**，served id=mtplx-flash-next-optimized-speed | - | - |

策略指定的先卸者=当前唯一驻留的 MTPLX（互斥策略：加载一方前先排空另一方；oMLX 侧卸载走 /admin/api/models/{id}/unload，MTPLX 侧走 mtplx stop，均在配置文件）。

## 结论
- done=true：编排器三能力（幂等ensure、策略卸载、卸载后自动恢复）在真实环境全链路验证，全程只触碰 8001/8002 两台（oMLX 仅只读GET），8910/医学监查零触碰；编排器每步自审计 + 模型员复核审计均在 actions.log。
- 未完成项（非缺陷）：ensure(translation) 因活库绑定指向 8000 被按设计拒止，等用户一次性迁移确认后重跑即为全绿。
- 已知局限（实现师12:00已记录）：哨兵计数活在API进程内，跨进程不共享——本轮以 status inflight=0 前置校核代替在途等待。
