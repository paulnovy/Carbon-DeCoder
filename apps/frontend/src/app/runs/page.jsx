"use client";

import { API_BASE } from "@/lib/api";
import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import RunControls, { StageActionButtons } from "@/components/RunControls";
import { useAppSelection } from "@/components/AppSelectionProvider";
import { Button, EmptyState, PageHeader, Panel } from "@/components/ui";


export default function RunsPage() {
  const { selectedProjectId, selectedRunId, selectRun, selectionReady } = useAppSelection();
  const [projects, setProjects] = useState([]);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedRun, setSelectedRun] = useState(null);
  const [runDetail, setRunDetail] = useState(null);
  const [steps, setSteps] = useState([]);
  const [events, setEvents] = useState([]);
  const [showNewRun, setShowNewRun] = useState(false);
  const [newRunProject, setNewRunProject] = useState("");
  const [newRunMode, setNewRunMode] = useState("full");
  const [newRunSample, setNewRunSample] = useState("");
  const [newRunRef, setNewRunRef] = useState("GRCh38_standard");
  const [creating, setCreating] = useState(false);
  const selectedRunRef = useRef(null);
  const allRunsInFlight = useRef(false);
  const detailInFlight = useRef(false);

  useEffect(() => {
    selectedRunRef.current = selectedRun;
  }, [selectedRun]);

  useEffect(() => {
    if (selectionReady) loadAllRuns();
  }, [selectionReady, selectedProjectId, selectedRunId]);

  useEffect(() => {
    if (selectedRun) loadRunDetail(selectedRun);
  }, [selectedRun]);

  // Poll run detail while pipeline is active
  useEffect(() => {
    if (!selectedRun) return;
    const isActive = runDetail && ["running", "paused", "queued", "started"].includes(runDetail.status);
    if (!isActive) return;
    const interval = setInterval(() => {
      if (document.visibilityState !== "hidden") loadRunDetail(selectedRun);
    }, 10000);
    return () => clearInterval(interval);
  }, [selectedRun, runDetail?.status]);

  const loadAllRuns = async () => {
    if (!selectionReady) return;
    if (allRunsInFlight.current) return;
    allRunsInFlight.current = true;
    try {
      const projsRes = await fetch(`${API_BASE}/projects`);
      const projsData = await projsRes.json();
      const projs = projsData.items || [];
      setProjects(projs);

      const allRuns = [];
      for (const p of projs) {
        try {
          const rRes = await fetch(`${API_BASE}/projects/${p.id}/runs`);
          const rData = await rRes.json();
          const rItems = rData.items || rData || [];
          for (const r of rItems) {
            allRuns.push({ ...r, project_name: p.name });
          }
        } catch {}
      }
      const STATUS_ORDER = { running: 0, paused: 1, cancelling: 2, queued: 3, started: 4, failed: 5, cancelled: 6, interrupted: 7, done: 8 };
      allRuns.sort((a, b) => {
        const sa = STATUS_ORDER[a.status] ?? 9;
        const sb = STATUS_ORDER[b.status] ?? 9;
        if (sa !== sb) return sa - sb;
        return (b.created_at || "").localeCompare(a.created_at || "");
      });
      const activeRun = allRuns.find(r => ["running", "paused", "cancelling"].includes(r.status));
      const visibleRuns = activeRun
        ? allRuns
        : selectedProjectId
          ? allRuns.filter((run) => run.project_id === selectedProjectId)
          : allRuns;
      setRuns(visibleRuns);
      const preferredRun = activeRun
        || visibleRuns.find((run) => run.id === selectedRunId)
        || visibleRuns.find((run) => run.id === selectedRunRef.current)
        || visibleRuns[0]
        || null;
      setSelectedRun(preferredRun?.id || null);
      if (!preferredRun) {
        setRunDetail(null);
        setSteps([]);
        setEvents([]);
      }
      if (!newRunProject) setNewRunProject(selectedProjectId || projs[0]?.id || "");
    } catch (e) {
      console.error("Failed to load runs:", e);
    } finally {
      allRunsInFlight.current = false;
      setLoading(false);
    }
  };

  const loadRunDetail = async (runId) => {
    if (!runId) return;
    if (detailInFlight.current) return;
    detailInFlight.current = true;
    try {
      const [detail, stepsRes, eventsRes] = await Promise.all([
        fetch(`${API_BASE}/runs/${runId}`).then((r) => r.ok ? r.json() : null),
        fetch(`${API_BASE}/runs/${runId}/steps`).then((r) => r.ok ? r.json() : { items: [] }),
        fetch(`${API_BASE}/runs/${runId}/events`).then((r) => r.ok ? r.json() : { items: [] }),
      ]);
      setRunDetail(detail);
      setSteps(stepsRes?.items || stepsRes || []);
      setEvents(eventsRes?.items || eventsRes || []);
    } catch (e) {
      console.error("Failed to load run detail:", e);
      setRunDetail(null);
      setSteps([]);
      setEvents([]);
    } finally {
      detailInFlight.current = false;
    }
  };

  const createRun = async () => {
    if (!newRunProject) return;
    setCreating(true);
    try {
      const res = await fetch(`${API_BASE}/projects/${newRunProject}/run/${newRunMode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sample_id: newRunSample || undefined,
          reference_id: newRunRef,
        }),
      });
      if (res.ok) {
      const run = await res.json();
      setShowNewRun(false);
      setSelectedRun(run.id);
      selectRun(run);
        await loadAllRuns();
        await loadRunDetail(run.id);
        // Auto-start pipeline
        try {
          const startRes = await fetch(`${API_BASE}/runs/${run.id}/pipeline/start`, { method: "POST" });
          if (startRes.ok) {
            await refreshCurrentRun();
          }
        } catch (_) { /* user can start manually */ }
      }
    } catch (e) { console.error(e); }
    finally { setCreating(false); }
  };

  const refreshCurrentRun = async () => {
    await loadAllRuns();
    if (selectedRun) await loadRunDetail(selectedRun);
  };

  const deleteRun = async (runId) => {
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete run");
      setRunDetail(null);
      setSteps([]);
      setEvents([]);
      setSelectedRun(null);
      await loadAllRuns();
    } catch (e) {
      console.error(e);
    }
  };

  const handleRunControlRefresh = () => {
    refreshCurrentRun();
  };

  if (loading) {
    return (
      <div style={{ color: "var(--color-text-secondary)", padding: 40 }}>
        Loading runs…
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        eyebrow="Operations"
        title="Runs"
        description="Pipeline execution history, stage diagnostics, and scoped restart controls."
        actions={
          <>
            <Button variant="secondary" onClick={refreshCurrentRun}>Refresh</Button>
            <Button variant="primary" onClick={() => setShowNewRun(true)}>+ New Run</Button>
          </>
        }
      />

      {/* New Run dialog */}
      {showNewRun && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.7)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }} onClick={() => setShowNewRun(false)}>
          <div className="card" style={{ width: 440, padding: 28 }} onClick={(e) => e.stopPropagation()}>
            <h2 style={{ fontSize: 18, fontWeight: 700, margin: "0 0 20px" }}>Start Pipeline Run</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div>
                <label style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>Project</label>
                <select value={newRunProject} onChange={(e) => setNewRunProject(e.target.value)} className="form-control">
                  <option value="">Select project…</option>
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  {projects.length === 0 && <option value="">No projects available</option>}
                </select>
              </div>
              <div>
                <label style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>Mode</label>
                <select value={newRunMode} onChange={(e) => setNewRunMode(e.target.value)} className="form-control">
                  <option value="full">Full pipeline</option>
                  <option value="qc">QC only</option>
                  <option value="benchmark">Benchmark</option>
                </select>
              </div>
              <div>
                <label style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>Reference</label>
                <select value={newRunRef} onChange={(e) => setNewRunRef(e.target.value)} className="form-control">
                  <option value="GRCh38_standard">GRCh38</option>
                  <option value="GRCh37_legacy">GRCh37</option>
                  <option value="T2T-CHM13v2">T2T-CHM13</option>
                </select>
              </div>
              <div>
                <label style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>Sample ID (optional)</label>
                <input value={newRunSample} onChange={(e) => setNewRunSample(e.target.value)} placeholder="e.g. sample_001"
                  className="form-control" />
              </div>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 24 }}>
              <Button variant="secondary" onClick={() => setShowNewRun(false)}>Cancel</Button>
              <Button variant="primary" onClick={createRun} disabled={creating || !newRunProject}>
                {creating ? "Starting…" : "Create & Start Pipeline"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {runs.length === 0 ? (
        <EmptyState
          title="No runs yet"
          description={
            <>
              Create a project and run from the{" "}
            <Link href="/projects" style={{ color: "var(--color-accent)" }}>
              Projects
            </Link>{" "}
            page.
            </>
          }
        />
      ) : (
        <div className="split-layout">
          {/* Run list */}
          <div className="card list-panel">
            <h3 className="list-panel-title">
              {runs.length} run{runs.length !== 1 ? "s" : ""}
            </h3>
            {runs.map((r) => (
              <button
                key={r.id}
                onClick={() => {
                  setSelectedRun(r.id);
                  selectRun(r);
                }}
                className={`list-button ${selectedRun === r.id ? "active" : ""}`}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <span className={`badge ${statusBadge(r.status)}`}>{r.status}</span>
                  <span style={{ fontWeight: 500 }}>{r.mode}</span>
                </div>
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                  {r.id} · {r.project_name}
                </div>
              </button>
            ))}
          </div>

          {/* Run detail */}
          <div>
            {selectedRun && runDetail ? (
              <RunDetail
                run={runDetail}
                steps={steps}
                events={events}
                project={projects.find((p) => p.id === runDetail.project_id)}
                onControlRefresh={handleRunControlRefresh}
              />
            ) : (
              <EmptyState title="Select a run" description="Pick a run from the list to inspect stages, logs, and scoped controls." />
            )}
          </div>
        </div>
      )}

    </div>
  );
}

function RunDetail({ run, steps, events, project, onControlRefresh }) {
  if (!run) return <EmptyState title="Run data unavailable" />;

  const currentPlan = currentStagePlan(run);
  const displaySteps = visibleStageSteps(steps, currentPlan);
  const doneSteps = displaySteps.filter((s) => s.status === "done").length;
  const totalSteps = displaySteps.length;
  const progressPct = totalSteps > 0 ? Math.round((doneSteps / totalSteps) * 100) : 0;
  const diagnostics = stageDiagnostics(events, currentPlan);
  const hasDiagnosticIssue = diagnostics.some((item) => ["failed", "paused"].includes(item.status));
  const shouldShowDiagnostics = diagnostics.length > 0 && (hasDiagnosticIssue || ["failed", "paused", "interrupted", "cancelled"].includes(run.status));

  return (
    <div>
      {/* Run header */}
      <Panel className="run-detail-header">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <span className={`badge ${statusBadge(run.status)}`} style={{ fontSize: 13, padding: "4px 12px" }}>
                {run.status}
              </span>
              <span style={{ fontSize: 18, fontWeight: 600 }}>{run.mode} run</span>
            </div>
            <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
              {project?.name || "Unknown project"} · ref: {run.reference_id}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
              {run.id}
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 4 }}>
              {new Date(run.created_at).toLocaleString()}
            </div>
          </div>
        </div>

        {/* Progress bar */}
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 6 }}>
            <span>Pipeline progress</span>
            <span>{doneSteps}/{totalSteps} stages · {progressPct}%</span>
          </div>
          <div style={{ height: 6, background: "var(--color-bg-base)", borderRadius: 3, overflow: "hidden" }}>
            <div
              style={{
                height: "100%",
                width: `${progressPct}%`,
                background: progressPct === 100 ? "var(--color-ok)" : ["cancelled", "cancelling", "paused"].includes(run.status) ? "var(--color-warn)" : "var(--color-accent)",
                borderRadius: 3,
                transition: "width 0.3s ease",
              }}
            />
          </div>
        </div>

        {/* Run controls */}
        <RunControls run={run} steps={steps} onRefresh={onControlRefresh} />
      </Panel>

      {/* Steps */}
      <Panel
        title={currentPlan.length > 0 ? "Current Stage Plan" : "Pipeline Steps"}
        description={currentPlan.length > 0 ? "Showing the active scoped flow for this run. Earlier historical attempts are kept in Events and diagnostics." : "Stage actions are scoped to the selected step; dependency checks prevent unsafe restarts."}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {displaySteps.map((s) => (
            <div
              key={s.id}
              className="detail-grid-row"
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                <span style={{ width: 20, textAlign: "center", flex: "0 0 20px" }}>
                  {s.status === "done" ? "✓" : s.status === "running" ? "◉" : s.status === "failed" ? "✗" : s.status === "blocked" ? "!" : s.status === "skipped" ? "↷" : "○"}
                </span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 500 }}>{formatStageName(s.step_name)}</div>
                  {s.last_log && (
                    <div style={{ fontSize: 11, color: "var(--color-text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {s.last_log}
                    </div>
                  )}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8 }}>
                <span className={`badge ${stepBadge(s.status)}`}>{s.status}</span>
                {s.progress_pct > 0 && s.status !== "done" && (
                  <span style={{ fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                    {s.progress_pct}%
                  </span>
                )}
              </div>
              <StageActionButtons
                run={run}
                stage={s.step_name}
                steps={displaySteps}
                onRefresh={onControlRefresh}
                compact
              />
            </div>
          ))}
        </div>
      </Panel>

      {shouldShowDiagnostics && (
        <StageDiagnostics diagnostics={diagnostics} />
      )}

      {/* Events */}
      <div className="card" style={{ padding: 20 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: "0 0 12px" }}>
          Events ({events.length})
        </h3>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 300, overflowY: "auto" }}>
          {events.map((e, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "6px 12px",
                borderRadius: 4,
                fontSize: 12,
                fontFamily: "var(--font-mono)",
              }}
            >
              <span style={{ color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>
                {new Date(e.created_at).toLocaleTimeString()}
              </span>
              <span style={{ color: eventColor(e.event_type) }}>{e.event_type}</span>
              {eventDetail(e.payload) && (
                <span style={{ color: "var(--color-text-secondary)", whiteSpace: "normal", overflowWrap: "anywhere" }}>
                  {String(eventDetail(e.payload)).slice(0, 600)}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function eventDetail(payload) {
  if (!payload) return "";
  if (payload.disk_pressure?.reason) return payload.disk_pressure.reason;
  return payload.reason || payload.error || payload.stderr_tail || payload.stderr || payload.stdout_tail || payload.stdout || payload.command || "";
}

function currentStagePlan(run) {
  const params = run?.parameters || {};
  const plan = params.stage_plan || {};
  const stages = Array.isArray(plan.final_stages) && plan.final_stages.length
    ? plan.final_stages
    : Array.isArray(params.stages)
      ? params.stages
      : [];
  const seen = new Set();
  return stages
    .map((stage) => String(stage || "").trim())
    .filter((stage) => {
      if (!stage || seen.has(stage)) return false;
      seen.add(stage);
      return true;
    });
}

function visibleStageSteps(steps, currentPlan) {
  if (!Array.isArray(steps) || steps.length === 0) return [];
  const latest = new Map();
  for (const step of steps) {
    const existing = latest.get(step.step_name);
    const existingTs = existing ? new Date(existing.updated_at || existing.created_at || 0).getTime() : -1;
    const nextTs = new Date(step.updated_at || step.created_at || 0).getTime();
    if (!existing || nextTs >= existingTs) latest.set(step.step_name, step);
  }
  if (currentPlan.length > 0) {
    return currentPlan
      .map((stage) => latest.get(stage) || { id: `planned-${stage}`, step_name: stage, status: "queued", progress_pct: 0, last_log: "planned" })
      .filter(Boolean);
  }
  return Array.from(latest.values()).filter((step) => !["process_recovery", "pipeline_dispatch"].includes(step.step_name));
}

function stageDiagnostics(events, currentPlan = []) {
  const activeStages = new Set(currentPlan);
  return (events || [])
    .filter((event) => event.event_type === "stage_execution_recorded" && event.payload)
    .filter((event) => activeStages.size === 0 || activeStages.has(event.payload.stage))
    .map((event) => ({ ...event.payload, created_at: event.created_at }))
    .reverse()
    .slice(0, 6);
}

function StageDiagnostics({ diagnostics }) {
  return (
    <div className="card" style={{ padding: 20, marginBottom: 16 }}>
      <h3 style={{ fontSize: 15, fontWeight: 600, margin: "0 0 12px" }}>
        Stage Diagnostics
      </h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {diagnostics.map((item, index) => {
          const stderr = item.stderr_tail || item.stderr || "";
          const stdout = item.stdout_tail || item.stdout || "";
          const detail = item.reason || stderr || stdout || item.command || "";
          const tone = item.status === "failed" ? "var(--color-err)" : item.status === "paused" ? "var(--color-warn)" : "var(--color-text-secondary)";
          return (
            <div
              key={`${item.stage || "stage"}-${item.created_at || index}`}
              style={{
                padding: 12,
                borderRadius: 8,
                background: "var(--color-bg-elevated)",
                border: `1px solid ${item.status === "failed" ? "color-mix(in srgb, var(--color-err) 45%, transparent)" : "var(--color-border-muted)"}`,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className={`badge ${stepBadge(item.status)}`}>{item.status || "unknown"}</span>
                  <strong style={{ fontSize: 13 }}>{formatStageName(item.stage || "stage")}</strong>
                  {item.returncode !== undefined && (
                    <span style={{ fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                      exit {item.returncode}
                    </span>
                  )}
                </div>
                {item.created_at && (
                  <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                    {new Date(item.created_at).toLocaleString()}
                  </span>
                )}
              </div>
              {item.command && (
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)", overflowWrap: "anywhere", marginBottom: 8 }}>
                  {item.command}
                </div>
              )}
              {detail && (
                <pre
                  style={{
                    margin: 0,
                    padding: 10,
                    borderRadius: 6,
                    maxHeight: 180,
                    overflow: "auto",
                    whiteSpace: "pre-wrap",
                    overflowWrap: "anywhere",
                    background: "var(--color-bg-base)",
                    color: tone,
                    fontSize: 11,
                    lineHeight: 1.45,
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {String(detail).slice(-1800)}
                </pre>
              )}
              {item.artifact_paths?.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 8 }}>
                  {item.artifact_paths.slice(0, 8).map((path) => (
                    <span key={path} className="badge badge-info" title={path}>
                      {path.split("/").slice(-1)[0]}
                    </span>
                  ))}
                  {item.artifact_paths.length > 8 && (
                    <span className="badge badge-info">+{item.artifact_paths.length - 8}</span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function statusBadge(status) {
  switch (status) {
    case "done": return "badge-ok";
    case "running": return "badge-info";
    case "paused": return "badge-warn";
    case "queued": return "badge-warn";
    case "failed": return "badge-err";
    case "blocked": return "badge-warn";
    case "cancelled": return "badge-warn";
    case "cancelling": return "badge-warn";
    case "skipped": return "badge-warn";
    default: return "badge-info";
  }
}

function stepBadge(status) {
  switch (status) {
    case "done": return "badge-ok";
    case "running": return "badge-info";
    case "paused": return "badge-warn";
    case "queued": return "badge-warn";
    case "failed": return "badge-err";
    case "blocked": return "badge-warn";
    case "cancelled": return "badge-warn";
    case "cancelling": return "badge-warn";
    case "skipped": return "badge-warn";
    default: return "badge-info";
  }
}

function eventColor(type) {
  if (type.includes("imported")) return "var(--color-ok)";
  if (type.includes("optional") || type.includes("skipped") || type.includes("blocked") || type.includes("unavailable")) return "var(--color-warn)";
  if (type.includes("error") || type.includes("failed")) return "var(--color-err)";
  if (type.includes("cancel")) return "var(--color-warn)";
  if (type.includes("queued")) return "var(--color-warn)";
  return "var(--color-text-secondary)";
}

function formatStageName(name) {
  return name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
