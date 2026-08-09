import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  CheckCircle2,
  CheckCheck,
  GitCompare,
  Maximize2,
  Minimize2,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  SendToBack,
  Trash2,
  Undo2,
  Redo2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";

const NODE_KINDS = [
  ["entry", "起点"],
  ["screening", "筛选"],
  ["run_in", "导入期"],
  ["randomization", "随机"],
  ["allocation", "分配"],
  ["arm", "研究臂"],
  ["dose_cohort", "剂量队列"],
  ["treatment", "治疗/给药"],
  ["treatment_switch", "治疗转组"],
  ["extension_period", "开放标签延展期"],
  ["decision_gate", "决策门"],
  ["follow_up", "随访"],
  ["end", "结束"],
  ["other", "其他"],
];

const EDGE_KINDS = [
  ["participant_flow", "受试者流转"],
  ["activation_dependency", "队列启用条件"],
  ["randomization", "随机分配"],
  ["conditional", "条件分支"],
  ["treatment_switch", "转为其他治疗"],
  ["treatment_continuation", "继续原治疗"],
  ["discontinuation", "中止/退出"],
  ["follow_up", "进入随访"],
];

function apiErrorText(error) {
  if (typeof error?.detail === "string") return error.detail;
  if (Array.isArray(error?.detail)) return error.detail.map((item) => item.msg).join("；");
  return error?.message || "请求失败";
}

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw payload;
  return payload;
}

