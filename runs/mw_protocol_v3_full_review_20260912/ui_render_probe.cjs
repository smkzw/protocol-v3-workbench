// Read current components and render locally; no API, browser, or service.
const fs=require('node:fs'); const path=require('node:path'); const Module=require('node:module');
const root=path.resolve(__dirname,'../..');
const req=Module.createRequire(path.join(root,'frontend/package.json'));
const React=req('react'); const {renderToStaticMarkup}=req('react-dom/server');
const {transformSync}=req('esbuild');
const filename=path.join(root,'frontend/src/features/medical-writing/MedicalWritingPreviewPanel.jsx');
const code=transformSync(fs.readFileSync(filename,'utf8'),{loader:'jsx',jsx:'automatic',format:'cjs'}).code;
const compiled=new Module(filename); compiled.filename=filename;compiled.paths=Module._nodeModulePaths(path.dirname(filename));compiled._compile(code,filename);
const Component=compiled.exports.MedicalWritingPreviewPanel;
const html=renderToStaticMarkup(React.createElement(Component,{preview:{page_count_basis:'microsoft_word_receipt',preview_status:'stale',page_count:42,snapshot_sha256:'a'.repeat(64),pages:[]}}));
fs.writeFileSync(path.join(__dirname,'preview_stale_render.html'),html);
const result={input:{page_count_basis:'microsoft_word_receipt',preview_status:'stale'},rendered_stale_title:html.includes('核验已过期'),rendered_verified_class:html.includes('medical-writing-preview-panel verified'),claims_final_layout_basis:html.includes('可作为最终版式依据')};
fs.writeFileSync(path.join(__dirname,'ui_render_probe.json'),JSON.stringify(result,null,2)+'\n'); console.log(JSON.stringify(result,null,2));
