"use client";

import { API_BASE } from "@/lib/api";
import { useState, useCallback } from "react";
import { Button, ConfirmDialog } from "@/components/ui";


const PIPELINE_STAGES = [
  "alignment",
  "coverage",
  "variants",
  "annotation",
  "sv",
  "cnv",
  "taxonomy",
  "unknown_reads",
  "mtdna",
  "prs",
];

export function formatStageLabel(stage) {
  return stage.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function stageStatus(steps, stage) {
  return steps?.find((s) => s.step_name === stage)?.status || "queued";
}

function stageOptions(run) {
  const configured = run?.parameters?.stages;
  if (Array.isArray(configured) && configured.length) {
    const seen = new Set();
    return configured.filter((stage) => {
      if (!PIPELINE_STAGES.includes(stage) || seen.has(stage)) return false;
      seen.add(stage);
      return true;
    });
  }
  return PIPELINE_STAGES;
}

function canPlanStage(run) {
  return ["queued", "failed", "cancelled", "interrupted", "done"].includes(run?.status);
}

function canSkipStageNow(run) {
  return ["running", "queued", "paused"].includes(run?.status);
}

function stageActionLabel(action) {
  if (action === "only_stage") return "Run only";
  if (action === "skip_stage") return "Skip";
  return "Resume from";
}

function actionBodyForStage(action, stage, note) {
  if (action === "only_stage") {
    return { resume_existing: true, only_stages: [stage], skip_reason: note || undefined };
  }
  return { resume_existing: true, from_stage: stage, skip_reason: note || undefined };
}

export function StageActionButtons({
  run,
  stage,
  steps = [],
  onRefresh,
  onError,
  compact = false,
  showStatus = false,
}) {
  const [pending, setPending] = useState(null);
  const [error, setError] = useState(null);
  const [confirmAction, setConfirmAction] = useState(null);
  const status = stageStatus(steps, stage);
  const canPlan = canPlanStage(run);
  const canSkip = canSkipStageNow(run);

  const doStageAction = useCallback(
    async (action) => {
      if (!run?.id || !stage) return;
      setPending(action);
      setError(null);
      onError?.(null);
      try {
        const isSkip = action === "skip_stage";
        const url = isSkip
          ? `${API_BASE}/runs/${run.id}/stages/${stage}/skip`
          : `${API_BASE}/runs/${run.id}/pipeline/start`;
        const body = isSkip
          ? { reason: "operator requested from pipeline step control" }
          : actionBodyForStage(action, stage);
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const payload = await res.json().catch(() => ({}));
          const detail =
            typeof payload.detail === "string"
              ? payload.detail
              : payload.detail?.message || payload.detail?.code || `HTTP ${res.status}`;
          throw new Error(detail);
        }
        onRefresh?.();
      } catch (e) {
        const message = e.message || "Stage action failed";
        setError(message);
        onError?.(message);
      } finally {
        setPending(null);
      }
    },
    [run?.id, stage, onRefresh, onError]
  );

  if (!run?.id || !stage) return null;
  if (!canPlan && !canSkip) {
    return showStatus ? (
      <span style={miniHintStyle}>No step action for {run.status}</span>
    ) : null;
  }

  const disabled = !!pending;
  const size = compact ? "sm" : "md";
  const confirmation = confirmAction ? stageConfirmationCopy(confirmAction, stage) : null;

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        {showStatus && (
          <span style={miniHintStyle}>
            {formatStageLabel(stage)} · {status}
          </span>
        )}
        {canPlan && (
          <>
            <Button
              variant="ghost"
              size={size}
              disabled={disabled}
              onClick={() => setConfirmAction("resume_from")}
              title="Resume this run from the selected stage. Dependency checks still apply."
            >
              {pending === "resume_from" ? "…" : stageActionLabel("resume_from")}
            </Button>
            <Button
              variant="ghost"
              size={size}
              disabled={disabled}
              onClick={() => setConfirmAction("only_stage")}
              title="Run only this stage. Existing reusable inputs are validated by the backend."
            >
              {pending === "only_stage" ? "…" : stageActionLabel("only_stage")}
            </Button>
          </>
        )}
        {canSkip && (
          <Button
            variant="warning"
            size={size}
            disabled={disabled}
            onClick={() => setConfirmAction("skip_stage")}
            title="Skip this stage. Required-stage skips are blocked unless a reusable artifact exists."
          >
            {pending === "skip_stage" ? "…" : stageActionLabel("skip_stage")}
          </Button>
        )}
        {error && (
          <span style={{ ...miniHintStyle, color: "var(--color-err)", maxWidth: compact ? 160 : 260 }} title={error}>
            {error}
          </span>
        )}
      </div>
      {confirmation && (
        <StageActionConfirmDialog
          title={confirmation.title}
          description={confirmation.description}
          details={confirmation.details}
          confirmLabel={stageActionLabel(confirmAction)}
          confirmVariant={confirmAction === "skip_stage" ? "warning" : "primary"}
          disabled={disabled}
          onCancel={() => setConfirmAction(null)}
          onConfirm={() => {
            const action = confirmAction;
            setConfirmAction(null);
            doStageAction(action);
          }}
        />
      )}
    </>
  );
}

