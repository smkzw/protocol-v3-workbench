import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { WritingReferencePanel } from "../writing-reference/WritingReferencePanel";

/**
 * Early authoring competitor-processing drawer.
 * Reuses WritingReferencePanel state machine; keeps the panel mounted when closed
 * so triage selection, scroll position, and in-flight jobs survive hide/show.
 */
export function AuthoringCompetitorDrawer({
  open = false,
  onClose = () => {},
  projectId,
  snapshotId = "",
  lockedIndication = "",
  lockedPhase = "",
  journey = null,
  onJourneyChange = () => {},
  onTriagePipelineChange = () => {},
  selectedBriefIds = [],
  onSelectedBriefIdsChange = () => {},
  requestedView = "",
  requestedArtifactId = "",
  focusRequestKey = "",
  keepPanelMounted = true,
  onExecuteSearch = null,
  searchBusy = false,
}) {
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    globalThis.addEventListener?.("keydown", onKeyDown);
    return () => globalThis.removeEventListener?.("keydown", onKeyDown);
  }, [open, onClose]);

  const prevOpenRef = useRef(open);
  const [refreshSignal, setRefreshSignal] = useState(0);
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      setRefreshSignal((signal) => signal + 1);
    }
    prevOpenRef.current = open;
  }, [open]);

  const shouldRenderPanel = Boolean(projectId && (keepPanelMounted || open) && snapshotId);

  return (
    <div
      className={`authoring-competitor-drawer-host ${open ? "is-open" : "is-closed"}`}
      data-open={open ? "true" : "false"}
      aria-hidden={!open}
    >
      <button
        type="button"
        className="authoring-competitor-drawer-backdrop"
        tabIndex={open ? 0 : -1}
        aria-label="关闭竞品处理抽屉"
        onClick={onClose}
      />
      <aside
        className="authoring-competitor-drawer panel"
        role="dialog"
        aria-modal={open ? "true" : "false"}
        aria-label="竞品方案处理"
        data-testid="authoring-competitor-drawer"
      >
        <header className="authoring-competitor-drawer-header">
          <div>
            <span>建稿前语料处理</span>
            <strong>竞品方案处理</strong>
            <small>
              {snapshotId
                ? "分诊、原文、译文与医学审核可在此完成；关闭抽屉不会清空研究框架或PICOS草稿。"
                : "完成竞品检索后可在此处理候选研究；当前尚无已保存的公开检索快照。"}
            </small>
          </div>
          <button
            type="button"
            className="icon-button authoring-competitor-drawer-close"
            onClick={onClose}
            title="关闭竞品处理抽屉"
            aria-label="关闭竞品处理抽屉"
            data-action="close-competitor-drawer"
          >
            <X size={16} />
          </button>
        </header>
        <div className="authoring-competitor-drawer-body">
          {shouldRenderPanel ? (
            <WritingReferencePanel
              projectId={projectId}
              variant="authoring"
              embedded
              compact
              snapshotId={snapshotId}
              lockedIndication={lockedIndication}
              lockedPhase={lockedPhase}
              journey={journey}
              onJourneyChange={onJourneyChange}
              onTriagePipelineChange={onTriagePipelineChange}
              selectedBriefIds={selectedBriefIds}
              onSelectedBriefIdsChange={onSelectedBriefIdsChange}
              requestedView={requestedView}
              requestedArtifactId={requestedArtifactId}
              focusRequestKey={focusRequestKey}
              refreshSignal={refreshSignal}
            />
          ) : (
            <div className="authoring-competitor-drawer-empty" role="status">
              <strong>竞品处理尚未就绪</strong>
              <p>
                {snapshotId
                  ? "本次公开检索结果已关联，但面板暂不可用；请关闭后重开抽屉。"
                  : "尚无已保存的公开检索快照。请先在语料门执行一次 ClinicalTrials.gov 公开检索；检索完成后本抽屉会自动加载候选分诊与原文处理。"}
              </p>
              {!snapshotId && typeof onExecuteSearch === "function" && (
                <button
                  type="button"
                  className="primary-button"
                  data-action="execute-search-from-competitor-drawer"
                  onClick={onExecuteSearch}
                  disabled={Boolean(searchBusy)}
                  title={searchBusy ? "正在执行公开检索，请稍候" : "执行公开检索并保存本次检索快照（推荐默认动作）"}
                >
                  {searchBusy ? "检索中…" : "执行公开检索（推荐）"}
                </button>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

export default AuthoringCompetitorDrawer;
