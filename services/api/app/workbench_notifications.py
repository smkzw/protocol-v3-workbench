"""Lightweight durable workbench notifications (JSONL).

Used when research-pipeline (and similar) need an in-app notice that the
computed WorkbenchInbox can surface. Prefer real inbox projection over a
separate UI channel.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_LOCK = threading.Lock()

# Align with main.RUNTIME_DIR: PROJECT_ROOT is parents[5] from app/main.py
# (…/医学经理工作台), not the implementation/workbench tree.
DEFAULT_NOTIFICATIONS_PATH = Path(
    os.environ.get(
        "WORKBENCH_RUNTIME_DIR",
        str(Path(__file__).resolve().parents[5] / "runtime"),
    )
) / "notifications" / "workbench_notifications.jsonl"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def notifications_path(runtime_dir: Path | str | None = None) -> Path:
    if runtime_dir is None:
        return DEFAULT_NOTIFICATIONS_PATH
    return Path(runtime_dir) / "notifications" / "workbench_notifications.jsonl"


def append_notification(
    *,
    project_id: str,
    title: str,
    summary: str = "",
    module: str = "medical_writing",
    item_type: str = "notice",
    source_type: str = "research_pipeline",
    source_id: str = "",
    priority: str = "medium",
    target_page: str = "writing",
    target_id: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    """Append one notification row. Idempotent on (project_id, source_id, title)."""
    target = path or DEFAULT_NOTIFICATIONS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    created_at = _utcnow_iso()
    source_id = source_id or f"{project_id}:{title}"
    item_id = f"notice:{source_type}:{source_id}"
    record = {
        "item_id": item_id,
        "project_id": project_id,
        "module": module,
        "module_label": "医学写作" if module == "medical_writing" else module,
        "item_type": item_type,
        "source_type": source_type,
        "source_id": source_id,
        "title": title,
        "summary": summary,
        "priority": priority,
        "status": "待查看",
        "needs_action": True,
        "action_label": "查看",
        "target_page": target_page,
        "target_id": target_id or project_id,
        "source_version": created_at,
        "created_at": created_at,
        "updated_at": created_at,
    }
    with _LOCK:
        if _already_present(target, project_id=project_id, source_id=source_id, title=title):
            return record
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def _already_present(
    path: Path, *, project_id: str, source_id: str, title: str
) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    str(row.get("project_id") or "") == project_id
                    and str(row.get("source_id") or "") == source_id
                    and str(row.get("title") or "") == title
                ):
                    return True
    except OSError:
        return False
    return False


def list_notifications(
    project_id: str, *, path: Path | None = None, limit: int = 80
) -> list[dict[str, Any]]:
    target = path or DEFAULT_NOTIFICATIONS_PATH
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with target.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(row.get("project_id") or "") != project_id:
                    continue
                rows.append(row)
    except OSError:
        return []
    # Latest wins per item_id
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        item_id = str(row.get("item_id") or "")
        if not item_id:
            continue
        by_id[item_id] = row
    ordered = sorted(
        by_id.values(),
        key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""),
        reverse=True,
    )
    return ordered[: max(1, int(limit))]


def notify_corpus_ready(project_id: str, *, path: Path | None = None) -> dict[str, Any]:
    return append_notification(
        project_id=project_id,
        title="研究语料已准备完毕，可进入研究设计引导",
        summary="公开检索、分诊、原文准备与一轮分析已完成，语料门已就绪。可进入证据化研究设计推荐。",
        source_type="research_pipeline",
        source_id=f"corpus_ready:{project_id}",
        priority="high",
        target_page="writing",
        target_id=project_id,
        path=path,
    )
