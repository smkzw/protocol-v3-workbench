import { useEffect, useRef, useState } from "react";
import "./RegimenProposalCard.css";

const KIND_LABELS = {
  loading: "负荷",
  maintenance: "维持",
  transition: "过渡",
  single: "单次",
  other: "其他",
};

const SUPPORT_LABELS = {
  project_material: "来自所提供的方案资料",
  reference_only: "参考资料中的信息",
  ai_recommendation: "AI建议，仍需结合研究确认",
};

function supportLabel(value) {
  return SUPPORT_LABELS[value] || "来源待核对";
}

function kindLabel(kind) {
  return KIND_LABELS[kind] || "步骤";
}

function quantityText(quantity) {
  if (!quantity || quantity.value === undefined || quantity.value === null || !quantity.unit) return "";
  return `${quantity.value} ${quantity.unit}`;
}

function publicError(error) {
  const text = error?.detail?.message || error?.message || (typeof error === "string" ? error : "");
  return typeof text === "string" && /[\u3400-\u9fff]/u.test(text) ? text : "确认未能完成，请稍后重试。";
}

function resolveDownloadUrl(sourceDownloadUrl, sourceArtifactId) {
  if (typeof sourceDownloadUrl !== "function") return "";
  const url = sourceDownloadUrl(sourceArtifactId);
  return typeof url === "string" && url.trim() ? url : "";
}

function openItems(proposal) {
  const questions = Array.isArray(proposal?.questions) ? proposal.questions.filter(Boolean) : [];
  const unresolved = Array.isArray(proposal?.regimen?.unresolved_questions)
    ? proposal.regimen.unresolved_questions.filter(Boolean)
    : [];
  return [...questions, ...unresolved];
}

function periodById(regimen, periodId) {
  return (regimen?.periods || []).find((period) => period.id === periodId) || null;
}

function armById(regimen, armId) {
  return (regimen?.arms || []).find((arm) => arm.id === armId) || null;
}

function StepEvidence({ references }) {
  if (!Array.isArray(references) || references.length === 0) return null;
  return (
    <details className="rpc-evidence">
      <summary>查看原文依据</summary>
      {references.map((reference, index) => (
        <div key={index} className="rpc-evidence-item"><blockquote>{reference.quote}</blockquote></div>
      ))}
    </details>
  );
}

function ScheduleUnit({ schedule, regimen }) {
  const period = periodById(regimen, schedule.period_id);
  const arm = armById(regimen, schedule.arm_id);
  return (
    <article className="rpc-unit">
      <header className="rpc-unit-head">
        <h3>{period?.label || "治疗期"}</h3>
        {period?.timing ? <p className="rpc-muted">{period.timing}</p> : null}
        <p className="rpc-arm">{arm?.label || "组别"}</p>
      </header>
      <ol className="rpc-steps">
        {(schedule.steps || []).map((step, stepIndex) => (
          <li key={stepIndex} className="rpc-step">
            <div className="rpc-step-meta">
              <span className="rpc-kind">{kindLabel(step.kind)}</span>
              {step.timing ? <span>{step.timing}</span> : null}
              {step.frequency ? <span>{step.frequency}</span> : null}
              {step.route ? <span>{step.route}</span> : null}
            </div>
            <ul className="rpc-products">
              {(step.products || []).map((product, productIndex) => {
                const dose = quantityText(product.dose);
                const volume = quantityText(product.volume);
                return (
                  <li key={productIndex}>
                    <strong>{product.name}</strong>
                    {dose ? <span className="rpc-quantity">{dose}</span> : null}
                    {volume ? <span className="rpc-quantity">{volume}</span> : null}
                  </li>
                );
              })}
            </ul>
            <p className="rpc-support">{supportLabel(step.source_support)}</p>
            <StepEvidence references={step.references} />
          </li>
        ))}
      </ol>
    </article>
  );
}

