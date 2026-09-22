import { ResearchInformationCard } from './ResearchInformationCard';
import { RegimenDesignWorkspace } from './RegimenDesignWorkspace';
import { DesignElementsCards } from './DesignElementsCards';
import { ManuscriptWorkspace } from './ManuscriptWorkspace';

// Keep the same study components mounted while the document stays in view.
export function ProtocolWritingDesk(props) {
  return <div className={`pvi-writing-desk${props.bridgeMode ? ' pvi-writing-desk--bridge' : ''}`}>
    <aside className="pvi-design-pane" aria-label="研究设计与建议">
      <h2>研究设计与建议</h2>
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
    <section className="pvi-document-pane" aria-label="研究方案文档"><ManuscriptWorkspace {...props}/></section>
  </div>;
}
