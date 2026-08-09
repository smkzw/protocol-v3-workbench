#!/usr/bin/env python3

import json
import re
import sys
from pathlib import Path


def split_chapters(text: str):
    matches = list(re.finditer(r"^##\s+(.+)$", text, flags=re.MULTILINE))
    chapters = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chapters.append((match.group(1).strip(), text[match.start():end]))
    return chapters


def main():
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/medical_monitoring_manual/医学监查子系统说明书.md")
    text = source.read_text(encoding="utf-8")
    chapters = split_chapters(text)
    mermaid_count = len(re.findall(r"^```mermaid\s*$", text, flags=re.MULTILINE))
    table_count = len(re.findall(r"^\|(?:\s*:?-+:?\s*\|)+\s*$", text, flags=re.MULTILINE))
    example_count = len(re.findall(r"(?m)^\s*\*(?:\*?)示例[：:]", text))
    core = []
    missing_examples = []
    for title, body in chapters:
        number_match = re.match(r"(\d+)(?:\.|、)", title)
        if number_match and 8 <= int(number_match.group(1)) <= 24:
            core.append(title)
            if not re.search(r"(?m)^\s*\*(?:\*?)示例[：:]", body):
                missing_examples.append(title)

    forbidden = {}
    for pattern in (
        r"&&",
        r"@@",
        r"/Users/",
        r"RUX-03-002|MY009|MG-K10",
        r"Reasonix|deepseek-v4-pro|MiniMax-M3|Kimi",
        r"主笔|会商源包|真实项目运行日志|logs/subsystems",
        r"Dr\.Wang|monsrcv_[A-Za-z0-9_]+",
        r"风险状态机|普适阈值|强制术语边界",
        r"自动确认(?:为|是)?(?:AE|MH|PD)",
        r"确保零漏报",
        r"profile\?metrics=",
        r"site_id=DEMO[A-Za-z0-9_-]*",
        r"risk_id=R-\d+",
        r"来源表示例",
    ):
        hits = re.findall(pattern, text)
        if hits:
            forbidden[pattern] = len(hits)

    checks = {
        "bytes_at_least_75000": len(text.encode("utf-8")) >= 75000,
        "chapters_at_least_30": len(chapters) >= 30,
        "mermaid_at_least_10": mermaid_count >= 10,
        "tables_at_least_20": table_count >= 20,
        "examples_at_least_20": example_count >= 20,
        "core_chapters_have_examples": not missing_examples,
        "no_forbidden_patterns": not forbidden,
        "section_16_3_is_project_scoped": "系统不维护可跨项目直接套用的禁限用药清单" in text and "说明性项目配置示例" in text,
        "profile_api_uses_project_metric_set": "profile?metric_set_id={metric_set_id}" in text and "profile?metrics=" not in text,
    }
    result = {
        "source": str(source),
        "bytes": len(text.encode("utf-8")),
        "chapters": len(chapters),
        "mermaid": mermaid_count,
        "tables": table_count,
        "examples": example_count,
        "core_chapters": core,
        "missing_core_examples": missing_examples,
        "forbidden": forbidden,
        "checks": checks,
        "ok": all(checks.values()),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
