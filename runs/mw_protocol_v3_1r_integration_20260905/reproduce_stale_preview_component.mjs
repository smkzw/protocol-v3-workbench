// Actual React component SSR, synthetic contract-valid stale payload. No browser/service.
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import Module from 'node:module';
import { spawnSync } from 'node:child_process';
const frontendPackage = fileURLToPath(new URL('../../frontend/package.json', import.meta.url));
const require = createRequire(frontendPackage);
const { build } = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const source = fileURLToPath(new URL('../../frontend/src/features/medical-writing/MedicalWritingPreviewPanel.jsx', import.meta.url));
const result = await build({ entryPoints: [source], bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react-dom', 'lucide-react'] });
const compiled = new Module(source);
compiled.filename = source;
compiled.paths = Module._nodeModulePaths(fileURLToPath(new URL('../../frontend', import.meta.url)));
compiled._compile(result.outputFiles[0].text, source);
const preview = {
  project_id: 'synthetic_project', document_id: 'synthetic_document',
  preview_status: 'stale', page_count_basis: 'microsoft_word_receipt',
  snapshot_sha256: 'a'.repeat(64), word_verified_snapshot_sha256: 'b'.repeat(64),
  page_count: 1, pages: [{page_number: 1, orientation: 'portrait', width_twips: 12240, height_twips: 15840, estimated: false}], warning: '旧回执与当前正文不同',
};
const validation = spawnSync(fileURLToPath(new URL('./venv/bin/python', import.meta.url)), ['-c', 'import sys; from packages.contracts.workbench_contracts import MedicalWritingDocumentPreview; MedicalWritingDocumentPreview.model_validate_json(sys.stdin.read())'], {input: JSON.stringify(preview), encoding: 'utf8', cwd: fileURLToPath(new URL('../../', import.meta.url)), env: {...process.env, PYTHONDONTWRITEBYTECODE: '1'}});
if (validation.status !== 0) throw new Error(`synthetic contract invalid: ${validation.stderr}`);
const html = renderToStaticMarkup(React.createElement(compiled.exports.MedicalWritingPreviewPanel, {preview}));
console.log(JSON.stringify({
  input_status: preview.preview_status,
  backend_contract_validated: true,
  shows_stale_heading: html.includes('核验已过期'),
  renders_verified_tone: html.includes('medical-writing-preview-panel verified'),
  claims_final_layout_basis: html.includes('可作为最终版式依据'),
  check_is: 'actual React component static markup, not browser visual acceptance',
}, null, 2));
if (!html.includes('核验已过期') || !html.includes('可作为最终版式依据')) throw new Error('observed contradiction no longer reproduced; re-review current source');
