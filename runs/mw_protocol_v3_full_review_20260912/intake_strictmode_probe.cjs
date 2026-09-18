const fs=require('node:fs');const path=require('node:path');const Module=require('node:module');
const root=path.resolve(__dirname,'../..');const req=Module.createRequire(path.join(root,'frontend/package.json'));
const {JSDOM}=req('jsdom');const dom=new JSDOM('<!doctype html><body></body>',{url:'http://localhost/'});
for(const k of ['window','document','HTMLElement','Node','File','FormData','Event','MouseEvent'])globalThis[k]=dom.window[k];
Object.defineProperty(globalThis,'navigator',{value:dom.window.navigator,configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=req('react');const {render,fireEvent,cleanup}=req('@testing-library/react');
const {transformSync}=req('esbuild');
const filename=path.join(root,'frontend/src/features/medical-writing/MedicalWritingSynopsisProjectIntake.jsx');
const compiled=new Module(filename);compiled.filename=filename;compiled.paths=Module._nodeModulePaths(path.dirname(filename));
compiled._compile(transformSync(fs.readFileSync(filename,'utf8'),{loader:'jsx',jsx:'automatic',format:'cjs'}).code,filename);
async function trial(strict){
 let resolveUpload;const uploaded=new Promise(r=>resolveUpload=r);let calls=[];
 globalThis.fetch=async(url)=>{calls.push(url);resolveUpload();return {ok:true,json:async()=>url.endsWith('/result')?{source:{source_id:'test-source',validation_warnings:[]},proposed_framing:{investigational_product:'review-only',indication:'review-only',study_phase:'II期'},proposed_picos:{},proposed_synopsis_text:'本地组件诊断。'}:{intake_id:'test-intake',idempotency_key:'test-operation',status:'review_ready'}}};
 const element=React.createElement(compiled.exports.MedicalWritingSynopsisProjectIntake,{});
 const view=render(strict?React.createElement(React.StrictMode,{},element):element);
 const file=new File(['test'],'review-only.docx');file.arrayBuffer=async()=>Buffer.from('test').buffer.slice(0,4);
 fireEvent.change(view.container.querySelector('input[type=file]'),{target:{files:[file]}});
 await React.act(async()=>{fireEvent.click(view.getByText('导入并提取'));await uploaded;});
 const result={strict,calls: calls.length,result_requested:calls.some(x=>x.endsWith('/result')),stuck_in_progress:!!view.container.querySelector('.file-first-progress'),visible_text:view.container.textContent};
 cleanup();return result;
}
(async()=>{const result=[await trial(false),await trial(true)];fs.writeFileSync(path.join(__dirname,'intake_strictmode_probe.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result.map(({visible_text,...rest})=>rest),null,2));})().catch(e=>{console.error(e);process.exitCode=1;});
