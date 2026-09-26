import { useEffect, useState } from 'react';
import { ResearchInformationCard } from './ResearchInformationCard';
import { RegimenDesignWorkspace } from './RegimenDesignWorkspace';
import { DesignElementsCards } from './DesignElementsCards';
import { ManuscriptWorkspace } from './ManuscriptWorkspace';

// 0926V1 G7 (A703/A704): the document canvas is the main area and stays first;
// the right rail carries tasks/summary only. 完整候选已在宽文档区呈现，研究
// 比较/设计确认通过「宽审阅」进入宽审阅面——纯 CSS 类切换（面板保持挂载，
// Escape 可退出），因此调宽/开关宽审阅/切右栏分组都不会重建 Office iframe，
// 也不影响 dirty/选区/IME/撤销状态。
export function ProtocolWritingDesk(props) {
  const [wideReview, setWideReview] = useState(false);

  useEffect(() => {
    if (!wideReview) return undefined;
    const escape = (event) => { if (event.key === 'Escape') setWideReview(false); };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  }, [wideReview]);

  return <div className={`pvi-writing-desk${props.bridgeMode ? ' pvi-writing-desk--bridge' : ''}${wideReview ? ' pvi-wide-review' : ''}`}>
    <section className="pvi-document-pane" aria-label="研究方案文档"><ManuscriptWorkspace {...props}/></section>
    <aside className="pvi-design-pane" aria-label="任务与摘要">
      <div className="pvi-design-pane-head">
        <h2>任务与摘要</h2>
        <button type="button" aria-pressed={wideReview}
          onClick={() => setWideReview(value => !value)}>
          {wideReview ? '退出宽审阅' : '宽审阅：研究比较'}
        </button>
      </div>
      {props.bridgeMode ? <ul className="pvi-handoff-summary">
        <li><strong>已沿用：</strong>项目设计与来源。</li>
        <li><strong>需确认：</strong>关键剂量、安全和统计决定。</li>
        <li><strong>写入规则：</strong>候选经采用后进入当前稿。</li>
      </ul> : <>
        <details open><summary>研究信息</summary><ResearchInformationCard {...props} compact/></details>
        <details><summary>治疗方案建议</summary><RegimenDesignWorkspace {...props}/></details>
        <details open><summary>关键设计确认</summary><DesignElementsCards {...props}/></details>
      </>}
    </aside>
  </div>;
}
