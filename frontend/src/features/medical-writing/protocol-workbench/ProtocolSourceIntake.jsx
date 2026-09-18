import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Download, FilePlus2, PencilLine } from "lucide-react";
import "./ProtocolSourceIntake.css";

import { SOURCE_ROLE_OPTIONS, ROLE_LABELS } from "./sourceRoleLabels.mjs";

const UNMARKED_VERSION = "unidentified";
const UNSPECIFIED_JURISDICTION = "unspecified";
const FALLBACK_ERROR = "本次操作未能完成，请稍后重试。";
const INCOMPLETE_LIST_ERROR = "资料列表返回不完整。";

function isAbortError(error) {
  return error?.name === "AbortError";
}

function isChineseText(value) {
  return typeof value === "string" && /[\u3400-\u9fff]/u.test(value);
}

function errorMessageOf(error) {
  const message = error?.detail?.message ?? error?.message;
  return isChineseText(message) && message.trim() ? message : FALLBACK_ERROR;
}

function nextStepOf(error) {
  const nextStep = error?.detail?.next_step ?? error?.next_step;
  return isChineseText(nextStep) && nextStep.trim() ? nextStep : null;
}

function roleLabel(value) {
  return ROLE_LABELS[value] ?? "资料类别未注明";
}

function versionText(value) {
  return value && value !== UNMARKED_VERSION ? `版本：${value}` : "版本未注明";
}

function jurisdictionText(value) {
  return value && value !== UNSPECIFIED_JURISDICTION ? `地区：${value}` : "地区未注明";
}

function currentValue(value) {
  return value && value !== UNMARKED_VERSION && value !== UNSPECIFIED_JURISDICTION
    ? value
    : "未注明";
}

function isStoredSource(record) {
  const identity = record?.source;
  return Boolean(
    identity
      && identity.source_artifact_id
      && typeof identity.logical_source_key === "string"
      && identity.logical_source_key.trim(),
  );
}

function sourceListFrom(payload) {
  if (!Array.isArray(payload?.sources)) {
    const error = new Error(INCOMPLETE_LIST_ERROR);
    error.detail = { next_step: "请重试。" };
    throw error;
  }
  return payload.sources;
}

