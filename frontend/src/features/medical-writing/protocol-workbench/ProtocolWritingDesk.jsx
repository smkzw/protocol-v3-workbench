import { ResearchInformationCard } from './ResearchInformationCard';
import { RegimenDesignWorkspace } from './RegimenDesignWorkspace';
import { DesignElementsCards } from './DesignElementsCards';
import { ManuscriptWorkspace } from './ManuscriptWorkspace';

// Keep the same study components mounted while the document stays in view.
export function ProtocolWritingDesk(props) {
  return <div className="pvi-writing-desk">
    <aside className="pvi-design-pane" aria-label="研究设计与建议">
      <h2>研究设计与建议</h2>
      <details open><summary>研究信息</summary><ResearchInformationCard {...props} compact/></details>
      <details><summary>治疗方案建议</summary><RegimenDesignWorkspace {...props}/></details>
      <details open><summary>关键设计确认</summary><DesignElementsCards {...props}/></details>
    </aside>
    <section className="pvi-document-pane" aria-label="研究方案文档"><ManuscriptWorkspace {...props}/></section>
  </div>;
}
