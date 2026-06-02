"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import RunControls from "../components/RunControls";
import { API_BASE, fetchApiHealth, fetchJson } from "@/lib/api";
import { useAppSelection } from "@/components/AppSelectionProvider";
import { Button } from "@/components/ui";

/* ── Constants ── */
const CHROMS = ["1","2","3","4","5","6","7","8","9","10","11","12","13","14","15","16","17","18","19","20","21","22","X","Y"];
const PRIMARY_DISPLAY_CONTIGS = [...CHROMS, "M"];

const GRCH38_PRIMARY_LENGTHS = {
  "1": 248956422,
  "2": 242193529,
  "3": 198295559,
  "4": 190214555,
  "5": 181538259,
  "6": 170805979,
  "7": 159345973,
  "8": 145138636,
  "9": 138394717,
  "10": 133797422,
  "11": 135086622,
  "12": 133275309,
  "13": 114364328,
  "14": 107043718,
  "15": 101991189,
  "16": 90338345,
  "17": 83257441,
  "18": 80373285,
  "19": 58617616,
  "20": 64444167,
  "21": 46709983,
  "22": 50818468,
  "X": 156040895,
  "Y": 57227415,
  "M": 16569,
};

const GRCH38_AUTOSOME_TOTAL = CHROMS
  .filter((chr) => /^\d+$/.test(chr))
  .reduce((sum, chr) => sum + GRCH38_PRIMARY_LENGTHS[chr], 0);

const STAGES = [
  ["input_validation", "Input validation", "FASTQ pair · reference · read groups"],
  ["alignment", "Alignment", "selected aligner -> SAM/BAM"],
  ["coverage", "Coverage/QC", "mosdepth · callable regions"],
  ["variants", "SNV/Indel calling", "bcftools / DeepVariant-ready"],
  ["sv", "SV/CNV analysis", "Manta/Delly · CNVkit"],
  ["interpretation", "Secondary analyses", "mtDNA · taxonomy · PRS · reports"],
];

const STAGE_ALIASES = {
  input_validation: ["input_validation", "fastq", "qc", "pipeline_dispatch"],
  alignment: ["alignment", "sort", "sorting", "index", "markdup", "duplicates", "duplicate_marking"],
  coverage: ["coverage", "qc_metrics", "callability"],
  variants: ["variants", "variant_calling", "snv", "indel", "bcftools", "deepvariant"],
  sv: ["sv", "cnv", "sv_calling", "cnv_calling"],
  interpretation: ["taxonomy", "mtdna", "prs", "reports", "report", "benchmark", "vendor_validation"],
};

/* ── Helpers ── */
function stepForStage(runSteps, id) {
  const aliases = STAGE_ALIASES[id] || [id];
  const matches = runSteps.filter((s) => aliases.some((a) => String(s.step_name || "").toLowerCase() === a));
  if (!matches.length) return null;
  return matches.find((s) => s.status === "running") || matches.find((s) => s.status === "failed") || matches.find((s) => s.status === "blocked") || matches.find((s) => s.status === "queued") || matches.find((s) => s.status === "skipped") || matches[matches.length - 1];
}

function stageClass(runSteps, id, runStatus) {
  const aliases = STAGE_ALIASES[id] || [id];
  const matches = runSteps.filter((s) => aliases.some((a) => String(s.step_name || "").toLowerCase() === a));
  if (matches.some((s) => s.status === "failed")) return "failed";
  if (matches.some((s) => s.status === "running")) return "active";
  if (matches.some((s) => s.status === "blocked")) return "blocked";
  if (matches.some((s) => s.status === "skipped")) return "skipped";
  if (matches.length && matches.every((s) => s.status === "done")) return "done";
  if (String(runStatus).toLowerCase() === "done") return "done";
  return "";
}

function eventDetail(payload) {
  if (!payload) return "";
  if (payload.disk_pressure?.reason) return payload.disk_pressure.reason;
  return payload.reason || payload.error || payload.stderr_tail || payload.stderr || payload.stdout_tail || payload.stdout || payload.command || "";
}

function formatDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

function formatEta(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  return "~" + formatDuration(seconds);
}

function formatNumber(n) {
  if (n == null) return "—";
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return n.toLocaleString();
}

function formatBytes(bytes) {
  if (bytes == null || Number.isNaN(Number(bytes))) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = Number(bytes);
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  return `${idx === 0 ? value : value.toFixed(1)} ${units[idx]}`;
}

function formatPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  return `${Number.isInteger(n) ? n : n.toFixed(2).replace(/\.?0+$/, "")}%`;
}

function metricStatusLabel(lp) {
  if (!lp) return "no data";
  if (lp.metric_quality === "final" || lp.metric_source === "final_flagstat_idxstats") return "final flagstat/idxstats";
  if (lp.metric_quality === "stale_live") return "stale live metrics";
  if (lp.status === "checkpoint_resume") return "checkpoint resume";
  if (lp.status === "aligning" || lp.status === "starting") return "live SAM stream";
  return lp.metric_source || lp.status || "metrics";
}

