#!/bin/bash
# 一键健康检查：系统状态 + 成品文件 + 计划状态 + Git状态
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "=== 1. 服务状态 ==="
B=$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:5274/openapi.json 2>/dev/null)
V=$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://localhost:5175/ 2>/dev/null)
echo "  后端(5274): $B  前端(5175): $V"

echo "=== 2. 成品文件 ==="
for f in "runs/mw_protocol_v3_unified_tests_20260919/acceptance_evidence/11_synopsis_typography.docx" \
         "runs/mw_protocol_v3_unified_tests_20260919/acceptance_evidence/10_soa_tuned.docx" \
         "runs/mw_protocol_v3_unified_tests_20260919/acceptance_evidence/使用说明.md"; do
  [ -f "$f" ] && echo "  ✓ $f" || echo "  ✗ 缺少 $f"
done

echo "=== 3. 研究事实与计划状态 ==="
python3 -c "
import json, urllib.request
S='study%3Av3%3A97f28c85ce9d55d671c1878429eb7998'
P='project%3Abrowser-acceptance-9'
try:
    with urllib.request.urlopen(f'http://127.0.0.1:5274/api/projects/{P}/protocol-workflow/study-definitions/{S}/manuscript-plan', timeout=15) as r:
        d = json.loads(r.read())
    print(f'  计划就绪: {d[\"all_applicable_inputs_ready\"]}  章节: {len(d[\"chapters\"])}')
except Exception as e:
    print(f'  后端未响应: {e}')
"

echo "=== 4. Git状态 ==="
echo "  HEAD: $(git log --oneline -1 2>/dev/null | cut -c1-40)"
echo "  未提交: $(git status --short 2>/dev/null | wc -l | tr -d ' ')"

echo "=== 完成 ==="