function stageConfirmationCopy(action, stage) {
  const label = formatStageLabel(stage);
  if (action === "only_stage") {
    return {
      title: `Run only ${label}`,
      description: "This starts a stage-scoped operation. It does not restart the whole pipeline.",
      details: [
        "Existing reusable inputs stay in place and are validated by the backend.",
        "Other stages remain unchanged unless this stage writes a newer artifact.",
      ],
    };
  }
  if (action === "skip_stage") {
    return {
      title: `Skip ${label}`,
      description: "This marks the selected stage as intentionally skipped for the current run.",
      details: [
        "Required-stage skips are rejected unless a reusable artifact already exists.",
        "Downstream stages may remain blocked if they need this stage output.",
      ],
    };
  }
  return {
    title: `Resume from ${label}`,
    description: "This resumes the run from the selected stage boundary.",
    details: [
      "Earlier completed artifacts remain available.",
      "This stage and downstream stages may be recomputed where dependency checks require it.",
    ],
  };
}

function StageActionConfirmDialog({
  title,
  description,
  details = [],
  confirmLabel,
  confirmVariant = "primary",
  disabled,
  onCancel,
  onConfirm,
}) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onCancel}>
      <div className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="stage-action-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <div>
            <div className="page-eyebrow">Stage action</div>
            <h2 id="stage-action-title">{title}</h2>
          </div>
        </div>
        <p className="modal-description">{description}</p>
        {details.length > 0 && (
          <ul className="modal-detail-list">
            {details.map((detail) => <li key={detail}>{detail}</li>)}
          </ul>
        )}
        <div className="modal-actions">
          <Button variant="secondary" onClick={onCancel} disabled={disabled}>Cancel</Button>
          <Button variant={confirmVariant} onClick={onConfirm} disabled={disabled}>{confirmLabel}</Button>
        </div>
      </div>
    </div>
  );
}

/**
 * State-driven run control buttons.
 *
 * Props:
 *   run           – run object (needs .id, .status)
 *   onRefresh     – called after a successful action to reload data
 *   compact       – if true, renders icon-only pills (for dashboard)
 *   showDelete    – if true, includes delete button (default true)
 *   className     – optional wrapper className
 */
