#!/bin/zsh
# Build the GenOffice docs renderer as a browser bundle and install it into
# the protocol-v3 frontend (T10).  Run from the protocol-v3 repo root:
#   scripts/qc/protocol_v3/build_genoffice_renderer.sh
set -euo pipefail

GENOFFICE="${GENOFFICE_ROOT:-$(cd "$(dirname "$0")/../../../.." && pwd)/genoffice-upstream}"
FRONTEND="$(cd "$(dirname "$0")/../../.." && pwd)/frontend"
GENOFFICE="$(cd "$GENOFFICE" && pwd)"

cd "$GENOFFICE/apps/docs"
DOCS_DEV_PORT=5199 npx vite build --base=/genoffice/ --config vite.renderer.config.ts

DEST="$FRONTEND/public/genoffice"
SRC="$GENOFFICE/apps/docs/src/renderer/dist"
rm -rf "$DEST/index.html" "$DEST/assets"
mkdir -p "$DEST"
cp -R "$SRC"/* "$DEST/"

# Inject the bridge shim before the module script so window.desktop exists
# when the renderer boots.
/opt/homebrew/bin/python3 - "$DEST/index.html" <<'PY'
import re, sys
from pathlib import Path
path = Path(sys.argv[1])
html = path.read_text(encoding='utf-8')
shim = '<script src="./bridge-shim.js"></script>'
if shim not in html:
    html = re.sub(r'(<script type="module"[^>]*>)', shim + r'\1', html, count=1)
    path.write_text(html, encoding='utf-8')
style = '<link rel="stylesheet" href="./embedded.css">'
if style not in html:
    html = html.replace('</head>', style + '</head>')
path.write_text(html, encoding='utf-8')
print('shim and embedded styles injected')
PY
print "GenOffice renderer installed at $DEST"