function svgDataUrl(svg) {
  return svg ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}` : "";
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

export function StudySchemaEditor({ projectId, sectionId, readOnly = false }) {
  const [snapshot, setSnapshot] = useState(null);
  const [workingCopy, setWorkingCopy] = useState(null);
  const [draft, setDraft] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [activePanel, setActivePanel] = useState("nodes");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [selectedEdgeId, setSelectedEdgeId] = useState("");
  const [changeReason, setChangeReason] = useState("");
  const [fullscreen, setFullscreen] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [historyState, setHistoryState] = useState({ undo: 0, redo: 0 });
  const undoStack = useRef([]);
  const redoStack = useRef([]);
  const previewRequestSequence = useRef(0);

  const base = `/api/projects/${projectId}/medical-writing/authoring-journey/study-schema`;
  const currentSvg = preview?.svg || snapshot?.svg || "";
  const svgPresentation = useMemo(() => {
    const width = Number(currentSvg.match(/<svg\b[^>]*\bwidth="([0-9.]+)"/)?.[1] || 0);
    const height = Number(currentSvg.match(/<svg\b[^>]*\bheight="([0-9.]+)"/)?.[1] || 0);
    const nodeCount = (currentSvg.match(/data-node-id="/g) || []).length;
    return {
      width,
      height,
      nodeCount,
      wordOrientation: width >= 1600 || nodeCount >= 12 ? "横向A4" : "纵向A4",
    };
  }, [currentSvg]);
  const issues = preview?.issues || snapshot?.issues || [];
  const blockers = issues.filter((item) => item.severity === "blocker");
  const selectedNode = draft?.nodes?.find((item) => item.node_id === selectedNodeId) || null;
  const selectedEdge = draft?.edges?.find((item) => item.edge_id === selectedEdgeId) || null;
  const committed = Boolean(snapshot?.study_schema);
  const draftMatchesCommitted = draft?.state_sha256 === snapshot?.study_schema?.state_sha256;
  const committedSchemaStale = snapshot?.study_schema?.status === "stale";
  const projectedFigure = workingCopy?.content_blocks?.find((block) => block.figure_kind === "study_schema") || null;
  const figureCurrent = Boolean(
    projectedFigure
    && projectedFigure.schema_state_sha256 === snapshot?.study_schema?.state_sha256
    && projectedFigure.layout_revision === snapshot?.presentation?.layout_revision
  );

  const load = () => {
    setBusy("load");
    setMessage("");
    Promise.all([
      fetch(base).then(readJson),
      sectionId
        ? fetch(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`).then(readJson)
        : Promise.resolve(null),
    ])
      .then(([payload, currentWorkingCopy]) => {
        setSnapshot(payload);
        setWorkingCopy(currentWorkingCopy);
        setDraft(payload.study_schema || null);
        setPreview(null);
        setSelectedNodeId(payload.study_schema?.nodes?.[0]?.node_id || "");
        setSelectedEdgeId(payload.study_schema?.edges?.[0]?.edge_id || "");
        undoStack.current = [];
        redoStack.current = [];
        setHistoryState({ undo: 0, redo: 0 });
      })
      .catch((error) => setMessage(`研究流程图读取失败：${apiErrorText(error)}`))
      .finally(() => setBusy(""));
  };

  useEffect(() => {
    load();
  }, [projectId, sectionId]);

  const invalidatePreview = () => {
    previewRequestSequence.current += 1;
    setPreview(null);
  };
  const syncHistoryState = () => setHistoryState({
    undo: undoStack.current.length,
    redo: redoStack.current.length,
  });
  const updateDraft = (updater) => {
    if (!draft) return;
    undoStack.current = [...undoStack.current.slice(-29), draft];
    redoStack.current = [];
    setDraft(updater(draft));
    syncHistoryState();
    invalidatePreview();
    setMessage("");
  };

  const undo = () => {
    if (!undoStack.current.length || !draft) return;
    const previous = undoStack.current[undoStack.current.length - 1];
    undoStack.current = undoStack.current.slice(0, -1);
    redoStack.current = [...redoStack.current.slice(-29), draft];
    setDraft(previous);
    setPreview(null);
    setMessage("已撤销上一步编辑。");
    syncHistoryState();
  };

  const redo = () => {
    if (!redoStack.current.length || !draft) return;
    const next = redoStack.current[redoStack.current.length - 1];
    redoStack.current = redoStack.current.slice(0, -1);
    undoStack.current = [...undoStack.current.slice(-29), draft];
    setDraft(next);
    setPreview(null);
    setMessage("已重做上一步编辑。");
    syncHistoryState();
  };

  const createProposal = () => {
    setBusy("proposal");
    setMessage("");
    fetch(`${base}/proposal`)
      .then(readJson)
      .then((payload) => {
        setDraft(payload);
        setPreview(null);
        setSelectedNodeId(payload.nodes?.[0]?.node_id || "");
        setActivePanel("nodes");
        undoStack.current = [];
        redoStack.current = [];
        setHistoryState({ undo: 0, redo: 0 });
        setMessage("已根据当前研究框架与PICOS生成候选图；可先整体核对，再一键确认全部候选。");
      })
      .catch((error) => setMessage(`候选图生成失败：${apiErrorText(error)}`))
      .finally(() => setBusy(""));
  };

  const updatePart = (partId, patch) => updateDraft((current) => ({
    ...current,
    parts: current.parts.map((part) => part.part_id === partId ? { ...part, ...patch } : part),
  }));

  const updateNode = (nodeId, patch, invalidateFact = true) => updateDraft((current) => ({
    ...current,
    nodes: current.nodes.map((node) => node.node_id === nodeId
      ? {
        ...node,
        ...patch,
        ...(invalidateFact && node.fact_status === "confirmed" ? { fact_status: "manual_candidate" } : {}),
      }
      : node),
  }));

  const updateEdge = (edgeId, patch, invalidateFact = true) => updateDraft((current) => ({
    ...current,
    edges: current.edges.map((edge) => edge.edge_id === edgeId
      ? {
        ...edge,
        ...patch,
        ...(invalidateFact && edge.fact_status === "confirmed" ? { fact_status: "manual_candidate" } : {}),
      }
      : edge),
  }));

  const addPart = () => updateDraft((current) => {
    const index = current.parts.length + 1;
    return {
      ...current,
      parts: [...current.parts, {
        part_id: `part_${Date.now()}`,
        order: current.parts.length,
        label: `研究部分 ${index}`,
        flow_direction: "left_to_right",
        source_bindings: [],
      }],
    };
  });

  const addNode = () => updateDraft((current) => {
    const nodeId = `node_${Date.now()}`;
    const partId = current.parts[0]?.part_id;
    const maxOrder = Math.max(-1, ...current.nodes.filter((node) => node.part_id === partId).map((node) => node.order));
    setSelectedNodeId(nodeId);
    setActivePanel("nodes");
    return {
      ...current,
      nodes: [...current.nodes, {
        node_id: nodeId,
        part_id: partId,
        order: maxOrder + 1,
        lane_order: 0,
        node_kind: "other",
        label: "新节点",
        detail_lines: [],
        fact_status: "manual_candidate",
        source_bindings: [],
      }],
    };
  });

  const deleteNode = (nodeId) => updateDraft((current) => {
    const nodes = current.nodes.filter((node) => node.node_id !== nodeId);
    setSelectedNodeId(nodes[0]?.node_id || "");
    return {
      ...current,
      nodes,
      edges: current.edges.filter((edge) => edge.from_node_id !== nodeId && edge.to_node_id !== nodeId),
    };
  });

  const addEdge = () => updateDraft((current) => {
    if (current.nodes.length < 2) return current;
    const edgeId = `edge_${Date.now()}`;
    setSelectedEdgeId(edgeId);
    setActivePanel("edges");
    return {
      ...current,
      edges: [...current.edges, {
        edge_id: edgeId,
        from_node_id: current.nodes[0].node_id,
        to_node_id: current.nodes[1].node_id,
        edge_kind: "participant_flow",
        label: "",
        fact_status: "manual_candidate",
        source_bindings: [],
      }],
    };
  });

  const deleteEdge = (edgeId) => updateDraft((current) => {
    const edges = current.edges.filter((edge) => edge.edge_id !== edgeId);
    setSelectedEdgeId(edges[0]?.edge_id || "");
    return { ...current, edges };
  });

  const confirmAllCandidates = () => updateDraft((current) => ({
    ...current,
    nodes: current.nodes.map((node) => (
      ["manual_candidate", "extracted_candidate"].includes(node.fact_status)
        ? { ...node, fact_status: "confirmed" }
        : node
    )),
    edges: current.edges.map((edge) => (
      ["manual_candidate", "extracted_candidate"].includes(edge.fact_status)
        ? { ...edge, fact_status: "confirmed" }
        : edge
    )),
  }));

  const requestPreview = ({ silent = false } = {}) => {
    if (!draft || !snapshot) return;
    const requestSequence = previewRequestSequence.current + 1;
    previewRequestSequence.current = requestSequence;
    if (!silent) {
      setBusy("preview");
      setMessage("");
    }
    fetch(`${base}/impact-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_journey_revision: snapshot.journey_revision,
        study_schema: draft,
      }),
    })
      .then(readJson)
      .then((payload) => {
        if (requestSequence !== previewRequestSequence.current) return;
        setPreview(payload);
        if (!silent) {
          setMessage(payload.issues?.length
            ? `预览完成：${payload.issues.filter((item) => item.severity === "blocker").length} 项阻断、${payload.issues.filter((item) => item.severity === "warning").length} 项提示。`
            : "预览完成，当前图无结构性问题。 ");
        }
      })
      .catch((error) => {
        if (requestSequence === previewRequestSequence.current) {
          setMessage(`影响预览失败：${apiErrorText(error)}`);
        }
      })
      .finally(() => {
        if (!silent && requestSequence === previewRequestSequence.current) {
          setBusy("");
        }
      });
  };

  useEffect(() => {
    if (!draft || !snapshot || readOnly) return undefined;
    if (committedSchemaStale && draftMatchesCommitted) return undefined;
    const timer = window.setTimeout(() => requestPreview({ silent: true }), 450);
    return () => window.clearTimeout(timer);
  }, [
    draft,
    snapshot?.journey_revision,
    readOnly,
    committedSchemaStale,
    draftMatchesCommitted,
  ]);

  const commit = () => {
    if (!draft || !snapshot || !preview || changeReason.trim().length < 10) return;
    setBusy("commit");
    setMessage("");
    fetch(`${base}/commit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_journey_revision: snapshot.journey_revision,
        study_schema: draft,
        impact_preview_id: preview.preview_id,
        reason: changeReason.trim(),
        actor: "medical_manager",
        idempotency_key: `study-schema-${projectId}-${Date.now()}`,
      }),
    })
      .then(readJson)
      .then((payload) => {
        setSnapshot(payload);
        setDraft(payload.study_schema);
        setPreview(null);
        setChangeReason("");
        setMessage(payload.formal_render_allowed
          ? "研究流程图已提交并形成可插入方案的正式矢量版本。"
          : "研究流程图已保存为草稿；仍有事实阻断项，暂不能插入正式方案。 ");
      })
      .catch((error) => setMessage(`研究流程图提交失败：${apiErrorText(error)}`))
      .finally(() => setBusy(""));
  };

  const saveLayout = (nextOverrides) => {
    if (!snapshot?.study_schema || !snapshot?.presentation) return;
    setBusy("layout");
    fetch(`${base}/layout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_journey_revision: snapshot.journey_revision,
        expected_schema_revision: snapshot.study_schema.revision,
        expected_layout_revision: snapshot.presentation.layout_revision,
        node_overrides: nextOverrides,
        actor: "medical_manager",
        idempotency_key: `study-schema-layout-${projectId}-${Date.now()}`,
      }),
    })
      .then(readJson)
      .then((payload) => {
        setSnapshot(payload);
        setMessage("位置微调已写入独立布局版本，未改变研究事实。 ");
      })
      .catch((error) => setMessage(`布局保存失败：${apiErrorText(error)}`))
      .finally(() => setBusy(""));
  };

  const nudgeSelectedNode = (dx, dy) => {
    if (!selectedNode || !draftMatchesCommitted) return;
    const current = snapshot.presentation?.node_overrides?.find((item) => item.node_id === selectedNode.node_id) || { node_id: selectedNode.node_id, dx: 0, dy: 0 };
    const next = {
      ...current,
      dx: clamp(current.dx + dx, -48, 48),
      dy: clamp(current.dy + dy, -32, 32),
    };
    const overrides = [
      ...(snapshot.presentation?.node_overrides || []).filter((item) => item.node_id !== selectedNode.node_id),
      next,
    ];
    saveLayout(overrides);
  };

  const projectFigure = () => {
    if (!sectionId || !snapshot?.study_schema || !snapshot?.presentation || !workingCopy) return;
    setBusy("project");
    setMessage("");
    fetch(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}/study-schema-figure`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_journey_revision: snapshot.journey_revision,
        expected_schema_revision: snapshot.study_schema.revision,
        expected_layout_revision: snapshot.presentation.layout_revision,
        expected_working_copy_revision: workingCopy.revision,
        actor: "medical_manager",
        reason: projectedFigure
          ? "医学经理确认以当前研究事实和布局更新方案研究流程图。"
          : "医学经理确认将当前研究流程图插入方案第1.2节。",
        idempotency_key: `study-schema-figure-${projectId}-${Date.now()}`,
      }),
    })
      .then(readJson)
      .then((payload) => {
        setWorkingCopy(payload.working_copy);
        setMessage(payload.projection_action === "inserted"
          ? "研究流程图已插入方案第1.2节，并进入工作副本版本。"
          : "方案中的研究流程图已更新为当前事实和布局版本。 ");
      })
      .catch((error) => setMessage(`插入方案失败：${apiErrorText(error)}`))
      .finally(() => setBusy(""));
  };

  const issueTargets = useMemo(() => new Map(issues.map((item) => [item.target_id, item])), [issues]);

  return (
    <section className={`study-schema-editor ${fullscreen ? "is-fullscreen" : ""}`} data-testid="study-schema-editor">
      <header className="study-schema-toolbar">
        <div>
          <span>研究流程图</span>
          <strong>{draft?.title || "研究设计概况"}</strong>
          {snapshot?.study_schema && <small>图版本 {snapshot.study_schema.revision} · 布局版本 {snapshot.presentation?.layout_revision || 0}</small>}
          {currentSvg && <small className="study-schema-output-hint">Word：{svgPresentation.wordOrientation}</small>}
        </div>
        <div className="study-schema-toolbar-actions">
          <button type="button" onClick={load} disabled={Boolean(busy)} title="重新读取服务器版本"><RefreshCw size={15} />刷新</button>
          <button type="button" onClick={undo} disabled={Boolean(busy) || readOnly || !historyState.undo} title="撤销上一步编辑"><Undo2 size={15} />撤销</button>
          <button type="button" onClick={redo} disabled={Boolean(busy) || readOnly || !historyState.redo} title="重做上一步编辑"><Redo2 size={15} />重做</button>
          {committedSchemaStale && <button type="button" className="primary-button" onClick={createProposal} disabled={Boolean(busy) || readOnly} title="研究事实已变化；按当前已确认研究框架和PICOS重新生成候选图"><RefreshCw size={15} />按当前设计重新生成</button>}
          <button
            type="button"
            onClick={confirmAllCandidates}
            disabled={Boolean(busy) || readOnly || !draft || !draft.nodes.some((node) => ["manual_candidate", "extracted_candidate"].includes(node.fact_status)) && !draft.edges.some((edge) => ["manual_candidate", "extracted_candidate"].includes(edge.fact_status))}
            title="医学经理整体核对当前候选后，一次确认全部节点和关系"
          ><CheckCheck size={15} />确认全部候选</button>
          {committed && <button type="button" onClick={() => saveLayout([])} disabled={Boolean(busy) || !draftMatchesCommitted} title="清除位置微调并恢复确定性自动布局"><RotateCcw size={15} />自动排布</button>}
          <div className="study-schema-zoom" aria-label="流程图缩放">
            <button type="button" onClick={() => setZoom((value) => clamp(value - 0.15, 0.55, 1.6))} disabled={zoom <= 0.55} title="缩小流程图"><ZoomOut size={15} /></button>
            <span>{Math.round(zoom * 100)}%</span>
            <button type="button" onClick={() => setZoom((value) => clamp(value + 0.15, 0.55, 1.6))} disabled={zoom >= 1.6} title="放大流程图"><ZoomIn size={15} /></button>
          </div>
          <button type="button" onClick={() => requestPreview()} disabled={Boolean(busy) || !draft || readOnly || committedSchemaStale && draftMatchesCommitted} title={committedSchemaStale && draftMatchesCommitted ? "研究事实已变化，请先按当前设计重新生成候选图" : "立即校验事实状态并刷新当前预览"}><GitCompare size={15} />立即预览</button>
          {committed && <button
            type="button"
            className={figureCurrent ? "" : "primary-button"}
            onClick={projectFigure}
            disabled={Boolean(busy) || readOnly || !sectionId || !workingCopy || !snapshot?.formal_render_allowed || !draftMatchesCommitted || figureCurrent}
            title={figureCurrent ? "方案中的流程图已是当前版本" : "把当前已确认流程图插入或更新到方案第1.2节"}
          ><SendToBack size={15} />{busy === "project" ? "写入中" : projectedFigure ? figureCurrent ? "已同步方案" : "更新方案" : "插入方案"}</button>}
          <button type="button" className="icon-button" onClick={() => setFullscreen((value) => !value)} title={fullscreen ? "退出最大化" : "最大化流程图编辑器"}>{fullscreen ? <Minimize2 size={17} /> : <Maximize2 size={17} />}</button>
        </div>
      </header>

      {!draft ? (
        <div className="study-schema-empty">
          <strong>尚未建立研究流程图</strong>
          <p>系统将从已确认研究框架和PICOS生成候选节点；所有节点与关系均需医学确认。</p>
          <button type="button" className="primary-button" onClick={createProposal} disabled={Boolean(busy) || readOnly}><Plus size={16} />生成候选图</button>
        </div>
      ) : (
        <div className="study-schema-workspace">
          <aside className="study-schema-structure">
            <div className="study-schema-tabs" role="tablist">
              {[["parts", "研究部分"], ["nodes", "节点"], ["edges", "关系"]].map(([id, label]) => (
                <button key={id} type="button" className={activePanel === id ? "active" : ""} onClick={() => setActivePanel(id)}>{label}</button>
              ))}
            </div>

            {activePanel === "parts" && <div className="study-schema-list">
              {draft.parts.map((part) => <article key={part.part_id} className="study-schema-form-row">
                <label><span>标题</span><input value={part.label} disabled={readOnly} onChange={(event) => updatePart(part.part_id, { label: event.target.value })} /></label>
                <div className="study-schema-inline-fields">
                  <label><span>顺序</span><input type="number" min="0" value={part.order} disabled={readOnly} onChange={(event) => updatePart(part.part_id, { order: Number(event.target.value) })} /></label>
                  <label><span>方向</span><select value={part.flow_direction} disabled={readOnly} onChange={(event) => updatePart(part.part_id, { flow_direction: event.target.value })}><option value="left_to_right">从左到右</option><option value="top_to_bottom">从上到下</option><option value="bottom_to_top">从下到上</option></select></label>
                </div>
              </article>)}
              {!readOnly && <button type="button" className="study-schema-add" onClick={addPart}><Plus size={14} />新增研究部分</button>}
            </div>}

            {activePanel === "nodes" && <div className="study-schema-list">
              {draft.nodes.map((node) => <button type="button" key={node.node_id} className={`study-schema-list-item ${selectedNodeId === node.node_id ? "active" : ""}`} onClick={() => setSelectedNodeId(node.node_id)}>
                <span>{NODE_KINDS.find(([id]) => id === node.node_kind)?.[1] || node.node_kind}</span>
                <strong>{node.label}</strong>
                {node.fact_status === "confirmed" ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
              </button>)}
              {!readOnly && <button type="button" className="study-schema-add" onClick={addNode}><Plus size={14} />新增节点</button>}
            </div>}

            {activePanel === "edges" && <div className="study-schema-list">
              {draft.edges.map((edge) => <button type="button" key={edge.edge_id} className={`study-schema-list-item ${selectedEdgeId === edge.edge_id ? "active" : ""}`} onClick={() => setSelectedEdgeId(edge.edge_id)}>
                <span>{EDGE_KINDS.find(([id]) => id === edge.edge_kind)?.[1] || edge.edge_kind}</span>
                <strong>{draft.nodes.find((node) => node.node_id === edge.from_node_id)?.label} → {draft.nodes.find((node) => node.node_id === edge.to_node_id)?.label}</strong>
                {edge.fact_status === "confirmed" ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
              </button>)}
              {!readOnly && <button type="button" className="study-schema-add" onClick={addEdge} disabled={draft.nodes.length < 2}><Plus size={14} />新增关系</button>}
            </div>}
          </aside>

          <main className="study-schema-canvas-column">
            <div className="study-schema-canvas">
              {currentSvg ? <img src={svgDataUrl(currentSvg)} alt="研究流程图预览" style={{ width: `${zoom * 100}%` }} /> : <div className="study-schema-canvas-placeholder">候选图将在编辑停顿后自动生成。</div>}
            </div>
            <div className="study-schema-legend"><span><i className="candidate" />候选事实</span><span><i className="confirmed" />已确认事实</span><span>虚线关系：队列启用条件/条件分支</span></div>
          </main>

          <aside className="study-schema-inspector">
            {activePanel === "nodes" && selectedNode ? <>
              <header><span>节点属性</span><strong>{selectedNode.label}</strong></header>
              <label><span>节点名称</span><input value={selectedNode.label} disabled={readOnly} onChange={(event) => updateNode(selectedNode.node_id, { label: event.target.value })} /></label>
              <label><span>节点类型</span><select value={selectedNode.node_kind} disabled={readOnly} onChange={(event) => updateNode(selectedNode.node_id, { node_kind: event.target.value })}>{NODE_KINDS.map(([id, label]) => <option value={id} key={id}>{label}</option>)}</select></label>
              <label><span>所属部分</span><select value={selectedNode.part_id} disabled={readOnly} onChange={(event) => updateNode(selectedNode.node_id, { part_id: event.target.value })}>{draft.parts.map((part) => <option value={part.part_id} key={part.part_id}>{part.label}</option>)}</select></label>
              <div className="study-schema-inline-fields"><label><span>流程层级</span><input type="number" min="0" value={selectedNode.order} disabled={readOnly} onChange={(event) => updateNode(selectedNode.node_id, { order: Number(event.target.value) })} /></label><label><span>同层分支</span><input type="number" min="0" max="20" value={selectedNode.lane_order || 0} disabled={readOnly} onChange={(event) => updateNode(selectedNode.node_id, { lane_order: Number(event.target.value) })} /></label></div>
              <label><span>补充说明（每行一条）</span><textarea rows="4" value={(selectedNode.detail_lines || []).join("\n")} disabled={readOnly} onChange={(event) => updateNode(selectedNode.node_id, { detail_lines: event.target.value.split("\n").map((line) => line.trim()).filter(Boolean) })} /></label>
              <div className="study-schema-fact-state"><span>事实状态</span><strong>{selectedNode.fact_status === "confirmed" ? "医学已确认" : "待医学确认"}</strong>{!readOnly && <button type="button" onClick={() => updateNode(selectedNode.node_id, { fact_status: selectedNode.fact_status === "confirmed" ? "manual_candidate" : "confirmed" }, false)}>{selectedNode.fact_status === "confirmed" ? "撤回确认" : "确认该节点"}</button>}</div>
              <div className="study-schema-nudge"><span>位置微调</span><div><button type="button" title="向上微调" disabled={!draftMatchesCommitted || Boolean(busy)} onClick={() => nudgeSelectedNode(0, -8)}><ArrowUp size={15} /></button><button type="button" title="向左微调" disabled={!draftMatchesCommitted || Boolean(busy)} onClick={() => nudgeSelectedNode(-8, 0)}><ArrowLeft size={15} /></button><button type="button" title="向右微调" disabled={!draftMatchesCommitted || Boolean(busy)} onClick={() => nudgeSelectedNode(8, 0)}><ArrowRight size={15} /></button><button type="button" title="向下微调" disabled={!draftMatchesCommitted || Boolean(busy)} onClick={() => nudgeSelectedNode(0, 8)}><ArrowDown size={15} /></button></div><small>单次 8 px，横向最多 ±48 px，纵向最多 ±32 px；不改变研究事实。</small></div>
              {!readOnly && <button type="button" className="danger-button" onClick={() => deleteNode(selectedNode.node_id)} disabled={draft.nodes.length <= 1}><Trash2 size={14} />删除节点</button>}
            </> : activePanel === "edges" && selectedEdge ? <>
              <header><span>关系属性</span><strong>{EDGE_KINDS.find(([id]) => id === selectedEdge.edge_kind)?.[1]}</strong></header>
              <label><span>起点</span><select value={selectedEdge.from_node_id} disabled={readOnly} onChange={(event) => updateEdge(selectedEdge.edge_id, { from_node_id: event.target.value })}>{draft.nodes.map((node) => <option value={node.node_id} key={node.node_id}>{node.label}</option>)}</select></label>
              <label><span>终点</span><select value={selectedEdge.to_node_id} disabled={readOnly} onChange={(event) => updateEdge(selectedEdge.edge_id, { to_node_id: event.target.value })}>{draft.nodes.map((node) => <option value={node.node_id} key={node.node_id}>{node.label}</option>)}</select></label>
              <label><span>关系类型</span><select value={selectedEdge.edge_kind} disabled={readOnly} onChange={(event) => updateEdge(selectedEdge.edge_id, { edge_kind: event.target.value })}>{EDGE_KINDS.map(([id, label]) => <option value={id} key={id}>{label}</option>)}</select></label>
              <label><span>关系标签</span><input value={selectedEdge.label || ""} disabled={readOnly} onChange={(event) => updateEdge(selectedEdge.edge_id, { label: event.target.value })} placeholder={selectedEdge.edge_kind === "conditional" ? "条件分支必须填写" : "可选"} /></label>
              <div className="study-schema-fact-state"><span>事实状态</span><strong>{selectedEdge.fact_status === "confirmed" ? "医学已确认" : "待医学确认"}</strong>{!readOnly && <button type="button" onClick={() => updateEdge(selectedEdge.edge_id, { fact_status: selectedEdge.fact_status === "confirmed" ? "manual_candidate" : "confirmed" }, false)}>{selectedEdge.fact_status === "confirmed" ? "撤回确认" : "确认该关系"}</button>}</div>
              {!readOnly && <button type="button" className="danger-button" onClick={() => deleteEdge(selectedEdge.edge_id)}><Trash2 size={14} />删除关系</button>}
            </> : <div className="study-schema-inspector-empty">选择一个节点或关系进行编辑。</div>}
          </aside>
        </div>
      )}

      {draft && <footer className="study-schema-footer">
        <div className="study-schema-issues">
          <strong>{blockers.length ? `${blockers.length} 项阻断正式插入` : preview ? "当前无阻断项" : "请先执行影响预览"}</strong>
          {issues.slice(0, 3).map((issue) => <span key={issue.issue_id} className={issue.severity}>{issue.message}</span>)}
          {issues.length > 3 && <small>另有 {issues.length - 3} 项，请在对应节点或关系中核对。</small>}
        </div>
        {!readOnly && <div className="study-schema-commit">
          <label><span>变更理由</span><input value={changeReason} onChange={(event) => setChangeReason(event.target.value)} placeholder="至少10个字，说明本次医学确认或调整依据" /></label>
          <button type="button" className="primary-button" onClick={commit} disabled={Boolean(busy) || !preview || changeReason.trim().length < 10}><Save size={15} />{busy === "commit" ? "提交中" : "提交当前版本"}</button>
        </div>}
      </footer>}
      {message && <p className={`study-schema-message ${/失败|冲突|错误/.test(message) ? "danger" : ""}`}>{message}</p>}
    </section>
  );
}
