"""reboot 不间断推进器（主会话心跳驱动，非dwfrun）。

设计：主Agent每轮心跳（用户消息/工人完成通知/定时唤醒）调一次 tick()：
- 检查在途工人/后台job → 交验合入
- 无在途工作 → 按工作包队列派发下一个工人
- 遇需用户决策项 → 输出决策请求并停派（不空转）
队列数据在 tools/orchestrator/queue.json（持久，可无损接续）。
"""
import json, os, subprocess, time, datetime

QPATH = os.path.join(os.path.dirname(__file__), "queue.json")

DEFAULT_QUEUE = {
    "pending": [
        {"id": "WP-M1-FIXTURE", "desc": "fixture抽取：从成型方案(朗来MY009-UC V2.0/康哲rux-ad/朗来MY004-RA)抽开局输入+参照答案，建eval/fixtures/<key>/（runtime不进git）", "deps": []},
        {"id": "WP-M1-EVALDEV", "desc": "dev/held-out划分+eval/run.py对3基线全量出分+基线报告定稿", "deps": ["WP-M1-FIXTURE", "M0_BASELINE"]},
        {"id": "WP-M2-STYLEKIT", "desc": "TopK确认UX+StyleKit/ClauseBank生成器（输入=CompetitorSet+解析后方案段落）", "deps": ["WP-M2-CORPUS_DONE"]},
        {"id": "WP-M2-B05", "desc": "分诊专病函数替换为通用术语匹配（B05，删24个专病函数）", "deps": ["WP-M2-CORPUS_DONE"]},
        {"id": "WP-M3-CHECKERS", "desc": "确定性检查器族：事实一致/风格泄漏/跨章一致/过程话术检测（只标记不改写）", "deps": []},
        {"id": "WP-M3-RENDER", "desc": "确定性渲染器：剂量表/SoA表/分析集（读StudyDefinition+SectionCard出数字表格）", "deps": ["WP-M4-CALC_DONE"]},
        {"id": "WP-M1-MODELEVAL", "desc": "模型对比（08_MODEL_EVAL：DeepSeek V4.1-Flash API vs 本地量化 vs GLM-5.3等，3dev项目×6类章节）", "deps": ["WP-M1-EVALDEV"]},
        {"id": "WP-M4-DECISIONCARD", "desc": "S2决定卡生成（选项+分析+推荐+竞品做法）", "deps": ["WP-M2-STYLEKIT"]},
        {"id": "WP-M5-DOCCHAIN", "desc": "文档级发布替代逐章冻结+一致性核对+导出", "deps": ["WP-M3-ENGINE"]}
    ],
    "completed": ["M0_GITIGNORE", "M0_STATUS", "WP-M1-EVAL-SKELETON", "WP-M3-LINT", "WP-M4-CALC", "WP-M2-CORPUS"],
    "blocked_on_user": [],
    "in_flight": [],
    "updated_at": None
}

def load():
    if not os.path.exists(QPATH):
        save(DEFAULT_QUEUE)
    with open(QPATH) as f:
        return json.load(f)

def save(q):
    q["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(QPATH, "w") as f:
        json.dump(q, f, ensure_ascii=False, indent=1)

def next_action(q):
    """返回 (action_type, payload)：
    - ("dispatch", workpack) 派发下一个可开工包
    - ("wait", reason) 有在途工作，等待
    - ("ask_user", item) 需用户决策
    - ("done", None) 队列空
    """
    if q["in_flight"]:
        return ("wait", f"{len(q['in_flight'])}个在途: {','.join(w['id'] for w in q['in_flight'])}")
    if q["blocked_on_user"]:
        return ("ask_user", q["blocked_on_user"][0])
    for wp in q["pending"]:
        deps_ok = all(d in q["completed"] for d in wp["deps"])
        if deps_ok:
            return ("dispatch", wp)
    if q["pending"]:
        return ("wait", f"待依赖: {','.join(w['id']+'/'+','.join(w['deps']) for w in q['pending'])}")
    return ("done", None)

if __name__ == "__main__":
    q = load()
    t, p = next_action(q)
    print(json.dumps({"action": t, "payload": p if isinstance(p, str) else p}, ensure_ascii=False))