export default function RunControls({
  run,
  steps = [],
  onRefresh,
  onError,
  compact = false,
  showDelete = true,
  errorMode = "inline",
  className = "",
}) {
  const [pending, setPending] = useState(null); // action name while in-flight
  const [error, setError] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmRunAction, setConfirmRunAction] = useState(null);
  const [stageAction, setStageAction] = useState("resume_from");
  const [selectedStage, setSelectedStage] = useState("coverage");
  const [skipReason, setSkipReason] = useState("");

  const status = run?.status;

  const doAction = useCallback(
    async (action, method = "POST", body = null, pendingLabel = action) => {
      if (!run?.id) return;
      setPending(pendingLabel);
      setError(null);
      onError?.(null);
      try {
        const url = action === "delete"
          ? `${API_BASE}/runs/${run.id}`
          : action.startsWith("/")
            ? `${API_BASE}${action}`
            : `${API_BASE}/runs/${run.id}/${action}`;
        const res = await fetch(url, {
          method,
          ...(body && {
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          const detail =
            typeof body.detail === "string"
              ? body.detail
              : body.detail?.message || body.detail?.code || `HTTP ${res.status}`;
          throw new Error(detail);
        }
        onRefresh?.();
      } catch (e) {
        const message = e.message || "Run action failed";
        setError(message);
        onError?.(message);
      } finally {
        setPending(null);
        setConfirmDelete(false);
      }
    },
    [run?.id, onRefresh, onError]
  );

  if (!run) return null;

  // ── State-driven visibility ──
  const canPause = status === "running" || status === "queued";
  const canStageBoundaryPause = !compact && status === "running";
  const canResume = status === "paused";
  const canCancel = status === "running" || status === "queued" || status === "paused" || status === "cancelling";
  const canRetry = status === "failed" || status === "cancelled" || status === "interrupted";
  const canResumeCheckpoint = status === "failed" || status === "cancelled" || status === "interrupted";
  const canDelete =
    showDelete && status !== "running" && status !== "paused"; // don't delete mid-flight
  const canStart =
    status === "queued" || status === "created";
  const canStagePlan = !compact && canPlanStage(run);
  const canSkipStage = !compact && canSkipStageNow(run);
  const effectiveStageAction = canStagePlan ? stageAction : "skip_stage";
  const selectableStages = stageOptions(run);

  const btnBase = compact
    ? {
        padding: "4px 10px",
        fontSize: 11,
        borderRadius: 5,
        border: "none",
        fontWeight: 600,
        cursor: "pointer",
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        lineHeight: 1.4,
      }
    : {
        padding: "7px 16px",
        fontSize: 13,
        borderRadius: 6,
        border: "none",
        fontWeight: 600,
        cursor: "pointer",
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        lineHeight: 1.4,
      };

  const btn = (variant) => ({
    ...btnBase,
    ...(variant === "cancel" && {
      background: "var(--color-warn)",
      color: "#000",
    }),
    ...(variant === "pause" && {
      background: "var(--color-bg-elevated)",
      border: "1px solid var(--color-warn)",
      color: "var(--color-warn)",
    }),
    ...(variant === "resume" && {
      background: "var(--color-ok)",
      color: "#000",
    }),
    ...(variant === "retry" && {
      background: "var(--color-accent)",
      color: "#000",
    }),
    ...(variant === "start" && {
      background: "var(--color-ok)",
      color: "#000",
    }),
    ...(variant === "delete" && {
      background: "transparent",
      border: "1px solid var(--color-err)",
      color: "var(--color-err)",
    }),
  });

  return (
    <div
      className={className}
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        gap: compact ? 6 : 10,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: compact ? 6 : 10,
          flexWrap: "wrap",
        }}
      >
        {/* Start pipeline (queued run without auto-start) */}
        {canStart && (
          <button
            style={{
              ...btn("start"),
              opacity: pending === "pipeline/start" ? 0.6 : 1,
              cursor: pending ? "wait" : "pointer",
            }}
            disabled={!!pending}
            onClick={() => doAction("pipeline/start")}
            title="Start pipeline execution"
          >
            {compact ? "▶" : "▶ Start"}
            {!compact && pending === "pipeline/start" && " …"}
          </button>
        )}

        {/* Pause/resume pipeline */}
        {canPause && (
          <button
            style={{
              ...btn("pause"),
              opacity: pending === "pause" ? 0.6 : 1,
              cursor: pending ? "wait" : "pointer",
            }}
            disabled={!!pending}
            onClick={() => doAction("pause")}
            title="Pause pipeline with minimal progress loss where supported"
          >
            {compact ? "⏸" : "⏸ Pause"}
            {!compact && pending === "pause" && " …"}
          </button>
        )}

        {canStageBoundaryPause && (
          <button
            style={{
              ...btn("pause"),
              opacity: pending === "stage-pause" ? 0.6 : 1,
              cursor: pending ? "wait" : "pointer",
            }}
            disabled={!!pending}
            onClick={() => doAction("pause", "POST", { mode: "stage_boundary" }, "stage-pause")}
            title="Wait for the active stage to finish, then pause before the next stage starts"
          >
            ⏸ Stage end
            {pending === "stage-pause" && " …"}
          </button>
        )}

        {canResume && (
          <button
            style={{
              ...btn("resume"),
              opacity: pending === "resume" ? 0.6 : 1,
              cursor: pending ? "wait" : "pointer",
            }}
            disabled={!!pending}
            onClick={() => doAction("resume")}
            title="Resume paused pipeline"
          >
            {compact ? "▶" : "▶ Resume"}
            {!compact && pending === "resume" && " …"}
          </button>
        )}

        {/* Cancel running/queued pipeline */}
        {canCancel && (
          <button
            style={{
              ...btn("cancel"),
              opacity: pending === "cancel" ? 0.6 : 1,
              cursor: pending ? "wait" : "pointer",
            }}
            disabled={!!pending}
            onClick={() => setConfirmRunAction({ type: "cancel", action: "cancel" })}
            title="Cancel pipeline — completed stages preserved"
          >
            {compact ? "■" : status === "cancelling" ? "■ Cancelling…" : "■ Cancel"}
            {!compact && pending === "cancel" && " …"}
          </button>
        )}

        {/* Resume failed/cancelled run in-place so /data/results/<run_id> checkpoints are reused */}
        {canResumeCheckpoint && (
          <button
            style={{
              ...btn("resume"),
              opacity: pending === "pipeline/start" ? 0.6 : 1,
              cursor: pending ? "wait" : "pointer",
            }}
            disabled={!!pending}
            onClick={() => doAction("pipeline/start", "POST", { resume_existing: true })}
            title="Resume only when a valid checkpoint exists; blocks instead of remapping from FASTQ"
          >
            {compact ? "▶" : "▶ Resume"}
            {!compact && pending === "pipeline/start" && " …"}
          </button>
        )}

        {/* Retry failed/cancelled */}
        {canRetry && (
          <button
            style={{
              ...btn("retry"),
              opacity: pending === "retry" ? 0.6 : 1,
              cursor: pending ? "wait" : "pointer",
            }}
            disabled={!!pending}
            onClick={() => setConfirmRunAction({ type: "retry", action: "retry" })}
            title="Create a new run with the same parameters; existing run checkpoints are not reused"
          >
            {compact ? "↻" : "↻ Retry new"}
            {!compact && pending === "retry" && " …"}
          </button>
        )}

        {/* Delete */}
        {canDelete &&
          (confirmDelete ? (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: compact ? 11 : 13,
            }}
          >
            <span style={{ color: "var(--color-text-secondary)" }}>
              Confirm?
            </span>
            <button
              style={{
                ...btn("delete"),
                background: "var(--color-err)",
                color: "#fff",
                border: "none",
              }}
              disabled={!!pending}
              onClick={() => doAction("delete", "DELETE")}
            >
              {pending === "delete" ? "…" : "Delete"}
            </button>
            <button
              style={{
                ...btnBase,
                background: "var(--color-bg-elevated)",
                color: "var(--color-text-secondary)",
                border: "1px solid var(--color-border-default)",
              }}
              onClick={() => setConfirmDelete(false)}
            >
              No
            </button>
          </span>
          ) : (
          <button
            style={btn("delete")}
            disabled={!!pending}
            onClick={() => setConfirmDelete(true)}
            title="Delete this run and all associated data"
          >
            {compact ? "🗑" : "🗑 Delete"}
          </button>
          ))}

        {/* Status hint when no actions available */}
        {!canStart && !canCancel && !canResumeCheckpoint && !canRetry && !canDelete && (
          <span
            style={{
              fontSize: compact ? 10 : 12,
              color: "var(--color-text-muted)",
              fontStyle: "italic",
            }}
          >
            {status === "done" ? "Run complete" : `Status: ${status}`}
          </span>
        )}
      </div>

      {(canStagePlan || canSkipStage) && (
        <div
          style={{
            width: "100%",
            display: "grid",
            gridTemplateColumns: "minmax(140px, 180px) minmax(180px, 1fr) minmax(180px, 1fr) auto",
            gap: 8,
            alignItems: "center",
            padding: "10px 0 0",
            borderTop: "1px solid var(--color-border-muted)",
          }}
        >
          <select
            value={effectiveStageAction}
            onChange={(e) => setStageAction(e.target.value)}
            style={stageControlStyle}
            disabled={!!pending}
            title="Choose stage-level operation"
          >
            {canStagePlan && <option value="resume_from">Resume from stage</option>}
            {canStagePlan && <option value="only_stage">Run selected stage only</option>}
            {canSkipStage && <option value="skip_stage">Skip stage</option>}
          </select>
          <select
            value={selectedStage}
            onChange={(e) => setSelectedStage(e.target.value)}
            style={stageControlStyle}
            disabled={!!pending}
            title="Pipeline stage"
          >
            {selectableStages.map((stage) => (
              <option key={stage} value={stage}>
                {formatStageLabel(stage)} · {stageStatus(steps, stage)}
              </option>
            ))}
          </select>
          <input
            value={skipReason}
            onChange={(e) => setSkipReason(e.target.value)}
            placeholder={effectiveStageAction === "skip_stage" ? "Reason, optional" : "Operator note, optional"}
            style={stageControlStyle}
            disabled={!!pending}
          />
          <button
            style={{
              ...btn(effectiveStageAction === "skip_stage" ? "pause" : "resume"),
              opacity: pending === "stage-action" ? 0.6 : 1,
              whiteSpace: "nowrap",
            }}
            disabled={!!pending}
            onClick={() => {
              if (effectiveStageAction === "skip_stage") {
                setConfirmRunAction({
                  type: "skip_stage",
                  action: `/runs/${run.id}/stages/${selectedStage}/skip`,
                  method: "POST",
                  body: { reason: skipReason || "operator requested skip" },
                  pendingLabel: "stage-action",
                  stage: selectedStage,
                });
                return;
              }
              const body = effectiveStageAction === "only_stage"
                ? { resume_existing: true, only_stages: [selectedStage], skip_reason: skipReason || undefined }
                : { resume_existing: true, from_stage: selectedStage, skip_reason: skipReason || undefined };
              setConfirmRunAction({
                type: effectiveStageAction,
                action: "pipeline/start",
                method: "POST",
                body,
                pendingLabel: "stage-action",
                stage: selectedStage,
              });
            }}
          >
            {pending === "stage-action" ? "Working…" : effectiveStageAction === "skip_stage" ? "Skip" : "Start"}
          </button>
        </div>
      )}

      <ConfirmDialog
        open={!!confirmRunAction}
        {...runActionConfirmationCopy(confirmRunAction)}
        busy={!!pending}
        onCancel={() => setConfirmRunAction(null)}
        onConfirm={() => {
          const confirmed = confirmRunAction;
          setConfirmRunAction(null);
          doAction(confirmed.action, confirmed.method || "POST", confirmed.body || null, confirmed.pendingLabel || confirmed.action);
        }}
      />

      {/* Error feedback */}
      {error && errorMode === "inline" && (
        <div
          style={{
            fontSize: compact ? 11 : 12,
            color: "var(--color-err)",
            maxWidth: compact ? 420 : 720,
            whiteSpace: "normal",
            overflowWrap: "anywhere",
            lineHeight: 1.35,
            padding: compact ? "7px 9px" : "9px 11px",
            border: "1px solid color-mix(in srgb, var(--color-err) 42%, transparent)",
            borderRadius: 6,
            background: "color-mix(in srgb, var(--color-err) 12%, transparent)",
          }}
          title={error}
        >
          {error}
        </div>
      )}
    </div>
  );
}