export function ProtocolSourceIntake({
  projectId,
  api,
  brief = "",
  onBriefChange,
  onPrepare,
  refreshKey = 0,
  initialExcludedKeys = [],
  onExcludedKeysChange,
}) {
  const instanceId = useId().replace(/:/gu, "");
  const apiRef = useRef(api);
  apiRef.current = api;

  const scopeRef = useRef({ projectId, generation: 0 });
  if (scopeRef.current.projectId !== projectId) {
    scopeRef.current = {
      projectId,
      generation: scopeRef.current.generation + 1,
    };
  }

  const mountedRef = useRef(true);
  const listControllerRef = useRef(null);
  const importControllerRef = useRef(null);
  const correctionControllerRef = useRef(null);
  const importBusyRef = useRef(false);
  const correctionBusyRef = useRef(false);

  const [sources, setSources] = useState(null);
  const [sourcesProjectId, setSourcesProjectId] = useState(null);
  const [viewProjectId, setViewProjectId] = useState(projectId);
  const [loadError, setLoadError] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [excludedKeys, setExcludedKeys] = useState(() => new Set(initialExcludedKeys));
  const [pendingFiles, setPendingFiles] = useState([]);
  const pendingFile = pendingFiles[0] ?? null;
  const [importRole, setImportRole] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [importStatus, setImportStatus] = useState(null);
  const [importError, setImportError] = useState(null);
  const [correction, setCorrection] = useState(null);
  const [correctionBusy, setCorrectionBusy] = useState(false);
  const [notice, setNotice] = useState(null);

  const ids = useMemo(
    () => ({
      title: `${instanceId}-title`,
      file: `${instanceId}-file`,
      brief: `${instanceId}-brief`,
      importRole: `${instanceId}-import-role`,
      importRoleHint: `${instanceId}-import-role-hint`,
      correctionRole: `${instanceId}-correction-role`,
      correctionVersion: `${instanceId}-correction-version`,
      correctionJurisdiction: `${instanceId}-correction-jurisdiction`,
    }),
    [instanceId],
  );

  function setImportBusyState(value) {
    importBusyRef.current = value;
    setImportBusy(value);
  }

  function setCorrectionBusyState(value) {
    correctionBusyRef.current = value;
    setCorrectionBusy(value);
  }

  function isLive(scope, signal) {
    return mountedRef.current
      && scopeRef.current === scope
      && !signal?.aborted;
  }

  function acceptSourceList(next, scope) {
    if (!isLive(scope)) return false;
    setSources(next);
    setSourcesProjectId(scope.projectId);
    setExcludedKeys((previous) => {
      const currentKeys = new Set(
        next.filter(isStoredSource).map((record) => record.source.logical_source_key),
      );
      const retained = new Set(
        [...previous].filter((key) => currentKeys.has(key)),
      );
      if (retained.size === previous.size && [...retained].every((key) => previous.has(key))) {
        return previous;
      }
      return retained;
    });
    return true;
  }

  function acceptCurrentRecord(stored, scope) {
    if (!isLive(scope) || !isStoredSource(stored)) return false;
    const key = stored.source.logical_source_key;
    setSources((previous) => {
      const current = Array.isArray(previous) ? previous : [];
      const index = current.findIndex(
        (record) => record?.source?.logical_source_key === key,
      );
      if (index < 0) return [...current, stored];
      return current.map((record, recordIndex) => (
        recordIndex === index ? stored : record
      ));
    });
    setSourcesProjectId(scope.projectId);
    return true;
  }

  async function refreshSources(scope, signal, requestApi) {
    try {
      const payload = await requestApi.listSources(scope.projectId, { signal });
      if (!isLive(scope, signal)) return false;
      return acceptSourceList(sourceListFrom(payload), scope);
    } catch (error) {
      if (!isLive(scope, signal) || isAbortError(error)) return false;
      setLoadError({ message: errorMessageOf(error), nextStep: nextStepOf(error) });
      return false;
    }
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      listControllerRef.current?.abort();
      importControllerRef.current?.abort();
      correctionControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    const scope = scopeRef.current;
    const controller = new AbortController();
    const requestApi = apiRef.current;
    listControllerRef.current = controller;

    setViewProjectId(scope.projectId);
    setSources(null);
    setSourcesProjectId(null);
    setLoadError(null);
    if (viewProjectId !== scope.projectId) setExcludedKeys(new Set());
    setPendingFiles([]);
    setImportRole("");
    setImportBusyState(false);
    setImportStatus(null);
    setImportError(null);
    setCorrection(null);
    setCorrectionBusyState(false);
    setNotice(null);

    requestApi.listSources(scope.projectId, { signal: controller.signal })
      .then((payload) => {
        if (!isLive(scope, controller.signal)) return;
        acceptSourceList(sourceListFrom(payload), scope);
        setLoadError(null);
      })
      .catch((error) => {
        if (!isLive(scope, controller.signal) || isAbortError(error)) return;
        setLoadError({ message: errorMessageOf(error), nextStep: nextStepOf(error) });
      });

    return () => {
      controller.abort();
      if (listControllerRef.current === controller) listControllerRef.current = null;
      importControllerRef.current?.abort();
      correctionControllerRef.current?.abort();
    };
  }, [projectId, reloadToken, refreshKey]);

  const projectViewReady = viewProjectId === projectId;
  const visibleSources = projectViewReady && sourcesProjectId === projectId ? sources : null;
  const currentSources = useMemo(
    () => (Array.isArray(visibleSources) ? visibleSources : []),
    [visibleSources],
  );
  const selectedSourceIds = useMemo(
    () => currentSources
      .filter((record) => (
        isStoredSource(record)
        && !excludedKeys.has(record.source.logical_source_key)
      ))
      .map((record) => record.source.source_artifact_id),
    [currentSources, excludedKeys],
  );
  const prepareDisabled = visibleSources === null || importBusy || correctionBusy || pendingFiles.length > 0;
  const canEditBrief = typeof onBriefChange === "function";

  function stageFile(event) {
    const files = Array.from(event.target.files ?? []);
    const file = files[0] ?? null;
    event.target.value = "";
    setImportStatus(null);
    setImportError(null);
    setNotice(null);
    if (!file) {
      setPendingFiles([]);
      setImportRole("");
      return;
    }
    if (files.some((item) => typeof item.name !== "string" || !/\.docx$/iu.test(item.name))) {
      setPendingFiles([]);
      setImportRole("");
      setImportError({
        message: "请选择DOCX格式的Word文件。",
        nextStep: "请在Word中确认后另存为DOCX，再重新选择。",
      });
      return;
    }
    if (new Set(files.map((item) => item.name)).size !== files.length) {
      setPendingFiles([]);
      setImportError({ message: "所选文件中有同名文件，请分别添加并核对资料名称。" });
      return;
    }
    setPendingFiles(files);
    setImportRole("");
  }

  async function confirmImport() {
    const files = [...pendingFiles];
    const file = files[0];
    const role = importRole;
    const scope = scopeRef.current;
    if (
      !file
      || !role
      || visibleSources === null
      || importBusyRef.current
      || correctionBusyRef.current
      || !isLive(scope)
    ) return;

    const requestApi = apiRef.current;
    const controller = new AbortController();
    importControllerRef.current?.abort();
    importControllerRef.current = controller;
    setImportBusyState(true);
    setImportError(null);
    setImportStatus(null);
    setNotice(null);

    try {
      for (const file of files) {
        if (!isLive(scope, controller.signal)) return;
        const result = await requestApi.importSource(
          scope.projectId,
          {
            file,
            logicalSourceKey: file.name,
            sourceRole: role,
            sourceVersion: "",
            jurisdiction: "",
          },
          { signal: controller.signal },
        );
        if (!isLive(scope, controller.signal)) return;

        const current = result?.current;
        if (!isStoredSource(current)) {
          setImportError({
            message: "保存结果未能确认当前资料。",
            nextStep: "请先查看已保存的资料，确认前不要重复上传。",
          });
          await refreshSources(scope, controller.signal, requestApi);
          return;
        }

        acceptCurrentRecord(current, scope);
        setPendingFiles((remaining) => remaining.filter((item) => item !== file));
        setImportStatus({
          tone: "ok",
          text: result?.replayed
            ? "这份文件此前已保存，已在当前资料中。"
            : "已保存。",
        });
      }
      setImportRole("");
    } catch (error) {
      if (!isLive(scope, controller.signal) || isAbortError(error)) return;
      setImportError({ message: errorMessageOf(error), nextStep: nextStepOf(error) });
      await refreshSources(scope, controller.signal, requestApi);
    } finally {
      if (isLive(scope, controller.signal)) {
        setImportBusyState(false);
        if (importControllerRef.current === controller) importControllerRef.current = null;
      }
    }
  }

  function openCorrection(record) {
    const identity = record?.source;
    if (correctionBusyRef.current || importBusyRef.current || !isStoredSource(record)) return;
    setNotice(null);
    setCorrection({
      id: identity.source_artifact_id,
      key: identity.logical_source_key,
      role: identity.source_role ?? "",
      version: "",
      jurisdiction: "",
      currentVersion: identity.source_version ?? "",
      currentJurisdiction: identity.jurisdiction ?? "",
    });
  }

  function patchCorrection(partial) {
    setCorrection((previous) => (previous ? { ...previous, ...partial } : previous));
  }

  async function submitCorrection() {
    const editing = correction;
    const scope = scopeRef.current;
    if (
      !editing
      || correctionBusyRef.current
      || importBusyRef.current
      || !isLive(scope)
    ) return;

    const requestApi = apiRef.current;
    const controller = new AbortController();
    correctionControllerRef.current?.abort();
    correctionControllerRef.current = controller;
    setCorrectionBusyState(true);
    setNotice(null);
    const body = {
      source_role: editing.role,
      source_version: editing.clearVersion ? UNMARKED_VERSION : editing.version.trim()
        || String(editing.currentVersion || "").trim()
        || UNMARKED_VERSION,
      jurisdiction: editing.clearJurisdiction ? UNSPECIFIED_JURISDICTION : editing.jurisdiction.trim()
        || String(editing.currentJurisdiction || "").trim()
        || UNSPECIFIED_JURISDICTION,
    };

    try {
      const result = await requestApi.correctSourceMetadata(
        scope.projectId,
        editing.id,
        body,
        { signal: controller.signal },
      );
      if (!isLive(scope, controller.signal)) return;

      const current = result?.current;
      if (!isStoredSource(current)) {
        setCorrection(null);
        setNotice({
          tone: "error",
          message: "更正结果未能确认当前资料。",
          nextStep: "请刷新资料列表，在当前版本上查看。",
        });
        await refreshSources(scope, controller.signal, requestApi);
        return;
      }

      acceptCurrentRecord(current, scope);
      setCorrection(null);
      setNotice({
        tone: "ok",
        message: result?.replayed ? "资料信息未变化，无需更正。" : "已保存更正。",
      });
    } catch (error) {
      if (!isLive(scope, controller.signal) || isAbortError(error)) return;
      setCorrection(null);
      setNotice({
        tone: "error",
        message: errorMessageOf(error),
        nextStep: nextStepOf(error),
      });
      await refreshSources(scope, controller.signal, requestApi);
    } finally {
      if (isLive(scope, controller.signal)) {
        setCorrectionBusyState(false);
        if (correctionControllerRef.current === controller) correctionControllerRef.current = null;
      }
    }
  }

  function toggleIncluded(key, included) {
    if (!projectViewReady) return;
    const next = new Set(excludedKeys);
    if (included) next.delete(key);
    else next.add(key);
    setExcludedKeys(next);
    onExcludedKeysChange?.([...next]);
  }

  function handlePrepare() {
    if (typeof onPrepare !== "function" || prepareDisabled) return;
    onPrepare({ userBrief: brief, sourceArtifactIds: [...selectedSourceIds] });
  }

  const visiblePendingFile = projectViewReady ? pendingFile : null;
  const visibleImportStatus = projectViewReady ? importStatus : null;
  const visibleImportError = projectViewReady ? importError : null;
  const visibleLoadError = projectViewReady ? loadError : null;
  const visibleCorrection = projectViewReady ? correction : null;
  const visibleNotice = projectViewReady ? notice : null;

  return (
    <section className="pvs-intake" aria-labelledby={ids.title}>
      <header className="pvs-head">
        <h3 className="pvs-title" id={ids.title}>资料来源</h3>
        <p className="pvs-sub">
          保存Word原文与资料分类，供后续写作使用；医学内容的确认在后续步骤完成。
        </p>
      </header>

      <div className="pvs-add-row">
        <label className="pvs-add" htmlFor={ids.file}>
          <FilePlus2 size={16} aria-hidden="true" />
          添加DOCX文件
        </label>
        <input
          className="pvs-file-input"
          id={ids.file}
          type="file"
          multiple
          accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          aria-label="选择要添加的DOCX文件"
          onChange={stageFile}
          disabled={!projectViewReady || visibleSources === null || importBusy || correctionBusy}
        />
        {visibleImportStatus && (
          <p className="pvs-ok" role="status" aria-live="polite">
            {visibleImportStatus.text}
          </p>
        )}
      </div>

      {visibleImportError && (
        <div className="pvs-error" role="alert">
          <p>{visibleImportError.message}</p>
          {visibleImportError.nextStep && <p className="pvs-error-step">{visibleImportError.nextStep}</p>}
        </div>
      )}

      {visiblePendingFile && (
        <div className="pvs-stage">
          <p className="pvs-stage-name">将添加：{pendingFiles.map((item) => item.name).join("、")}</p>
          {pendingFiles.length > 1 && <p className="pvs-hint">本组共 {pendingFiles.length} 份文件，使用下方同一类别；不同类别可分组添加。</p>}
          <p className="pvs-hint">
            以文件名作为资料名称；版本与地区未识别时保持未注明，保存后可随时更正。
          </p>
          <div className="pvs-row">
            <label htmlFor={ids.importRole}>资料类别</label>
            <select
              id={ids.importRole}
              aria-describedby={ids.importRoleHint}
              value={importRole}
              onChange={(event) => setImportRole(event.target.value)}
            >
              <option value="">请选择资料类别</option>
              {SOURCE_ROLE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="pvs-primary"
              onClick={confirmImport}
              disabled={!importRole || importBusy}
            >
              {importBusy ? "正在保存…" : "保存到资料"}
            </button>
            <button
              type="button"
              className="pvs-ghost"
              onClick={() => {
                setPendingFiles([]);
                setImportRole("");
              }}
              disabled={importBusy}
            >
              取消添加
            </button>
          </div>
          <p className="pvs-hint" id={ids.importRoleHint}>
            请选择最符合文件用途的类别；选择类别不代表确认其中的医学内容。
          </p>
        </div>
      )}

      <div className="pvs-brief">
        <label htmlFor={ids.brief}>写作说明（可选）</label>
        <textarea
          id={ids.brief}
          rows={2}
          value={brief}
          placeholder="补充本次写作的意图或注意事项，可留空。"
          readOnly={!canEditBrief}
          onChange={canEditBrief ? (event) => onBriefChange(event.target.value) : undefined}
        />
      </div>

      {visibleLoadError && (
        <div className="pvs-error" role="alert">
          <p>{visibleLoadError.message}</p>
          {visibleLoadError.nextStep && <p className="pvs-error-step">{visibleLoadError.nextStep}</p>}
          <button
            type="button"
            className="pvs-ghost"
            onClick={() => {
              setLoadError(null);
              setReloadToken((token) => token + 1);
            }}
          >
            重试
          </button>
        </div>
      )}

      {visibleSources === null && !visibleLoadError && (
        <p className="pvs-hint">正在读取已保存的资料…</p>
      )}

      {visibleSources !== null && currentSources.length === 0 && (
        <p className="pvs-hint">还没有已保存的资料。</p>
      )}

      {currentSources.length > 0 && (
        <>
          <p className="pvs-selection-note">
            勾选仅表示带入后续写作，默认纳入当前资料；不代表医学内容已确认。
          </p>
          <ul className="pvs-cards">
            {currentSources.map((record) => {
              const identity = record?.source;
              if (!isStoredSource(record)) return null;
              const key = identity.logical_source_key;
              const included = !excludedKeys.has(key);
              const editing = visibleCorrection?.id === identity.source_artifact_id;
              return (
                <li key={identity.source_artifact_id} className="pvs-card">
                  <div className="pvs-card-main">
                    <input
                      type="checkbox"
                      className="pvs-check"
                      checked={included}
                      aria-label={`纳入后续写作：${key}`}
                      onChange={(event) => toggleIncluded(key, event.target.checked)}
                    />
                    <div className="pvs-card-info">
                      <span className="pvs-card-name">{key}</span>
                      <span className="pvs-card-meta">
                        {roleLabel(identity.source_role)} · {versionText(identity.source_version)} ·{" "}
                        {jurisdictionText(identity.jurisdiction)}
                      </span>
                    </div>
                  </div>
                  <div className="pvs-card-actions">
                    <a
                      className="pvs-link"
                      href={apiRef.current.sourceDownloadUrl(projectId, identity.source_artifact_id)}
                      download
                    >
                      <Download size={14} aria-hidden="true" />
                      下载原文件
                    </a>
                    <button
                      type="button"
                      className="pvs-ghost"
                      onClick={() => openCorrection(record)}
                      disabled={correctionBusy || importBusy}
                    >
                      <PencilLine size={14} aria-hidden="true" />
                      更正类别或版本
                    </button>
                  </div>
                  {editing && (
                    <div className="pvs-correct">
                      <p className="pvs-hint">
                        更正资料分类，不重新上传文件；原文与历史记录保持不变。
                      </p>
                      <div className="pvs-row">
                        <label htmlFor={ids.correctionRole}>更正类别</label>
                        <select
                          id={ids.correctionRole}
                          value={visibleCorrection.role}
                          onChange={(event) => patchCorrection({ role: event.target.value })}
                        >
                          {SOURCE_ROLE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          className="pvs-primary"
                          onClick={submitCorrection}
                          disabled={correctionBusy || importBusy}
                        >
                          {correctionBusy ? "正在保存…" : "保存更正"}
                        </button>
                        <button
                          type="button"
                          className="pvs-ghost"
                          onClick={() => setCorrection(null)}
                          disabled={correctionBusy || importBusy}
                        >
                          取消更正
                        </button>
                      </div>
                      <div className="pvs-correct-fields">
                        <div className="pvs-correct-field">
                          <label htmlFor={ids.correctionVersion}>版本（留空保持原值）</label>
                          <input
                            id={ids.correctionVersion}
                            type="text"
                            value={visibleCorrection.version}
                            onChange={(event) => patchCorrection({ version: event.target.value, clearVersion: false })}
                          />
                          <button type="button" className="pvs-ghost"
                            disabled={correctionBusy || visibleCorrection.clearVersion}
                            onClick={() => patchCorrection({ version: "", clearVersion: true })}>
                            版本改为未注明
                          </button>
                          {visibleCorrection.clearVersion && <span className="pvs-hint">保存后版本将改为未注明</span>}
                          <span className="pvs-hint">
                            当前：{currentValue(visibleCorrection.currentVersion)}
                          </span>
                        </div>
                        <div className="pvs-correct-field">
                          <label htmlFor={ids.correctionJurisdiction}>地区（留空保持原值）</label>
                          <input
                            id={ids.correctionJurisdiction}
                            type="text"
                            value={visibleCorrection.jurisdiction}
                            onChange={(event) => patchCorrection({ jurisdiction: event.target.value, clearJurisdiction: false })}
                          />
                          <button type="button" className="pvs-ghost"
                            disabled={correctionBusy || visibleCorrection.clearJurisdiction}
                            onClick={() => patchCorrection({ jurisdiction: "", clearJurisdiction: true })}>
                            地区改为未注明
                          </button>
                          {visibleCorrection.clearJurisdiction && <span className="pvs-hint">保存后地区将改为未注明</span>}
                          <span className="pvs-hint">
                            当前：{currentValue(visibleCorrection.currentJurisdiction)}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {visibleNotice && (
        <div
          className={visibleNotice.tone === "error" ? "pvs-error" : "pvs-ok"}
          role={visibleNotice.tone === "error" ? "alert" : "status"}
          aria-live="polite"
        >
          <p>{visibleNotice.message}</p>
          {visibleNotice.nextStep && <p className="pvs-error-step">{visibleNotice.nextStep}</p>}
          <button type="button" className="pvs-ghost" onClick={() => setNotice(null)}>
            知道了
          </button>
        </div>
      )}

      {typeof onPrepare === "function" && (
        <footer className="pvs-prepare">
          <button
            type="button"
            className="pvs-primary"
            onClick={handlePrepare}
            disabled={prepareDisabled}
          >
            准备写作材料
          </button>
          <span className="pvs-hint">{pendingFiles.length > 0
            ? "请先保存或取消待添加的文件，再开始整理。"
            : `将使用已勾选的 ${selectedSourceIds.length} 份资料。`}</span>
        </footer>
      )}
    </section>
  );
}

export default ProtocolSourceIntake;
