import React from 'react';
import { createRoot } from 'react-dom/client';
import { ChapterDraftPreview } from '../src/features/medical-writing/protocol-workbench/ChapterDraftPreview.jsx';
import { chapterFixture } from './fixtures/chapter-preview-fixture.mjs';
import '../src/styles.css';
createRoot(document.getElementById('root')).render(<>
  <aside style={{padding:'10px 24px',background:'#fff3d6',fontSize:14}}>章节阅读显示验证 · 全部内容为合成资料 · 未调用模型或保存研究</aside>
  <main style={{padding:'12px'}}><ChapterDraftPreview title="研究程序" candidate={chapterFixture()}/></main>
</>);