function hasAlignmentMetrics(lp) {
  if (!lp) return false;
  return ["final", "stale_live"].includes(lp.metric_quality) || ["aligning", "starting", "complete"].includes(lp.status) || Number(lp.primary_reads_processed || 0) > 0;
}

function hasCheckpointState(lp) {
  return Boolean(lp?.checkpoint_state?.best_checkpoint || lp?.checkpoint_state?.substage_plan?.length);
}

function normalizeChrKey(chr) {
  const value = String(chr || "").replace(/^chr/i, "");
  if (value === "MT" || value === "Mt" || value === "m" || value === "M") return "M";
  return value;
}

function expectedRefPct(chr) {
  const key = normalizeChrKey(chr);
  if (key === "X" || key === "Y" || key === "M") return null;
  const len = GRCH38_PRIMARY_LENGTHS[key];
  return len ? (len / GRCH38_AUTOSOME_TOTAL) * 100 : null;
}

function displayContigName(chr) {
  const key = normalizeChrKey(chr);
  return key === "M" ? "M" : key;
}

function expectedDeltaLabel(chr, currentPct, expectedPct) {
  if (expectedPct != null) {
    const delta = currentPct - expectedPct;
    return `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}pp`;
  }
  return "off primary";
}

/* ── Main Dashboard ── */
export default function Dashboard() {
  const { selectedProjectId, selectedRunId } = useAppSelection();
  const [selectedChr, setSelectedChr] = useState(null);
  const [health, setHealth] = useState(null);
  const [projects, setProjects] = useState([]);
  const [runs, setRuns] = useState([]);
  const [covSummary, setCovSummary] = useState(null);
  const [covTiles, setCovTiles] = useState([]);
  const [runEvents, setRunEvents] = useState([]);
  const [runSteps, setRunSteps] = useState([]);
  const [liveProgress, setLiveProgress] = useState(null);
  const [livePollState, setLivePollState] = useState({ status: "idle", lastOkAt: null, missed: 0 });
  const [refreshTick, setRefreshTick] = useState(0);
  const [activeTab, setActiveTab] = useState("alignment"); // "alignment" | "mapping"
  const [controlError, setControlError] = useState(null);
  const mainLoadInFlight = useRef(false);

  // Main data load
  useEffect(() => {
    let alive = true;
    const load = async () => {
      if (mainLoadInFlight.current || document.visibilityState === "hidden") return;
      mainLoadInFlight.current = true;
      try {
        const [h, projs] = await Promise.all([
          fetchApiHealth(API_BASE),
          fetchJson(`${API_BASE}/projects`, { items: [] }),
        ]);
        if (!alive) return;
        setHealth(h);
        const pList = projs.items || [];
        setProjects(pList);

        const allRuns = [];
        const globalRuns = await fetchJson(`${API_BASE}/runs?limit=50`, { items: [] });
        for (const run of globalRuns.items || []) {
          const project = pList.find((p) => p.id === run.project_id);
          allRuns.push({ ...run, project_name: project?.name || run.project_id || "no project" });
        }
        for (const p of pList.slice(0, 6)) {
          const r = await fetchJson(`${API_BASE}/projects/${p.id}/runs`, { items: [] });
          for (const run of r.items || r || []) {
            if (!allRuns.some((existing) => existing.id === run.id)) allRuns.push({ ...run, project_name: p.name });
          }
        }
        const STATUS_ORDER = { running: 0, paused: 1, cancelling: 2, queued: 3, started: 4, failed: 5, cancelled: 6, interrupted: 7, done: 8 };
        allRuns.sort((a, b) => {
          const sa = STATUS_ORDER[a.status] ?? 9;
          const sb = STATUS_ORDER[b.status] ?? 9;
          if (sa !== sb) return sa - sb;
          return (b.created_at || "").localeCompare(a.created_at || "");
        });
        const activeWork = allRuns.find(r => ["running", "paused", "cancelling"].includes(r.status));
        const selectedProjectRuns = selectedProjectId ? allRuns.filter((run) => run.project_id === selectedProjectId) : allRuns;
        const selectedRun = selectedRunId ? selectedProjectRuns.find((run) => run.id === selectedRunId) : null;
        const ar = activeWork || selectedRun || selectedProjectRuns[0] || null;
        const visibleRuns = activeWork ? allRuns : selectedProjectRuns;
        if (!alive) return;
        setRuns(ar ? [ar, ...visibleRuns.filter((run) => run.id !== ar.id)] : []);

        if (ar?.sample_id) {
          const sid = ar.sample_id;
          const rid = ar.id;
          const [covS, tiles, evts, steps] = await Promise.all([
            fetchJson(`${API_BASE}/samples/${sid}/coverage-summary?run_id=${encodeURIComponent(rid)}`, null),
            fetchJson(`${API_BASE}/samples/${sid}/coverage-tiles?run_id=${encodeURIComponent(rid)}`, { tiles: [] }),
            fetchJson(`${API_BASE}/runs/${rid}/events`, { items: [] }),
            fetchJson(`${API_BASE}/runs/${rid}/steps`, { items: [] }),
          ]);
          if (!alive) return;
          setCovSummary(covS);
          setCovTiles(tiles.tiles || []);
          setRunEvents((evts.items || []).slice(-15).reverse());
          setRunSteps(steps.items || []);
        } else {
          setCovSummary(null);
          setCovTiles([]);
          setRunEvents([]);
          setRunSteps([]);
        }
      } finally {
        mainLoadInFlight.current = false;
      }
    };
    load();
    const interval = setInterval(load, 60000);
    return () => { alive = false; clearInterval(interval); };
  }, [refreshTick, selectedProjectId, selectedRunId]);

  // Alignment progress polling: live during mapping, final/recovered after completion.
  useEffect(() => {
    const activeRun = runs[0];
    if (!activeRun) {
      setLiveProgress(null);
      setLivePollState({ status: "idle", lastOkAt: null, missed: 0 });
      return;
    }
    let alive = true;
    let inFlight = false;
    const shouldPoll = ["running", "paused", "cancelling"].includes(activeRun.status);
    const poll = async () => {
      if (document.visibilityState === "hidden") return;
      if (inFlight) return;
      inFlight = true;
      const data = await fetchJson(`${API_BASE}/runs/${activeRun.id}/live-progress`, null, { timeoutMs: 5000 });
      inFlight = false;
      if (!alive) return;
      if (data) {
        setLiveProgress(data);
        setLivePollState({ status: "ok", lastOkAt: Date.now(), missed: 0 });
      } else {
        setLivePollState((prev) => ({ ...prev, status: "stale", missed: (prev.missed || 0) + 1 }));
      }
    };
    poll();
    if (!shouldPoll) return () => { alive = false; };
    const activeInterval = 2500;
    const interval = setInterval(poll, activeInterval);
    return () => { alive = false; clearInterval(interval); };
  }, [runs]);

  const activeRun = runs[0];
  const runStatus = activeRun?.status || "idle";
  const activeRunId = activeRun?.id || "—";

  useEffect(() => {
    setControlError(null);
  }, [activeRun?.id, activeRun?.status]);

  const doneSteps = runSteps.filter(s => s.status === "done").length;
  const totalSteps = runSteps.length || 1;
  const pipelineProgress = runStatus === "done" ? 100 : Math.round((doneSteps / totalSteps) * 100);
  const latestEvent = runEvents[0];
  const activeStep = runSteps.find(s => s.status === "running") || runSteps.find(s => s.status === "queued");
  const activeStage = STAGES.find(([id]) => stageClass(runSteps, id, runStatus) === "active")?.[1] || activeStep?.step_name?.replace(/_/g, " ") || runStatus;
  const activeResourcePlan = activeRun?.parameters?.resource_plan || {};
  const backendPolicy = activeResourcePlan?.backend_policy?.alignment || null;
  const lp = liveProgress;
  const effectiveBackend = lp?.alignment_backend || backendPolicy || "auto";
  const resourcePlanLabel = activeResourcePlan?.threads ? `${activeResourcePlan.effective_profile || "auto"} · ${activeResourcePlan.threads}t` : "pending";

  // Coverage data
  const chrCoverage = {};
  for (const t of covTiles) {
    const c = normalizeChrKey(t.contig);
    if (!c) continue;
    if (!PRIMARY_DISPLAY_CONTIGS.includes(c)) continue;
    if (!chrCoverage[c]) chrCoverage[c] = { total: 0, count: 0 };
    chrCoverage[c].total += t.coverage || 0;
    chrCoverage[c].count += 1;
  }
  const coverageRows = Object.entries(chrCoverage || {}).map(([chr, data]) => ({
    chr,
    tiles: data.count || 0,
    avgCoverage: data.count ? data.total / data.count : 0,
  }));
  const selectedCovData = selectedChr ? chrCoverage[selectedChr] : null;
  const selectedCov = selectedCovData?.count ? selectedCovData.total / selectedCovData.count : null;

  // Live progress data
  const hasLiveData = hasAlignmentMetrics(lp);
  const hasCheckpoint = hasCheckpointState(lp);
  const hasAlignmentProgress = hasLiveData && lp.progress_pct != null;
  const alignmentProgressSub = lp?.total_reads_estimated
    ? "estimated from FASTQ sample"
    : lp?.total_reads_known
      ? "read-count progress"
      : "stage-count progress";

  return (
    <div className="dashboard">
      {/* Command bar */}
      <section className="dash-command card">
        <div className="dash-command-left">
          <span className={`dash-status-dot ${runStatus}`} />
          <div>
            <p className="dash-command-label">WGS Cockpit</p>
            <h1>{activeRun?.project_name || "No active run"}</h1>
          </div>
        </div>
        <div className="dash-command-metrics">
          <MetricPill label="Run" value={activeRun?.id || "standby"} title={activeRun?.id || "No active run"} className="run-id" />
          <MetricPill label="Stage" value={activeStage} />
          <MetricPill label="Backend" value={effectiveBackend} />
          <MetricPill label="Plan" value={resourcePlanLabel} />
          <MetricPill label="API" value={health?.ok ? "connected" : "offline"} tone={health?.ok ? "ok" : "err"} />
        </div>
        {activeRun && (
          <div className="dash-command-controls">
            <RunControls
              run={activeRun}
              compact
              showDelete={false}
              errorMode="parent"
              onError={setControlError}
              onRefresh={() => {
                setControlError(null);
                setRefreshTick((t) => t + 1);
              }}
            />
          </div>
        )}
      </section>

      {controlError && (
        <div className="dash-control-alert" role="alert">
          <div>
            <strong>Run action blocked</strong>
            <span>{controlError}</span>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={() => setControlError(null)} aria-label="Dismiss run action error">
            Dismiss
          </Button>
        </div>
      )}

      {/* Stats row */}
      <div className="dash-stats">
        <StatCard label="API" value={health?.ok ? "Healthy" : "Down"} color={health?.ok ? "ok" : "err"} />
        <StatCard label="Run" value={activeRunId} sub={runStatus} className="run-card" title={activeRun?.id || undefined} />
        <StatCard label="Stage" value={activeStep?.step_name?.replace(/_/g, " ") || activeStage} />
        <StatCard
          label="Reads"
          value={hasLiveData ? formatNumber(lp.primary_reads_processed) : covSummary?.mean_coverage != null ? `${covSummary.mean_coverage.toFixed(1)}x` : "—"}
          sub={hasLiveData ? "primary SAM records" : covSummary?.status === "imported" ? "mean depth" : "no data"}
        />
        <StatCard
          label="Mapped so far"
          value={hasLiveData ? formatPct(lp.mapped_pct) : "—"}
          sub={hasLiveData ? `${formatNumber(lp.primary_reads_mapped)} of ${formatNumber(lp.primary_reads_processed)}` : hasCheckpoint ? "checkpoint state recovered" : "no live data"}
        />
        <StatCard
          label={hasAlignmentProgress ? "Alignment est." : "Pipeline"}
          value={hasAlignmentProgress ? `${lp.progress_pct}%` : `${pipelineProgress}%`}
          sub={hasAlignmentProgress ? alignmentProgressSub : "stage-count progress"}
        />
      </div>

      {/* Tab switcher */}
      <div className="segmented-control" style={{ marginBottom: 16 }}>
        <button className={`segmented-button ${activeTab === "alignment" ? "active" : ""}`} onClick={() => setActiveTab("alignment")}>Alignment Live</button>
        <button className={`segmented-button ${activeTab === "mapping" ? "active" : ""}`} onClick={() => setActiveTab("mapping")}>Preliminary Mapping</button>
      </div>

      {/* Tab content */}
      {activeTab === "alignment" ? (
        <AlignmentLiveTab
          lp={lp}
          hasLiveData={hasLiveData}
          hasCheckpoint={hasCheckpoint}
          activeRun={activeRun}
          runs={runs}
          runSteps={runSteps}
          runStatus={runStatus}
          runEvents={runEvents}
          latestEvent={latestEvent}
          doneSteps={doneSteps}
          totalSteps={totalSteps}
          pipelineProgress={pipelineProgress}
          effectiveBackend={effectiveBackend}
          livePollState={livePollState}
        />
      ) : (
        <PreliminaryMappingTab
          lp={lp}
          hasLiveData={hasLiveData}
          runs={runs}
          coverageRows={coverageRows}
          selectedChr={selectedChr}
          selectedCov={selectedCov}
          onSelectChr={setSelectedChr}
          covSummary={covSummary}
          covTiles={covTiles}
          effectiveBackend={effectiveBackend}
          livePollState={livePollState}
        />
      )}
    </div>
  );
}

