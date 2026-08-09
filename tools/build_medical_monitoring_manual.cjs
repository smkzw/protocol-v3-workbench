#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { marked } = require("marked");

const root = path.resolve(__dirname, "..");
const sourcePath = process.argv[2] || path.join(root, "docs/medical_monitoring_manual/医学监查子系统说明书.md");
const outputPath = process.argv[3] || path.join(root, "docs/medical_monitoring_manual/医学监查子系统说明书.html");
const logoPath = path.join(root, "frontend/src/assets/header_logo.png");
const mermaidPath = path.join(root, "tools/vendor/mermaid-11.16.0.min.js");

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function plainText(value) {
  return String(value)
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^\)]+\)/g, "$1")
    .replace(/[\*_~]/g, "")
    .trim();
}

function decodeHtml(value) {
  return String(value)
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'")
    .replaceAll("&amp;", "&");
}

function slugBase(value) {
  const normalized = plainText(value)
    .toLowerCase()
    .replace(/[\s/]+/g, "-")
    .replace(/[^\p{Letter}\p{Number}\-]+/gu, "")
    .replace(/^-+|-+$/g, "");
  return normalized || "section";
}

function withHeadingAnchors(markdown) {
  const seen = new Map();
  const headings = [];
  const body = markdown.replace(/^(#{1,4})\s+(.+)$/gm, (_, hashes, rawTitle) => {
    const title = plainText(rawTitle);
    const base = slugBase(title);
    const count = (seen.get(base) || 0) + 1;
    seen.set(base, count);
    const id = count === 1 ? base : `${base}-${count}`;
    const level = hashes.length;
    headings.push({ level, title, id });
    return `<h${level} id="${escapeHtml(id)}" tabindex="-1">${escapeHtml(title)}<a class="heading-link" href="#${escapeHtml(id)}" aria-label="复制本节链接">#</a></h${level}>`;
  });
  return { body, headings };
}

function buildToc(headings) {
  return headings
    .filter((item) => item.level >= 2 && item.level <= 3)
    .map((item) => `<a class="toc-link toc-level-${item.level}" href="#${escapeHtml(item.id)}" data-target="${escapeHtml(item.id)}">${escapeHtml(item.title)}</a>`)
    .join("\n");
}

if (!fs.existsSync(sourcePath)) throw new Error(`Markdown source not found: ${sourcePath}`);
if (!fs.existsSync(logoPath)) throw new Error(`Official CMS logo not found: ${logoPath}`);

const source = fs.readFileSync(sourcePath, "utf8");
const { body, headings } = withHeadingAnchors(source);
marked.setOptions({ gfm: true, breaks: false });
let rendered = marked.parse(body);
let mermaidCount = 0;
rendered = rendered.replace(/<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g, (_, encoded) => {
  mermaidCount += 1;
  return `<figure class="diagram-frame interactive-shell" data-diagram-index="${mermaidCount}"><div class="content-toolbar"><strong>交互图 ${mermaidCount}</strong><span class="toolbar-hint">已适配当前视野 · 可放大和全屏查看</span><div class="toolbar-actions"><button class="tool-button collapse-control" type="button" title="收起或展开图形" aria-expanded="true">▾</button><button class="tool-button zoom-out-control" type="button" title="缩小">−</button><button class="tool-button zoom-reset-control" type="button" title="恢复完整视图">↺</button><button class="tool-button zoom-in-control" type="button" title="放大">＋</button><button class="tool-button fullscreen-control" type="button" title="全屏查看">⛶</button></div></div><div class="diagram-viewport"><div class="mermaid">${escapeHtml(decodeHtml(encoded))}</div></div></figure>`;
});
const logoMime = path.extname(logoPath).toLowerCase() === ".png" ? "image/png" : "image/svg+xml";
const logoData = `data:${logoMime};base64,${fs.readFileSync(logoPath).toString("base64")}`;
const title = headings.find((item) => item.level === 1)?.title || "医学监查子系统说明书";
const topChapters = headings.filter((item) => item.level === 2);
const sectionReferenceMap = {};
headings.forEach((item) => {
  const numbered = item.title.match(/^(\d+(?:\.\d+)*)\.?\s/);
  if (numbered) sectionReferenceMap[numbered[1]] = item.id;
  const appendix = item.title.match(/附录\s*([A-E])/i);
  if (appendix) sectionReferenceMap[`附录${appendix[1].toUpperCase()}`] = item.id;
});