function runActionConfirmationCopy(action) {
  if (!action) return {};
  if (action.type === "cancel") {
    return {
      title: "Cancel pipeline run?",
      description: "The run stops from its current active state. Completed stages and reusable artifacts remain in place.",
      details: [
        "This is not a delete operation.",
        "The run can usually be resumed from checkpoints when dependency checks pass.",
      ],
      confirmLabel: "Cancel run",
      tone: "warning",
    };
  }
  if (action.type === "retry") {
    return {
      title: "Create a new retry run?",
      description: "This creates a separate run with the same parameters instead of resuming the current run.",
      details: [
        "Current run checkpoints will not be reused.",
        "Use Resume when the goal is to continue from existing progress.",
      ],
      confirmLabel: "Retry as new run",
      tone: "warning",
    };
  }
  if (action.type === "skip_stage") {
    const stage = formatStageLabel(action.stage || "stage");
    return {
      title: `Skip ${stage}?`,
      description: "This marks only the selected stage as intentionally skipped for the current run.",
      details: [
        "Required-stage skips are rejected unless a reusable artifact already exists.",
        "Downstream stages may remain blocked if they need this output.",
      ],
      confirmLabel: "Skip stage",
      tone: "warning",
    };
  }
  const stage = formatStageLabel(action.stage || "stage");
  const runOnly = action.type === "only_stage";
  return {
    title: `${runOnly ? "Run only" : "Resume from"} ${stage}?`,
    description: runOnly
      ? "This starts a stage-scoped operation without restarting the whole pipeline."
      : "This resumes the run from the selected stage boundary.",
    details: [
      "Existing valid artifacts are reused where dependency checks allow it.",
      "Other stages remain unchanged unless this operation writes newer downstream artifacts.",
    ],
    confirmLabel: runOnly ? "Run only this stage" : "Resume from stage",
    tone: "warning",
  };
}

const stageControlStyle = {
  width: "100%",
  minWidth: 0,
  padding: "7px 10px",
  background: "var(--color-bg-base)",
  border: "1px solid var(--color-border-default)",
  borderRadius: 6,
  color: "var(--color-text-primary)",
  fontSize: 12,
};

const miniHintStyle = {
  fontSize: 11,
  color: "var(--color-text-muted)",
  lineHeight: 1.25,
  overflowWrap: "anywhere",
};