export function RegimenProposalCard({
  proposal,
  onConfirm,
  busy = false,
  confirmationBlockedReason = "",
  error = "",
  savedReceipt = null,
  sourceDownloadUrl,
}) {
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState("");
  const confirmingRef = useRef(false);
  const requestGeneration = useRef(0);

  const proposalKey = JSON.stringify(proposal);
  useEffect(() => {
    requestGeneration.current += 1;
    confirmingRef.current = false;
    setConfirming(false);
    setConfirmError("");
  }, [proposalKey]);

  const regimen = proposal?.regimen || null;
  const pending = openItems(proposal);
  const schedules = Array.isArray(regimen?.schedules) ? regimen.schedules : [];
  const downloadSources = new Map();
  for (const schedule of schedules) {
    for (const step of schedule.steps || []) {
      for (const reference of step.references || []) {
        const id = reference.source_artifact_id;
        if (!downloadSources.has(id)) {
          const url = resolveDownloadUrl(sourceDownloadUrl, id);
          if (url) downloadSources.set(id, url);
        }
      }
    }
  }
  const canConfirm = typeof onConfirm === "function"
    && !savedReceipt
    && !busy
    && !confirmationBlockedReason
    && !confirming
    && proposal?.status === "ready_for_review"
    && Boolean(regimen)
    && pending.length === 0;

  async function handleConfirm() {
    if (!canConfirm || confirmingRef.current) return;
    confirmingRef.current = true;
    const generation = requestGeneration.current;
    setConfirming(true);
    setConfirmError("");
    try {
      await onConfirm(proposal);
      if (generation !== requestGeneration.current) return;
    } catch (thrown) {
      if (generation !== requestGeneration.current) return;
      setConfirmError(publicError(thrown));
    } finally {
      if (generation === requestGeneration.current) {
        confirmingRef.current = false;
        setConfirming(false);
      }
    }
  }

  const alertText = confirmError || (typeof error === "string" ? error : "");
  let blockReason = "";
  if (savedReceipt) blockReason = "原确认记录已保留；后续研究修改的有效性以当前研究版本为准。";
  else if (!regimen) blockReason = "当前没有可确认的给药方案。";
  else if (proposal?.status !== "ready_for_review") blockReason = "当前仍为建议状态，尚未达到可确认条件。";
  else if (typeof onConfirm !== "function") blockReason = "确认操作暂不可用。";
  else if (confirmationBlockedReason) blockReason = confirmationBlockedReason;
  else if (busy) blockReason = "正在处理中，请稍候。";

  return (
    <section className="rpc-card" aria-label="剂量方案">
      <header className="rpc-heading">
        <div className="rpc-title-row">
          <h2>剂量方案</h2>
          <span className="rpc-tag">{savedReceipt ? "监管答辩级·确认记录" : "监管答辩级·需确认"}</span>
        </div>
        <p className="rpc-status" role="status">{savedReceipt ? "本次选择已保存" : "建议，尚未确认"}</p>
      </header>

      {regimen ? (
        <div className="rpc-grid">
          {schedules.map((schedule, index) => (
            <ScheduleUnit
              key={`${schedule.period_id}:${schedule.arm_id}:${index}`}
              schedule={schedule}
              regimen={regimen}
            />
          ))}
        </div>
      ) : (
        <p className="rpc-empty">资料尚不足以形成完整给药方案。</p>
      )}

      {downloadSources.size > 0 ? (
        <div className="rpc-source-links" aria-label="原始资料">
          {[...downloadSources].map(([id, url]) => <a key={id} href={url} download>下载对应原文件</a>)}
        </div>
      ) : null}

      {pending.length > 0 ? (
        <div className="rpc-pending" role="status">
          <p>仍有未决事项，确认前需先处理：</p>
          <ul>
            {pending.map((item, index) => <li key={index}>{item}</li>)}
          </ul>
        </div>
      ) : null}

      {!canConfirm && !pending.length && blockReason ? (
        <p className="rpc-block-reason" role="status">{blockReason}</p>
      ) : null}

      {alertText ? <div className="rpc-error" role="alert"><p>{alertText}</p></div> : null}

      <div className="rpc-actions">
        <button
          type="button"
          className="rpc-confirm"
          disabled={!canConfirm}
          onClick={handleConfirm}
        >
          {savedReceipt ? "原确认记录已保存" : "确认这套给药方案"}
        </button>
      </div>
    </section>
  );
}