const html = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="only light">
  <title>${escapeHtml(title)}</title>
  <style>
    :root{color-scheme:only light;--kz-orange:#FF9900;--kz-yellow:#FFCC00;--kz-ink:#1F252D;--kz-text:#3E4651;--kz-muted:#687383;--kz-line:#DDE2E8;--kz-soft:#F4F6F8;--kz-paper:#FFFFFF;--kz-risk:#C00000;--kz-ok:#2E7D32;--kz-blue:#407AAA;--sidebar:336px}
    *,*::before,*::after{box-sizing:border-box}
    html{scroll-behavior:smooth;background:var(--kz-soft)}
    body{margin:0;color:var(--kz-text);background:var(--kz-soft);font-family:"Microsoft YaHei",Arial,"Noto Sans SC",sans-serif;font-size:16px;line-height:1.72}
    a{color:var(--kz-blue);text-underline-offset:3px}
    .progress{position:fixed;z-index:50;left:0;top:0;height:3px;width:0;background:var(--kz-orange)}
    .sidebar{position:fixed;inset:0 auto 0 0;width:var(--sidebar);background:#fff;border-right:1px solid var(--kz-line);display:flex;flex-direction:column;z-index:20}
    .brand{padding:24px 24px 18px;border-top:5px solid var(--kz-orange);border-bottom:1px solid var(--kz-line)}
    .brand img{display:block;width:188px;height:auto;object-fit:contain}
    .brand .book-label{margin-top:15px;color:var(--kz-muted);font-size:13px}
    .brand strong{display:block;margin-top:3px;color:var(--kz-ink);font-size:18px;line-height:1.35}
    .search{padding:16px 18px 10px}
    .search-wrap{display:grid;grid-template-columns:1fr 36px;border:1px solid #C9D0D8;background:#fff}
    .search input{width:100%;border:0;padding:10px 12px;font:inherit;outline:none;min-width:0}
    .search button{border:0;border-left:1px solid var(--kz-line);background:var(--kz-soft);cursor:pointer;font-size:17px}
    .search-status{min-height:22px;margin:5px 2px 0;color:var(--kz-muted);font-size:12px}
    .toc{padding:4px 12px 24px;overflow:auto;overscroll-behavior:contain}
    .toc-link{display:block;border-left:3px solid transparent;padding:7px 10px;color:#4E5865;text-decoration:none;font-size:14px;line-height:1.45}
    .toc-link:hover{background:#F7F8FA;color:var(--kz-ink)}
    .toc-link.active{border-left-color:var(--kz-orange);background:#FFF8ED;color:#9A5100;font-weight:700}
    .toc-level-3{padding-left:24px;color:#707A87;font-size:13px}
    .main{margin-left:var(--sidebar);min-height:100vh}
    .topbar{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;gap:18px;padding:12px 32px;background:rgba(255,255,255,.96);border-bottom:1px solid var(--kz-line);backdrop-filter:blur(10px)}
    .crumb{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--kz-muted);font-size:13px}
    .top-actions{display:flex;gap:8px;flex:0 0 auto}
    .icon-button{width:36px;height:36px;border:1px solid #CDD3DA;background:#fff;color:var(--kz-text);cursor:pointer;font-size:17px}
    .icon-button:hover{border-color:var(--kz-orange);color:#9A5100}
    article{max-width:1180px;margin:0 auto;padding:46px 64px 100px;background:var(--kz-paper);min-height:100vh}
    h1,h2,h3,h4{color:var(--kz-ink);letter-spacing:0;scroll-margin-top:78px;position:relative}
    h1{margin:0 0 30px;padding:0 0 24px;border-bottom:2px solid var(--kz-orange);font-size:clamp(30px,3vw,42px);line-height:1.25}
    h1::after{content:"";position:absolute;left:0;bottom:-2px;width:110px;height:5px;background:var(--kz-yellow)}
    h2{margin:58px 0 22px;padding-top:8px;font-size:clamp(24px,2.4vw,31px);line-height:1.35}
    h2::before{content:"";position:absolute;left:-20px;top:15px;width:5px;height:26px;background:var(--kz-orange)}
    h3{margin:38px 0 16px;font-size:clamp(20px,1.9vw,24px);line-height:1.4}
    h4{margin:27px 0 12px;font-size:18px;line-height:1.45}
    .heading-link{margin-left:9px;color:#BAC1C9;text-decoration:none;font-size:.64em;font-weight:400;opacity:0}
    h1:hover .heading-link,h2:hover .heading-link,h3:hover .heading-link,h4:hover .heading-link{opacity:1}
    p{margin:0 0 16px}
    ul,ol{margin:8px 0 18px;padding-left:27px}
    li{margin:5px 0}
    strong{color:#20262E}
    blockquote{margin:22px 0;padding:14px 18px;border-left:4px solid var(--kz-orange);background:#FFF8ED;color:#4B5561}
    code{padding:2px 5px;border-radius:3px;background:#F0F2F5;color:#9B3D00;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em}
    pre{overflow:auto;padding:16px;background:#20262E;color:#F7F8FA;border-radius:4px;line-height:1.55}
    pre code{padding:0;background:transparent;color:inherit}
    .interactive-shell{position:relative;margin:24px 0 30px;border:1px solid #D6DCE3;background:#fff;box-shadow:0 1px 2px rgba(31,37,45,.04)}
    .content-toolbar{min-height:46px;display:flex;align-items:center;gap:12px;padding:7px 9px 7px 14px;border-bottom:1px solid var(--kz-line);background:#F7F8FA;color:var(--kz-ink)}
    .content-toolbar strong{font-size:14px;white-space:nowrap}
    .toolbar-hint{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--kz-muted);font-size:12px}
    .toolbar-actions{display:flex;align-items:center;gap:4px;margin-left:auto}
    .tool-button{width:32px;height:32px;display:inline-grid;place-items:center;border:1px solid transparent;background:transparent;color:#4A5562;cursor:pointer;font:700 16px/1 "Microsoft YaHei",Arial,sans-serif}
    .tool-button:hover,.tool-button:focus-visible{border-color:#C6CDD5;background:#fff;color:#9A5100;outline:none}
    .diagram-frame{padding:0;overflow:visible}
    .diagram-viewport{min-height:180px;overflow:hidden;padding:18px;cursor:default;overscroll-behavior:contain;background:#FCFCFD}
    .diagram-viewport.can-pan{overflow:auto;cursor:grab}
    .diagram-viewport.is-dragging{cursor:grabbing;user-select:none}
    .diagram-frame .mermaid{display:flex;align-items:center;justify-content:center;width:100%;min-width:0;transition:opacity .18s ease}
    .diagram-frame svg{display:block;width:100%;max-width:100%;height:100%;max-height:100%;font-family:"Microsoft YaHei",Arial,"Noto Sans SC",sans-serif!important}
    .diagram-frame .node{cursor:pointer;transition:opacity .16s ease,filter .16s ease}
    .diagram-frame .node:hover,.diagram-frame .node:focus-visible{filter:drop-shadow(0 2px 5px rgba(31,37,45,.2));outline:none}
    .diagram-frame .mermaid.has-node-focus .node:not(.is-focused){opacity:.28}
    .diagram-frame .node.is-focused{filter:drop-shadow(0 3px 8px rgba(255,153,0,.42))}
    .diagram-frame.is-collapsed .diagram-viewport{display:none}
    .diagram-frame.is-collapsed .collapse-control{transform:rotate(-90deg)}
    .table-shell{overflow:visible}
    .table-viewport{overflow:auto;overscroll-behavior:contain}
    .table-shell.is-collapsed .table-viewport,.table-shell.is-collapsed .table-more{display:none}
    .table-shell.is-collapsed .collapse-control{transform:rotate(-90deg)}
    .table-shell.is-preview tbody tr:nth-child(n+9){display:none}
    .table-more{width:100%;padding:10px 14px;border:0;border-top:1px solid var(--kz-line);background:#FAFBFC;color:#5C6673;cursor:pointer;font:inherit;font-size:13px}
    .table-more:hover{background:#FFF8ED;color:#8B4B00}
    .table-shell.is-compact th,.table-shell.is-compact td{padding:6px 9px;font-size:13px;line-height:1.42}
    table{width:100%;border-collapse:collapse;font-size:15px;line-height:1.55}
    th,td{padding:10px 12px;border:1px solid var(--kz-line);vertical-align:top;text-align:left;min-width:110px}
    th{position:static;background:#F2F4F7;color:#252B33;font-weight:700}
    tbody tr:nth-child(even){background:#FAFBFC}
    .interactive-shell.is-expanded{position:fixed;inset:18px;z-index:1000;margin:0;display:flex;flex-direction:column;background:#fff;box-shadow:0 18px 60px rgba(20,26,34,.28)}
    .interactive-shell.is-expanded .diagram-viewport,.interactive-shell.is-expanded .table-viewport{flex:1;min-height:0;max-height:none}
    .interactive-shell.is-expanded .table-viewport th{position:sticky;top:0;z-index:2}
    body.has-expanded-content{overflow:hidden}
    body.has-expanded-content::before{content:"";position:fixed;inset:0;z-index:999;background:rgba(27,33,41,.54)}
    hr{border:0;border-top:1px solid var(--kz-line);margin:40px 0}
    mark{background:#FFE9A8;color:inherit;padding:0 1px}
    .chapter-nav{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;margin-top:70px;padding-top:24px;border-top:1px solid var(--kz-line)}
    .chapter-nav a{display:flex;min-height:62px;align-items:center;padding:12px 16px;border:1px solid var(--kz-line);text-decoration:none;color:var(--kz-text);background:#fff}
    .chapter-nav a:last-child{justify-content:flex-end;text-align:right}
    .chapter-nav a:hover{border-color:var(--kz-orange)}
    .doc-footer{margin-top:38px;color:var(--kz-muted);font-size:12px;text-align:center}
    .back-top{position:fixed;right:24px;bottom:24px;width:42px;height:42px;border:1px solid #C9D0D8;background:#fff;color:var(--kz-text);cursor:pointer;opacity:0;pointer-events:none;transition:opacity .2s}
    .back-top.show{opacity:1;pointer-events:auto}
    @media(max-width:1050px){:root{--sidebar:292px}article{padding:38px 38px 90px}.topbar{padding-inline:20px}}
    @media(max-width:760px){.sidebar{position:static;width:100%;height:auto;max-height:48vh}.toc{max-height:28vh}.main{margin-left:0}.topbar{top:0}article{padding:30px 20px 80px}h2::before{left:-10px}.chapter-nav{grid-template-columns:1fr}.back-top{right:14px;bottom:14px}}
    @media print{.sidebar,.topbar,.progress,.back-top,.chapter-nav,.content-toolbar,.table-more{display:none!important}.main{margin:0}article{max-width:none;padding:0;box-shadow:none}h1,h2,h3,h4{break-after:avoid}.interactive-shell{border:0;box-shadow:none}.diagram-viewport,.table-viewport{overflow:visible;padding:0}table,blockquote,pre{break-inside:avoid}a{color:inherit;text-decoration:none}.heading-link{display:none}}
  </style>
</head>
<body>
  <div class="progress" id="progress"></div>
  <aside class="sidebar">
    <div class="brand"><img src="${logoData}" alt="CMS 康哲药业"><div class="book-label">AI 全流程医学经理工作台</div><strong>医学监查子系统说明书</strong></div>
    <div class="search"><div class="search-wrap"><input id="searchInput" type="search" placeholder="检索正文" aria-label="检索正文"><button id="searchButton" title="检索">⌕</button></div><div class="search-status" id="searchStatus"></div></div>
    <nav class="toc" aria-label="文档目录">${buildToc(headings)}</nav>
  </aside>
  <main class="main">
    <div class="topbar"><div class="crumb" id="crumb">${escapeHtml(title)}</div><div class="top-actions"><button class="icon-button" id="printButton" title="打印或导出 PDF">⎙</button><button class="icon-button" id="copyButton" title="复制当前章节链接">⌁</button></div></div>
    <article id="article">${rendered}<nav class="chapter-nav" aria-label="章节翻页"><a id="prevChapter" href="#">上一章</a><a id="nextChapter" href="#">下一章</a></nav><div class="doc-footer">本说明书用于医学监查子系统的产品、科学规则与工程实施管理。系统输出均须经医学经理终审。</div></article>
  </main>
  <button class="back-top" id="backTop" title="返回顶部">↑</button>
  ${mermaidCount ? `<script id="mermaid-lib">${fs.readFileSync(mermaidPath, "utf8").replaceAll("</script", "<\\/script")}</script><script id="mermaid-init">mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'base',flowchart:{useMaxWidth:true,htmlLabels:true},themeVariables:{primaryColor:'#FFF4E2',primaryBorderColor:'#FF9900',primaryTextColor:'#1F252D',lineColor:'#687383',secondaryColor:'#F4F6F8',tertiaryColor:'#FFFFFF',fontFamily:'Microsoft YaHei, Arial, Noto Sans SC'}});const finalizeMermaid=()=>{const figures=[...document.querySelectorAll('.diagram-frame')];const rendered=figures.filter(figure=>figure.querySelector('svg')).length;const hasError=figures.some(figure=>/Syntax error in text|Parse error|mermaid version/i.test(figure.textContent));document.documentElement.dataset.mermaid=figures.length>0&&rendered===figures.length&&!hasError?'ready':'error'};window.__mermaidReady=mermaid.run({querySelector:'.mermaid'}).then(finalizeMermaid).catch(error=>{finalizeMermaid();document.documentElement.dataset.mermaidMessage=error&&error.message?error.message:String(error)});</script>` : ""}
  <script>
  (()=>{
    const sectionRefs=${JSON.stringify(sectionReferenceMap)};
    function addInternalReferenceLinks(){
      const article=document.getElementById('article');
      const walker=document.createTreeWalker(article,NodeFilter.SHOW_TEXT,{acceptNode(node){
        const parent=node.parentElement;
        if(!parent)return NodeFilter.FILTER_REJECT;
        if(parent.closest('a,code,pre,script,style,h1,h2,h3,h4,.content-toolbar'))return NodeFilter.FILTER_REJECT;
        return /§\\s*\\d|第\\s*\\d+\\s*章|附录\\s*[A-E]/.test(node.nodeValue)?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_REJECT;
      }});
      const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
      const pattern=/§\\s*(\\d+(?:\\.\\d+)*)|第\\s*(\\d+)\\s*章|附录\\s*([A-E])/g;
      nodes.forEach(node=>{
        const text=node.nodeValue;let match;let last=0;let changed=false;const fragment=document.createDocumentFragment();pattern.lastIndex=0;
        while((match=pattern.exec(text))){
          const key=match[1]||match[2]||('附录'+match[3]);const target=sectionRefs[key];if(!target)continue;
          fragment.append(document.createTextNode(text.slice(last,match.index)));
          const link=document.createElement('a');link.href='#'+target;link.className='section-reference';link.textContent=match[0];fragment.append(link);
          last=match.index+match[0].length;changed=true;
        }
        if(changed){fragment.append(document.createTextNode(text.slice(last)));node.replaceWith(fragment)}
      });
    }
    function setExpanded(shell,active){
      document.querySelectorAll('.interactive-shell.is-expanded').forEach(other=>{if(other!==shell){other.classList.remove('is-expanded');const otherButton=other.querySelector('.fullscreen-control');if(otherButton){otherButton.textContent='⛶';otherButton.title='全屏查看'}}});
      shell.classList.toggle('is-expanded',active);
      document.body.classList.toggle('has-expanded-content',active);
      const button=shell.querySelector('.fullscreen-control');
      if(button){button.textContent=active?'×':'⛶';button.title=active?'退出全屏':'全屏查看'}
    }
    function bindCollapse(shell){
      const button=shell.querySelector('.collapse-control');if(!button)return;
      button.addEventListener('click',()=>{const collapsed=shell.classList.toggle('is-collapsed');button.setAttribute('aria-expanded',String(!collapsed));button.title=collapsed?'展开内容':'收起内容'});
    }
    function bindFullscreen(shell){
      const button=shell.querySelector('.fullscreen-control');if(!button)return;
      button.addEventListener('click',()=>setExpanded(shell,!shell.classList.contains('is-expanded')));
    }
    function prepareTables(){
      document.querySelectorAll('table').forEach((table,index)=>{
        let shell=table.closest('.table-shell');
        if(!shell){
          shell=document.createElement('section');shell.className='table-shell interactive-shell';
          const toolbar=document.createElement('div');toolbar.className='content-toolbar';
          const rowCount=[...table.tBodies].reduce((total,body)=>total+body.rows.length,0);
          const contextHeading=[...document.querySelectorAll('h2,h3,h4')].filter(heading=>heading.compareDocumentPosition(table)&Node.DOCUMENT_POSITION_FOLLOWING).at(-1)?.textContent.replace('#','').trim()||'正文表格';
          toolbar.setAttribute('role','toolbar');toolbar.setAttribute('aria-label','表格操作');
          toolbar.innerHTML='<strong>表格 '+(index+1)+' · '+contextHeading+'</strong><span class="toolbar-hint">'+rowCount+' 行 · 可展开和全屏查看</span><div class="toolbar-actions"><button class="tool-button collapse-control" type="button" title="收起或展开表格" aria-label="收起或展开表格" aria-expanded="true">▾</button><button class="tool-button density-control" type="button" title="切换紧凑显示" aria-label="切换表格密度">≡</button><button class="tool-button fullscreen-control" type="button" title="全屏查看" aria-label="全屏查看表格">⛶</button></div>';
          const viewport=document.createElement('div');viewport.className='table-viewport';
          table.parentNode.insertBefore(shell,table);shell.append(toolbar,viewport);viewport.appendChild(table);
          table.setAttribute('aria-label',contextHeading);table.querySelectorAll('thead th').forEach(th=>th.setAttribute('scope','col'));
          if(rowCount>12){shell.classList.add('is-preview');const more=document.createElement('button');more.type='button';more.className='table-more';more.dataset.rowCount=String(rowCount);more.textContent='展开全部 '+rowCount+' 行';shell.appendChild(more)}
        }
        bindCollapse(shell);bindFullscreen(shell);
        const density=shell.querySelector('.density-control');if(density)density.addEventListener('click',()=>{const compact=shell.classList.toggle('is-compact');density.title=compact?'恢复舒适显示':'切换紧凑显示'});
        const more=shell.querySelector('.table-more');if(more)more.addEventListener('click',()=>{const preview=shell.classList.toggle('is-preview');const rowCount=more.dataset.rowCount||'';more.textContent=preview?'展开全部 '+rowCount+' 行':'收起至前 8 行'});
      });
    }
    function prepareDiagrams(){
      document.querySelectorAll('.diagram-frame').forEach((shell,index)=>{
        bindCollapse(shell);bindFullscreen(shell);
        const viewport=shell.querySelector('.diagram-viewport');const svg=shell.querySelector('svg');if(!viewport||!svg)return;
        const contextHeading=[...document.querySelectorAll('h2,h3,h4')].filter(heading=>heading.compareDocumentPosition(shell)&Node.DOCUMENT_POSITION_FOLLOWING).at(-1)?.textContent.replace('#','').trim()||'系统逻辑图';
        const toolbar=shell.querySelector('.content-toolbar');toolbar?.setAttribute('role','toolbar');toolbar?.setAttribute('aria-label','图形操作');
        const title=shell.querySelector('.content-toolbar strong');if(title)title.textContent='交互图 '+(index+1)+' · '+contextHeading;
        shell.setAttribute('role','group');shell.setAttribute('aria-label',contextHeading);
        const mermaid=shell.querySelector('.mermaid');let scale=1;let fittedHeight=240;
        svg.setAttribute('preserveAspectRatio','xMidYMid meet');
        function measureFit(){
          const viewBox=svg.viewBox&&svg.viewBox.baseVal;const ratio=viewBox&&viewBox.width>0?viewBox.height/viewBox.width:0.6;
          const availableWidth=Math.max(320,viewport.clientWidth-36);
          const viewportLimit=shell.classList.contains('is-expanded')?Math.max(320,window.innerHeight-122):Math.min(620,Math.max(360,window.innerHeight*.56));
          fittedHeight=Math.min(viewportLimit,Math.max(180,availableWidth*ratio));
        }
        function applyScale(){
          const zoomed=scale>1.001;
          mermaid.style.width=(scale*100)+'%';mermaid.style.flex='0 0 '+(scale*100)+'%';mermaid.style.height=(fittedHeight*scale)+'px';
          svg.style.width='100%';svg.style.height='100%';svg.style.maxWidth='100%';svg.style.maxHeight='100%';
          viewport.classList.toggle('can-pan',zoomed);viewport.style.overflow=zoomed?'auto':'hidden';
          shell.querySelector('.toolbar-hint').textContent=zoomed?'缩放 '+Math.round(scale*100)+'% · 可拖动查看细节':'已适配当前视野 · 图形完整显示';
        }
        function fitToViewport(){measureFit();applyScale();if(scale<=1.001)viewport.scrollTo({left:0,top:0})}
        shell.querySelector('.zoom-in-control')?.addEventListener('click',()=>{scale=Math.min(2.5,scale+.25);applyScale()});
        shell.querySelector('.zoom-out-control')?.addEventListener('click',()=>{scale=Math.max(.5,scale-.25);applyScale()});
        shell.querySelector('.zoom-reset-control')?.addEventListener('click',()=>{scale=1;svg.querySelectorAll('.node').forEach(node=>node.classList.remove('is-focused'));mermaid.classList.remove('has-node-focus');fitToViewport()});
        let dragging=false,startX=0,startY=0,startLeft=0,startTop=0;
        viewport.addEventListener('pointerdown',event=>{if(scale<=1.001||event.button!==0||event.target.closest('.node'))return;dragging=true;startX=event.clientX;startY=event.clientY;startLeft=viewport.scrollLeft;startTop=viewport.scrollTop;viewport.classList.add('is-dragging');viewport.setPointerCapture(event.pointerId)});
        viewport.addEventListener('pointermove',event=>{if(!dragging)return;viewport.scrollLeft=startLeft-(event.clientX-startX);viewport.scrollTop=startTop-(event.clientY-startY)});
        const stopDrag=()=>{dragging=false;viewport.classList.remove('is-dragging')};viewport.addEventListener('pointerup',stopDrag);viewport.addEventListener('pointercancel',stopDrag);
        svg.querySelectorAll('.node').forEach(node=>{node.setAttribute('tabindex','0');node.setAttribute('role','button');node.setAttribute('aria-label','查看图中节点：'+(node.textContent||'').replace(/\\s+/g,' ').trim());const toggle=()=>{const active=node.classList.toggle('is-focused');svg.querySelectorAll('.node').forEach(other=>{if(other!==node)other.classList.remove('is-focused')});mermaid.classList.toggle('has-node-focus',active);shell.querySelector('.toolbar-hint').textContent=active?'已聚焦：'+(node.textContent||'').replace(/\\s+/g,' ').trim():'缩放 '+Math.round(scale*100)+'% · 可拖动和全屏查看'};node.addEventListener('click',toggle);node.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();toggle()}})});
        svg.addEventListener('dblclick',()=>{svg.querySelectorAll('.node').forEach(node=>node.classList.remove('is-focused'));mermaid.classList.remove('has-node-focus');fitToViewport()});
        const classObserver=new MutationObserver(()=>{if(scale<=1.001)requestAnimationFrame(fitToViewport)});classObserver.observe(shell,{attributes:true,attributeFilter:['class']});
        window.addEventListener('resize',()=>{if(scale<=1.001)fitToViewport()},{passive:true});
        fitToViewport();
      });
    }
    function prepareInteractiveContent(){addInternalReferenceLinks();prepareTables();prepareDiagrams();document.documentElement.dataset.interactive='ready'}
    if(window.__mermaidReady)window.__mermaidReady.then(prepareInteractiveContent);else prepareInteractiveContent();
    document.addEventListener('keydown',event=>{if(event.key==='Escape'){const expanded=document.querySelector('.interactive-shell.is-expanded');if(expanded)setExpanded(expanded,false)}});
    const links=[...document.querySelectorAll('.toc-link')];
    const chapters=${JSON.stringify(topChapters)};
    const crumb=document.getElementById('crumb');
    const progress=document.getElementById('progress');
    const backTop=document.getElementById('backTop');
    const prev=document.getElementById('prevChapter');
    const next=document.getElementById('nextChapter');
    let currentId=chapters[0]?.id||'';
    function setCurrent(id){
      const active=links.find(link=>link.dataset.target===id)||links.filter(link=>{const el=document.getElementById(link.dataset.target);return el?el.getBoundingClientRect().top<=110:false}).at(-1);
      links.forEach(link=>link.classList.toggle('active',link===active));
      if(active){active.scrollIntoView({block:'nearest'});crumb.textContent=active.textContent.trim()}
      const chapterEls=chapters.map(ch=>document.getElementById(ch.id));
      const idx=Math.max(0,chapterEls.findLastIndex(el=>el?el.getBoundingClientRect().top<=120:false));
      currentId=chapters[idx]?.id||currentId;
      const p=chapters[idx-1],n=chapters[idx+1];
      prev.style.visibility=p?'visible':'hidden';next.style.visibility=n?'visible':'hidden';
      if(p){prev.href='#'+p.id;prev.textContent='← '+p.title}if(n){next.href='#'+n.id;next.textContent=n.title+' →'}
    }
    const observer=new IntersectionObserver(entries=>{entries.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top).forEach(e=>setCurrent(e.target.id))},{rootMargin:'-80px 0px -72% 0px'});
    links.forEach(link=>{const el=document.getElementById(link.dataset.target);if(el)observer.observe(el)});
    function onScroll(){const max=document.documentElement.scrollHeight-innerHeight;progress.style.width=(max>0?scrollY/max*100:0)+'%';backTop.classList.toggle('show',scrollY>600);setCurrent(currentId)}
    addEventListener('scroll',onScroll,{passive:true});onScroll();
    backTop.addEventListener('click',()=>scrollTo({top:0,behavior:'smooth'}));
    document.getElementById('printButton').addEventListener('click',()=>print());
    document.getElementById('copyButton').addEventListener('click',async()=>{const url=location.href.split('#')[0]+'#'+currentId;await navigator.clipboard.writeText(url);crumb.textContent='已复制当前章节链接';setTimeout(()=>setCurrent(currentId),1200)});
    const input=document.getElementById('searchInput'),status=document.getElementById('searchStatus'),article=document.getElementById('article');
    let marks=[];
    function clearMarks(){marks.forEach(mark=>mark.replaceWith(document.createTextNode(mark.textContent)));marks=[];article.normalize()}
    function search(){clearMarks();const q=input.value.trim();if(!q){status.textContent='';return}const walker=document.createTreeWalker(article,NodeFilter.SHOW_TEXT,{acceptNode:n=>n.parentElement.closest('script,style,code,pre,mark')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT});const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);const lower=q.toLocaleLowerCase('zh-CN');nodes.forEach(node=>{const text=node.nodeValue;const idx=text.toLocaleLowerCase('zh-CN').indexOf(lower);if(idx<0)return;const mark=document.createElement('mark');const after=node.splitText(idx);after.splitText(q.length);mark.textContent=after.nodeValue;after.replaceWith(mark);marks.push(mark)});status.textContent=marks.length?'找到 '+marks.length+' 处；已定位第一处':'未找到匹配内容';marks[0]?.scrollIntoView({behavior:'smooth',block:'center'})}
    document.getElementById('searchButton').addEventListener('click',search);input.addEventListener('keydown',e=>{if(e.key==='Enter')search()});
    document.querySelectorAll('.heading-link').forEach(link=>link.addEventListener('click',async e=>{e.preventDefault();history.replaceState(null,'',link.getAttribute('href'));await navigator.clipboard.writeText(location.href);link.textContent='✓';setTimeout(()=>link.textContent='#',900)}));
  })();
  </script>
</body>
</html>`;

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, html);
console.log(JSON.stringify({ sourcePath, outputPath, headings: headings.length, chapters: topChapters.length, mermaidCount, bytes: Buffer.byteLength(html) }, null, 2));
