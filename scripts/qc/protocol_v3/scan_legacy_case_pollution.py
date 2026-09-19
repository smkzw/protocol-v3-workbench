"""Read-only legacy pollution scan (requirements-v2 T03 / A26).

Locates records likely touched by the case-fitting recommendations that left
the generic path in 28d1f9c.  Read-only: opens every SQLite file with
mode=ro, never mutates, never rewrites history.  Identical values alone do
not prove pollution, so every finding is a reconciliation candidate with its
provenance, not a verdict.

Classification:
- leaked      … tokens that only the leaked validation recommendation could
                produce (case drug, fixed rates, fixed storage, NRI/tipping)
- cross_hit   … CRSwNP-domain tokens in a project whose confirmed indication
                is not CRSwNP
- note        … CRSwNP-domain tokens inside the real CRSwNP reference project
                (legitimate content, listed for completeness)
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

LEAKED_TOKENS = ('合成药X', '临床缓解率', '第24周', '2℃～8℃', '8%上调',
                 '无应答插补', 'tipping point', '首次概念验证',
                 '（设计假设修订）', '（适用性修正）')
CRSWNP_TOKENS = ('慢性鼻窦炎', '鼻息肉', '鼻窦', 'SNOT-22')
CRSWNP_MARKERS = ('慢性鼻窦炎', '鼻息肉', 'CRSwNP')


def _classify(text: str, project_hint: str) -> list[tuple[str, str]]:
    hits = []
    is_crswnp_project = any(marker in project_hint for marker in CRSWNP_MARKERS)
    for token in LEAKED_TOKENS:
        if token in text:
            hits.append(('leaked', token))
    for token in CRSWNP_TOKENS:
        if token in text:
            hits.append(('note' if is_crswnp_project else 'cross_hit', token))
    return hits


def _project_hint(body: dict) -> str:
    return json.dumps(body, ensure_ascii=False)[:4000]


def _snippet(text: str, token: str, span: int = 60) -> str:
    at = text.find(token)
    if at < 0:
        return ''
    return text[max(0, at - span):at + len(token) + span]


def scan_db(db_path: Path) -> dict:
    uri = f'file:{db_path}?mode=ro'
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    findings = []
    try:
        # Per-project domain map: a project whose aggregate bodies mention the
        # CRSwNP indication anywhere IS a CRSwNP study — its ENT-scale tokens
        # are legitimate content, not cross-domain pollution.
        crswnp_projects = set()
        for row in con.execute('SELECT project_id, body_json AS body FROM aggregate_revision'):
            body = row['body'] or ''
            if any(marker in body for marker in CRSWNP_MARKERS):
                crswnp_projects.add(row['project_id'])
        for table, id_col, body_col in (
                ('aggregate_revision', 'aggregate_id', 'body_json'),
                ('event_stream', 'domain_event_id', 'body_json')):
            try:
                rows = con.execute(
                    f'SELECT project_id, {id_col} AS record_id, {body_col} AS body FROM {table}')
            except sqlite3.OperationalError as exc:
                findings.append({'db': str(db_path), 'table': table,
                                 'kind': 'error', 'detail': str(exc)})
                continue
            for row in rows:
                body = row['body'] or ''
                is_crswnp_project = row['project_id'] in crswnp_projects
                hits = [('leaked', token) for token in LEAKED_TOKENS if token in body]
                hits.extend(('note' if is_crswnp_project else 'cross_hit', token)
                            for token in CRSWNP_TOKENS if token in body)
                for kind, token in hits:
                    findings.append({
                        'db': str(db_path), 'table': table, 'kind': kind,
                        'project_id': row['project_id'], 'record_id': row['record_id'],
                        'token': token, 'snippet': _snippet(body, token)})
    finally:
        con.close()
    return {'db': str(db_path), 'findings': findings}


def main(argv: list[str]) -> int:
    out_path = Path(argv[1]) if len(argv) > 1 else Path('legacy_pollution_scan.json')
    targets = [Path(p) for p in argv[2:]] or sorted(
        p for p in Path('runs').rglob('*.sqlite') if not p.name.endswith('-wal'))
    report = {'schema_version': 'legacy-pollution-scan.v1',
              'generated_at': datetime.now(timezone.utc).isoformat(),
              'mode': 'read-only',
              'databases': [scan_db(db) for db in targets]}
    summary = {}
    for db in report['databases']:
        for finding in db['findings']:
            summary[finding['kind']] = summary.get(finding['kind'], 0) + 1
    report['summary'] = summary
    report['reconciliation_note'] = (
        '每条 finding 均为核对候选而非结论：leaked 建议由用户按当前确认设计重核；'
        'cross_hit 建议按该项目真实适应症重核；note 为真实CRSwNP项目合法内容。'
        '不自动修改任何事实、事件或稿件（A26）。')
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), '->', out_path)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