/* ── Alignment Live Tab ── */
function AlignmentLiveTab({ lp, hasLiveData, hasCheckpoint, activeRun, runs, runSteps, runStatus, runEvents, latestEvent, doneSteps, totalSteps, pipelineProgress, effectiveBackend, livePollState }) {
  const totalReadsAvailable = lp?.total_reads_available || lp?.total_reads != null;
  const totalReadsEstimated = Boolean(lp?.total_reads_estimated);
  const finalMetrics = lp?.metric_quality === "final" || lp?.metric_source === "final_flagstat_idxstats";
  const totalReadsLabel = finalMetrics ? "Final primary records" : totalReadsEstimated ? "Estimated primary records" : "Expected primary records";
  const progressLabel = lp?.progress_pct != null
    ? finalMetrics ? "alignment complete" : `${lp.progress_pct}% of ${totalReadsEstimated ? "estimated" : "expected"} reads`
    : "total read count unknown";
  const statusLabel = metricStatusLabel(lp);
  const checkpoint = lp?.checkpoint_state;

  return (
    <div className="dash-grid">
      {/* Real Progress Panel */}
      <div className="card dash-aln-progress">
        <div className="card-head">
          <h2>Alignment Progress</h2>
          <p>{hasLiveData || hasCheckpoint ? `${statusLabel} · ${effectiveBackend}${livePollState?.status === "stale" ? " · waiting for next API update" : ""}` : `waiting for SAM stream · ${effectiveBackend}`}</p>
        </div>
        {hasLiveData ? (
          <div className="dash-aln-body">
            {/* Main progress bar */}
            <div className="dash-aln-main-bar">
              <div className="dash-aln-bar-label">
                <span>Primary SAM records</span>
                <b>{formatNumber(lp.primary_reads_processed)} {lp.total_reads_known ? `/ ${formatNumber(lp.total_reads)}` : ""}</b>
              </div>
              <div className="dash-aln-bar-track">
                <div className="dash-aln-bar-fill" style={{ width: `${lp.progress_pct ?? 0}%` }} />
              </div>
              <div className="dash-aln-bar-meta">
                <span>{progressLabel}</span>
                <span className={`dash-aln-confidence ${totalReadsAvailable ? lp.eta_confidence : "unknown"}`}>
                  {totalReadsAvailable ? (totalReadsEstimated ? "ETA estimated" : `ETA confidence: ${lp.eta_confidence}`) : "ETA disabled"}
                </span>
              </div>
            </div>

            {/* Metrics grid */}
            <div className="dash-aln-metrics">
              <AlnMetric label={finalMetrics ? "Mapped final" : "Mapped so far"} value={formatPct(lp.mapped_pct)} sub={`${formatNumber(lp.primary_reads_mapped)} of ${formatNumber(lp.primary_reads_processed)} primary`} />
              <AlnMetric label="Unmapped" value={formatPct(lp.unmapped_pct)} sub={`${formatNumber(lp.primary_reads_unmapped)} reads`} />
              <AlnMetric
                label={totalReadsAvailable ? totalReadsLabel : "Total reads"}
                value={totalReadsAvailable ? formatNumber(lp.total_reads) : "—"}
                sub={finalMetrics ? "samtools flagstat" : totalReadsEstimated ? "FASTQ sample estimate" : totalReadsAvailable ? "FASTQ count" : "not measured"}
              />
              <AlnMetric
                label="Avg speed"
                value={`${formatNumber(lp.reads_per_sec_avg ?? lp.reads_per_sec)}/s`}
                sub={`10s: ${formatNumber(lp.reads_per_sec_10s ?? lp.reads_per_sec)}/s`}
              />
              <AlnMetric
                label="ETA"
                value={formatEta(lp.eta_sec)}
                sub={totalReadsAvailable ? (totalReadsEstimated ? "avg speed · estimated total" : "avg speed") : "needs total reads"}
              />
              <AlnMetric label="MAPQ ≥ 30" value={formatPct(lp.mapq_ge30_pct)} sub={lp.mapq_60_pct != null ? `MAPQ 60: ${formatPct(lp.mapq_60_pct)}` : finalMetrics ? "not in flagstat" : "aligner-reported"} />
              <AlnMetric label="Proper pairs" value={formatPct(lp.proper_pair_pct)} sub={lp.duplicates_pct != null ? `duplicates: ${formatPct(lp.duplicates_pct)}` : undefined} />
              <AlnMetric label="Backend" value={lp.alignment_backend || effectiveBackend} sub={lp.metric_source || "selected policy"} />
              <AlnMetric label="Secondary" value={formatNumber(lp.secondary_alignments)} />
              <AlnMetric label="Supplementary" value={formatNumber(lp.supplementary_alignments)} />
              <AlnMetric label="Elapsed" value={formatDuration(lp.elapsed_sec)} />
            </div>
            {checkpoint && <AlignmentCheckpointState checkpoint={checkpoint} finalMetrics={finalMetrics} />}
          </div>
        ) : hasCheckpoint ? (
          <div className="dash-aln-body">
            <AlignmentCheckpointState checkpoint={checkpoint} finalMetrics={false} />
          </div>
        ) : (
          <div className="dash-empty">
            {["running", "paused"].includes(runStatus) ? "Alignment running — live metrics will appear when SAM stream starts." : "No alignment in progress. Start a run to see live metrics."}
          </div>
        )}
      </div>

      {/* Pipeline */}
      <div className="card dash-pipeline">
        <div className="card-head">
          <h2>Pipeline</h2>
          <p>{doneSteps}/{totalSteps} steps</p>
        </div>
        <div className="dash-progress">
          <div className="dash-progress-bar">
            <div className={runStatus} style={{ width: `${pipelineProgress}%` }} />
          </div>
        </div>
        <div className="dash-stages">
          {STAGES.map(([id, label, desc]) => {
            const cls = stageClass(runSteps, id, runStatus);
            const step = stepForStage(runSteps, id);
            return (
              <div key={id} className={`dash-stage ${cls}`}>
                <em>{cls === "done" ? "✓" : cls === "active" ? "▸" : cls === "failed" ? "✗" : cls === "blocked" ? "!" : cls === "skipped" ? "↷" : "·"}</em>
                <div>
                  <strong>{label}</strong>
                  <small>{["running", "skipped", "blocked"].includes(step?.status) ? step.step_name?.replace(/_/g, " ") : desc}</small>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Chromosome Distribution */}
      <div className="card dash-aln-chroms">
        <div className="card-head">
          <h2>Mapped Read Distribution</h2>
          <p>{hasLiveData && lp.chromosomes ? `primary order + top 10 other contigs · ${lp.mapped_contigs_total ?? lp.chromosomes.length} mapped total` : "no data"}</p>
        </div>
        {hasLiveData && lp.chromosomes?.length > 0 ? (
          <ChrDistribution chromosomes={lp.chromosomes} total={lp.primary_reads_mapped} />
        ) : (
          <div className="dash-empty">Chromosome distribution appears after alignment starts.</div>
        )}
      </div>

      {/* Log */}
      <div className="card dash-log">
        <div className="card-head">
          <h2>Log</h2>
          <p>{runEvents.length > 0 ? activeRun?.id?.slice(0, 10) : "no activity"}</p>
        </div>
        {runEvents.length > 0 ? (
          <div className="dash-log-lines">
            {runEvents.map((ev, i) => {
              const t = ev.created_at ? new Date(ev.created_at).toLocaleTimeString("en-GB") : "";
              const eventType = ev.event_type || "";
              const lvl = eventType.includes("fail") || eventType.includes("error") ? "ERR" : "INFO";
              const detail = eventDetail(ev.payload);
              const msg = eventType.replace(/_/g, " ") + (detail ? ": " + String(detail).slice(0, 420) : "");
              return (
                <p key={i}><time>{t}</time><b className={lvl.toLowerCase()}>{lvl}</b><span>{msg}</span></p>
              );
            })}
          </div>
        ) : (
          <div className="dash-empty">No events yet.</div>
        )}
      </div>

      {/* Runs */}
      <div className="card dash-runs">
        <div className="card-head">
          <h2>Runs</h2>
          <Link href="/runs">View all →</Link>
        </div>
        <RunsList runs={runs} />
      </div>
    </div>
  );
}

function AlignmentCheckpointState({ checkpoint, finalMetrics }) {
  const best = checkpoint?.best_checkpoint;
  const plan = checkpoint?.substage_plan || [];
  return (
    <div className="dash-aln-checkpoint">
      <div className="dash-aln-checkpoint-head">
        <span>{finalMetrics ? "Final artifacts" : "Checkpoint resume state"}</span>
        <b>{checkpoint?.current_label || "Waiting for checkpoint"}</b>
      </div>
      {best && (
        <div className="dash-aln-checkpoint-best">
          <span>{best.kind?.replace(/_/g, " ") || "checkpoint"}</span>
          <b>{formatBytes(best.size_bytes)}</b>
          <small>{best.path}</small>
        </div>
      )}
      {plan.length > 0 && (
        <div className="dash-aln-substages">
          {plan.map((stage) => (
            <span key={stage.id} className={stage.status}>
              <i>{stage.status === "done" ? "✓" : stage.status === "active" ? "▸" : "·"}</i>
              {stage.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Preliminary Mapping Tab ── */
function PreliminaryMappingTab({ lp, hasLiveData, runs, coverageRows, selectedChr, selectedCov, onSelectChr, covSummary, covTiles, effectiveBackend, livePollState }) {
  const liveChromosomes = hasLiveData && lp.chromosomes ? lp.chromosomes : [];
  const liveContigCount = lp?.mapped_contigs_total ?? liveChromosomes.length;
  const selectedLiveChr = selectedChr ? liveChromosomes.find(c => normalizeChrKey(c.chr) === selectedChr) : null;
  const liveByKey = new Map(liveChromosomes.map((item) => [normalizeChrKey(item.chr), item]));
  const primaryShare = PRIMARY_DISPLAY_CONTIGS.reduce((sum, chr) => sum + (liveByKey.get(chr)?.pct || 0), 0);
  const offPrimaryShare = hasLiveData ? Math.max(0, 100 - primaryShare) : null;
  const mtShare = liveByKey.get("M")?.pct ?? null;
  const sexShare = (liveByKey.get("X")?.pct || 0) + (liveByKey.get("Y")?.pct || 0);
  const cigarTotal = Object.values(lp?.cigar_classes || {}).reduce((sum, value) => sum + (value || 0), 0);
  const cigarPct = (key) => cigarTotal ? (((lp?.cigar_classes || {})[key] || 0) / cigarTotal * 100).toFixed(1) + "%" : "pending";
  const offPrimaryTone = offPrimaryShare == null ? undefined : offPrimaryShare > 2 ? "warn" : "ok";
  const unmappedTone = lp?.unmapped_pct == null ? undefined : lp.unmapped_pct > 5 ? "warn" : "ok";
  const mapqTone = lp?.mapq_ge30_pct == null ? undefined : lp.mapq_ge30_pct < 80 ? "warn" : "ok";
  const chromosomeMetrics = PRIMARY_DISPLAY_CONTIGS.map((chr) => {
    const row = coverageRows.find((item) => item.chr === chr);
    const liveChr = liveChromosomes.find(c => normalizeChrKey(c.chr) === chr);
    const expPct = expectedRefPct(chr);
    const value = row ? row.avgCoverage : liveChr ? liveChr.pct : null;
    const label = row ? `${row.avgCoverage.toFixed(1)}x` : liveChr ? (expPct != null ? `${liveChr.pct}% / ${expPct.toFixed(1)}% ref` : `${liveChr.pct}%`) : "—";
    return { chr, row, liveChr, value, label };
  });
  const chromosomeScale = Math.max(
    1,
    ...chromosomeMetrics
      .filter((item) => item.chr !== "M" && item.value != null)
      .map((item) => item.value)
  );

  return (
    <div className="dash-grid dash-grid-mapping">
      {/* Genome evidence */}
      <div className="card dash-evidence">
        <div className="card-head">
          <h2>{covTiles.length ? "Genome Coverage" : "Mapped Read Distribution"}</h2>
          <p>{covTiles.length ? covTiles.length + " tiles" : hasLiveData ? `${liveContigCount} mapped contigs · ${effectiveBackend}${livePollState?.status === "stale" ? " · API update pending" : ""}` : "no data"}</p>
        </div>
        <div className="dash-evidence-body">
          <div className="dash-evidence-summary">
            <ResourceLine label="Mean coverage" value={covSummary?.mean_coverage != null ? covSummary.mean_coverage.toFixed(1) + "x" : covTiles.length ? "not imported" : "pending coverage stage"} />
            <ResourceLine label="Callable" value={covSummary?.callable_fraction != null ? (covSummary.callable_fraction * 100).toFixed(1) + "%" : covTiles.length ? "not imported" : "pending coverage stage"} />
            <ResourceLine label={covTiles.length ? "Chromosomes" : "Mapped contigs"} value={coverageRows.length || liveContigCount || "none"} />
            <ResourceLine label="Mapped" value={hasLiveData ? formatPct(lp.mapped_pct) : "pending"} tone={lp?.mapped_pct > 90 ? "ok" : hasLiveData ? "warn" : undefined} />
            <ResourceLine label="MAPQ >=30" value={hasLiveData ? formatPct(lp.mapq_ge30_pct) : "pending"} tone={mapqTone} />
          </div>
          <div className="dash-mapping-diagnostics">
            <div className="dash-map-panel">
              <h3>Mapping quality</h3>
              <ResourceLine label="Unmapped" value={hasLiveData ? formatPct(lp.unmapped_pct) : "pending"} tone={unmappedTone} />
              <ResourceLine label="Proper pairs" value={lp?.proper_pair_pct != null ? formatPct(lp.proper_pair_pct) : "pending"} tone={lp?.proper_pair_pct > 80 ? "ok" : lp?.proper_pair_pct != null ? "warn" : undefined} />
              <ResourceLine label="MAPQ 60" value={hasLiveData ? formatPct(lp.mapq_60_pct) : "pending"} />
            </div>
            <div className="dash-map-panel">
              <h3>Reference signal</h3>
              <ResourceLine label="Primary 1-22,X,Y,M" value={hasLiveData ? `${primaryShare.toFixed(1)}%` : "pending"} tone={primaryShare > 97 ? "ok" : hasLiveData ? "warn" : undefined} />
              <ResourceLine label="Other contigs" value={offPrimaryShare != null ? `${offPrimaryShare.toFixed(1)}%` : "pending"} tone={offPrimaryTone} />
              <ResourceLine label="chrM" value={mtShare != null ? `${mtShare}%` : "pending"} />
            </div>
            <div className="dash-map-panel">
              <h3>Alignment shape</h3>
              <ResourceLine label="Clean CIGAR" value={cigarPct("clean")} />
              <ResourceLine label="Soft clipped" value={cigarPct("soft_clip")} tone={(lp?.cigar_classes?.soft_clip || 0) > 0 ? "warn" : undefined} />
              <ResourceLine label="X+Y share" value={hasLiveData ? `${sexShare.toFixed(1)}%` : "pending"} />
            </div>
          </div>
          <div className="dash-evidence-chromosomes">
            <div className="dash-chromosome-list-head">
              <span>Primary contigs</span>
              <em>{covTiles.length ? "mean depth" : "mapped share"}</em>
            </div>
            {chromosomeMetrics.map(({ chr, row, liveChr, value, label }) => {
              const barPct = value == null ? 0 : Math.max(2, Math.min(100, (value / chromosomeScale) * 100));
              return (
                <button key={chr} className={"dash-evidence-row " + (selectedChr === chr ? "sel " : "") + (row || liveChr ? "" : "empty")} onClick={() => onSelectChr(selectedChr === chr ? null : chr)}>
                  <span className="dash-evidence-chr-label">
                    <b>chr {chr}</b>
                    {chr === "M" && value != null && value > chromosomeScale * 2 ? <small>mtDNA high copy</small> : null}
                  </span>
                  <span className="dash-evidence-track" aria-hidden="true">
                    <i style={{ width: `${barPct}%` }} />
                  </span>
                  <em>{label}</em>
                </button>
              );
            })}
          </div>
          <div className="dash-evidence-note">
            {selectedChr ? (
              <span>chr{selectedChr}: {selectedCov != null ? selectedCov.toFixed(1) + "x coverage" : selectedLiveChr ? `${selectedLiveChr.reads.toLocaleString()} mapped reads; ${selectedLiveChr.pct}% current share${expectedRefPct(selectedChr) != null ? ` vs ${expectedRefPct(selectedChr).toFixed(1)}% autosomal reference share` : ""}` : "no coverage tiles"}</span>
            ) : (
              <span>{covTiles.length ? "Select a chromosome to inspect imported coverage." : "During alignment this is a pre-QC mapped-read histogram, not depth coverage or contamination proof. Depth and callable coverage arrive after Coverage/QC."}</span>
            )}
          </div>
        </div>
      </div>

      {/* Runs */}
      <div className="card dash-runs">
        <div className="card-head">
          <h2>Runs</h2>
          <Link href="/runs">View all →</Link>
        </div>
        <RunsList runs={runs} />
      </div>
    </div>
  );
}

/* ── Shared Components ── */
function RunsList({ runs = [] }) {
  const visibleRuns = runs.slice(0, 5);

  if (!visibleRuns.length) return <div className="dash-empty">No runs yet</div>;
  return (
    <div className="dash-run-list">
      {visibleRuns.map(r => (
        <Link key={r.id} href={`/runs?id=${r.id}`} className={`dash-run-item ${r.status}`}>
          <div>
            <span className="dash-run-name">{r.project_name || r.project_id || r.id.slice(0, 10)}</span>
            <span className={`badge badge-${r.status === "done" ? "ok" : ["running", "paused", "cancelled", "cancelling"].includes(r.status) ? "warn" : "err"}`}>{r.status}</span>
          </div>
          <small>{r.mode} · {r.id.slice(0, 10)}</small>
        </Link>
      ))}
    </div>
  );
}

function ChrDistribution({ chromosomes, total }) {
  const byKey = new Map();
  for (const item of chromosomes || []) {
    byKey.set(normalizeChrKey(item.chr), item);
  }
  const primaryRows = PRIMARY_DISPLAY_CONTIGS.map((key) => byKey.get(key) || { chr: key, reads: 0, pct: 0, missing: true });
  const extraRows = (chromosomes || [])
    .filter((item) => !PRIMARY_DISPLAY_CONTIGS.includes(normalizeChrKey(item.chr)))
    .sort((a, b) => (b.reads || 0) - (a.reads || 0))
    .slice(0, 10);
  const rows = [...primaryRows, ...extraRows];
  const maxPct = Math.max(
    1,
    ...rows.map(c => c.pct || 0),
    ...rows.map(c => expectedRefPct(c.chr) || 0),
  );
  return (
    <div className="dash-chr-body">
      <div className="dash-chr-legend">
        <span><i className="current" />current mapped share</span>
        <span><i className="expected" />autosomal reference share</span>
      </div>
      {primaryRows.map(chr => {
        const expectedPct = expectedRefPct(chr.chr);
        const currentWidth = Math.max(2, Math.round(((chr.pct || 0) / maxPct) * 100));
        const expectedWidth = expectedPct == null ? 0 : Math.max(2, Math.round((expectedPct / maxPct) * 100));
        const deltaLabel = expectedDeltaLabel(chr.chr, chr.pct || 0, expectedPct);
        const metricLabel = expectedPct == null ? `${chr.pct}%` : `${chr.pct}% · ${deltaLabel}`;
        return (
          <div key={chr.chr} className={`dash-chr-row ${expectedPct == null ? "no-baseline" : ""} ${chr.missing ? "empty" : ""}`}>
            <b>{displayContigName(chr.chr)}</b>
            <span className="dash-chr-track">
              {expectedPct != null && <i className="expected" style={{ width: `${expectedWidth}%` }} />}
              {!chr.missing && <i className="current" style={{ width: `${currentWidth}%` }} />}
            </span>
            <em>{chr.missing ? "—" : chr.reads.toLocaleString()}</em>
            <small>{metricLabel}</small>
            <span className="dash-chr-name" />
          </div>
        );
      })}
      {extraRows.length > 0 && (
        <>
          <div className="dash-chr-divider"><span>other mapped contigs · top 10</span></div>
          {extraRows.map(chr => {
            return (
              <div key={chr.chr} className="dash-chr-row no-baseline off-primary extra" title={chr.chr}>
                <b>+</b>
                <span className="dash-chr-name">{chr.chr}</span>
                <em>{chr.reads.toLocaleString()}</em>
                <small>mapped reads</small>
                <span />
              </div>
            );
          })}
        </>
      )}
      <p className="dash-chr-note">
        Bars compare primary reference reads already emitted by the aligner. Non-primary contigs are listed without bars, sorted by mapped reads.
      </p>
    </div>
  );
}

function AlnMetric({ label, value, sub }) {
  return (
    <div className="dash-aln-metric">
      <span>{label}</span>
      <b>{value}</b>
      {sub && <small>{sub}</small>}
    </div>
  );
}

function StatCard({ label, value, sub, color, className = "", title }) {
  return (
    <div className={`card stat-card ${className}`} title={title}>
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={color ? { color: `var(--color-${color})` } : undefined}>{value}</div>
      {sub && <small>{sub}</small>}
    </div>
  );
}

function ResourceLine({ label, value, tone, mono }) {
  return (
    <div className="dash-resource-line">
      <span>{label}</span>
      <b className={tone || ""} style={{ fontFamily: mono ? "var(--font-mono)" : undefined }}>{value}</b>
    </div>
  );
}

function MetricPill({ label, value, tone, className = "", title }) {
  return (
    <div className={`dash-metric-pill ${tone || ""} ${className}`} title={title}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}
