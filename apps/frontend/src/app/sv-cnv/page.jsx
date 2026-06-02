"use client";

import { API_BASE } from "@/lib/api";
import { useState, useEffect } from "react";
import { StageActionButtons } from "@/components/RunControls";
import { useAppSelection } from "@/components/AppSelectionProvider";
import { EmptyState as SharedEmptyState, PageHeader, Panel } from "@/components/ui";


export default function SvCnvPage() {
  const { selectedProjectId, selectedRunId, selectedSampleId } = useAppSelection();
  const [project, setProject] = useState(null);
  const [samples, setSamples] = useState([]);
  const [runs, setRuns] = useState([]);
  const [runSteps, setRunSteps] = useState([]);
  const [runEvents, setRunEvents] = useState([]);
  const [svData, setSvData] = useState(null);
  const [cnvData, setCnvData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("sv");

  const selectedRun = runs.find((run) => run.id === selectedRunId) || null;
  const selectedSample = samples.find((sample) => sample.id === selectedSampleId || sample.sample_id === selectedSampleId) || null;
  const sampleKey = selectedSample?.sample_id || selectedSample?.id || selectedSampleId;

  useEffect(() => {
    loadContext();
  }, [selectedProjectId]);

  useEffect(() => {
    setSvData(null);
    setCnvData(null);
  }, [sampleKey, selectedRunId]);

  useEffect(() => {
    if (!sampleKey || !selectedRunId) return;
    if (tab === "sv" && svData == null) loadVariantData(sampleKey, selectedRunId, "sv");
    if (tab === "cnv" && cnvData == null) loadVariantData(sampleKey, selectedRunId, "cnv");
  }, [tab, sampleKey, selectedRunId, svData, cnvData]);

  useEffect(() => {
    if (!selectedRunId) {
      setRunSteps([]);
      setRunEvents([]);
      return;
    }
    const loadRunContext = async () => {
      const stepsRes = await fetch(`${API_BASE}/runs/${selectedRunId}/steps`).then((r) => r.ok ? r.json() : null).catch(() => null);
      setRunSteps(stepsRes ? stepsRes.items || [] : []);
      setRunEvents([]);
    };
    loadRunContext();
  }, [selectedRunId]);

  const refreshRunContext = async () => {
    if (!selectedRun) return;
    const [stepsRes, eventsRes] = await Promise.allSettled([
      fetch(`${API_BASE}/runs/${selectedRun.id}/steps`).then((r) => r.ok ? r.json() : null),
      fetch(`${API_BASE}/runs/${selectedRun.id}/events`).then((r) => r.ok ? r.json() : null),
    ]);
    setRunSteps(stepsRes.status === "fulfilled" && stepsRes.value ? stepsRes.value.items || [] : []);
    setRunEvents(eventsRes.status === "fulfilled" && eventsRes.value ? eventsRes.value.items || [] : []);
  };

  const loadContext = async () => {
    if (!selectedProjectId) {
      setProject(null);
      setSamples([]);
      setRuns([]);
      setSvData(null);
      setCnvData(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [projectRes, samplesRes, runsRes] = await Promise.all([
        fetch(`${API_BASE}/projects/${selectedProjectId}`),
        fetch(`${API_BASE}/projects/${selectedProjectId}/samples`),
        fetch(`${API_BASE}/projects/${selectedProjectId}/runs`),
      ]);
      setProject(projectRes.ok ? await projectRes.json() : null);
      const samplesData = samplesRes.ok ? await samplesRes.json() : { items: [] };
      const runsData = runsRes.ok ? await runsRes.json() : { items: [] };
      setSamples(samplesData.items || samplesData || []);
      setRuns((runsData.items || runsData || []).slice().sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")));
    } catch (e) {
      console.error("Failed to load SV/CNV context:", e);
      setProject(null);
      setSamples([]);
      setRuns([]);
    } finally {
      setLoading(false);
    }
  };

  const loadVariantData = async (sampleId, runId, kind) => {
    try {
      const data = await fetch(`${API_BASE}/samples/${sampleId}/${kind}?run_id=${encodeURIComponent(runId)}`).then((r) => r.ok ? r.json() : null);
      const items = data ? data.items || data || [] : [];
      if (kind === "sv") setSvData(items);
      if (kind === "cnv") setCnvData(items);
    } catch {
      if (kind === "sv") setSvData([]);
      if (kind === "cnv") setCnvData([]);
    }
  };

  if (loading) {
    return <div style={{ color: "var(--color-text-secondary)", padding: 40 }}>Loading SV/CNV data…</div>;
  }

  return (
    <div>
      <PageHeader
        eyebrow="Structural variation"
        title="SV / CNV"
        description="Run-scoped structural variants and copy-number segments for the project/run selected in Projects."
      />

      <Panel title="SV/CNV Context">
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <ContextMetric label="Project" value={project?.name || selectedProjectId || "Select in Projects"} />
          <ContextMetric label="Run" value={selectedRun?.id || selectedRunId || "Select in Projects"} />
          <ContextMetric label="Sample" value={selectedSample?.sample_id || selectedSampleId || "Select in Projects"} />

          <div style={{ display: "flex", background: "var(--color-bg-base)", borderRadius: 6, overflow: "hidden", border: "1px solid var(--color-border-default)" }}>
            <TabButton active={tab === "sv"} onClick={() => setTab("sv")} label={`SV (${svData == null ? "…" : svData.length})`} />
            <TabButton active={tab === "cnv"} onClick={() => setTab("cnv")} label={`CNV (${cnvData == null ? "…" : cnvData.length})`} />
          </div>
          {selectedRun && (
            <StageActionButtons
              run={selectedRun}
              stage={tab}
              steps={runSteps}
              onRefresh={refreshRunContext}
              compact
            />
          )}
        </div>
      </Panel>

      {!selectedProjectId || !selectedRunId || !sampleKey ? (
        <SharedEmptyState title="No run selected" description="Select a project and run in Projects to inspect SV/CNV calls." />
      ) : tab === "sv" ? (
        <SvView data={svData || []} loading={svData == null} stageContext={stageContextFor("sv", selectedRun, runSteps, runEvents)} />
      ) : (
        <CnvView data={cnvData || []} loading={cnvData == null} stageContext={stageContextFor("cnv", selectedRun, runSteps, runEvents)} />
      )}
    </div>
  );
}

function ContextMetric({ label, value }) {
  return (
    <div style={{ minWidth: 160 }}>
      <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>{label}</div>
      <div style={{ marginTop: 3, fontSize: 12, color: "var(--color-text-secondary)", fontFamily: "var(--font-mono)", overflowWrap: "anywhere" }}>{value}</div>
    </div>
  );
}

function SvView({ data, loading, stageContext }) {
  if (loading) {
    return <div style={{ color: "var(--color-text-secondary)", padding: 20 }}>Loading SV data…</div>;
  }

  if (data.length === 0) {
    return <StageEmptyState title={stageContext.title} text={stageContext.text} detail={stageContext.detail} tone={stageContext.tone} />;
  }

  const typeCounts = {};
  const evidenceCounts = {};
  for (const sv of data) {
    const t = sv.sv_type || "OTHER";
    typeCounts[t] = (typeCounts[t] || 0) + 1;
    for (const evidence of sv.evidence_types || []) {
      evidenceCounts[evidence] = (evidenceCounts[evidence] || 0) + 1;
    }
  }

  return (
    <div>
      {/* Type summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 12, marginBottom: 24 }}>
        {Object.entries(typeCounts).map(([type, count]) => (
          <div key={type} className="card" style={{ padding: 14, textAlign: "center" }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: "var(--color-accent)", fontFamily: "var(--font-mono)" }}>{count}</div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{type}</div>
          </div>
        ))}
      </div>
      {Object.keys(evidenceCounts).length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
          {Object.entries(evidenceCounts).map(([evidence, count]) => (
            <span key={evidence} className="badge badge-info">{evidence}: {count}</span>
          ))}
        </div>
      )}

      {/* SV table */}
      <div className="card" style={{ overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "var(--color-bg-elevated)" }}>
              <Th>Type</Th>
              <Th>Location</Th>
              <Th>Size</Th>
              <Th>Callers</Th>
              <Th>Evidence</Th>
              <Th>Quality</Th>
              <Th>Trust</Th>
            </tr>
          </thead>
          <tbody>
            {data.map((sv, i) => (
              <tr key={i} style={{ borderBottom: "1px solid var(--color-border-muted)" }}>
                <Td><span className="badge badge-accent">{sv.sv_type || "SV"}</span></Td>
                <Td mono>{sv.chrom}:{sv.start?.toLocaleString()}{sv.end_chrom && sv.end_chrom !== sv.chrom ? ` → ${sv.end_chrom}:${sv.end_pos?.toLocaleString()}` : `–${sv.end?.toLocaleString()}`}</Td>
                <Td mono>{sv.size_bp ? formatSize(sv.size_bp) : (sv.start && sv.end ? formatSize(sv.end - sv.start) : "—")}</Td>
                <Td style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{sv.caller_list?.join(", ") || sv.callers?.join(", ") || sv.caller || "—"}</Td>
                <Td>
                  <EvidenceList items={sv.evidence_types || []} />
                </Td>
                <Td mono>{sv.quality_score ?? "—"}</Td>
                <Td><TrustBadge score={sv.trust_score} /></Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CnvView({ data, loading, stageContext }) {
  if (loading) {
    return <div style={{ color: "var(--color-text-secondary)", padding: 20 }}>Loading CNV data…</div>;
  }

  if (data.length === 0) {
    return <StageEmptyState title={stageContext.title} text={stageContext.text} detail={stageContext.detail} tone={stageContext.tone} />;
  }

  const gainCount = data.filter((c) => (c.copy_number || 2) > 2).length;
  const lossCount = data.filter((c) => (c.copy_number || 2) < 2).length;
  const neutralCount = data.filter((c) => (c.copy_number || 2) === 2).length;

  return (
    <div>
      {/* Summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16, marginBottom: 24 }}>
        <StatCard label="Total Segments" value={data.length} />
        <StatCard label="Gains (CN>2)" value={gainCount} color="ok" />
        <StatCard label="Losses (CN<2)" value={lossCount} color="err" />
        <StatCard label="Neutral (CN=2)" value={neutralCount} />
      </div>

      {/* CNV table */}
      <div className="card" style={{ overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "var(--color-bg-elevated)" }}>
              <Th>Chrom</Th>
              <Th>Start</Th>
              <Th>End</Th>
              <Th>Size</Th>
              <Th>CN</Th>
              <Th>Event</Th>
              <Th>Method</Th>
              <Th>Trust</Th>
            </tr>
          </thead>
          <tbody>
            {data.map((seg, i) => {
              const cn = seg.copy_number ?? 2;
              const event = cn > 2 ? "GAIN" : cn < 2 ? "LOSS" : "NEUTRAL";
              const eventColor = cn > 2 ? "ok" : cn < 2 ? "err" : "info";
              return (
                <tr key={i} style={{ borderBottom: "1px solid var(--color-border-muted)" }}>
                  <Td mono>{seg.chrom}</Td>
                  <Td mono>{seg.start?.toLocaleString()}</Td>
                  <Td mono>{seg.end?.toLocaleString()}</Td>
                  <Td mono>{seg.start && seg.end ? formatSize(seg.end - seg.start) : "—"}</Td>
                  <Td mono style={{ fontWeight: 600, color: cn !== 2 ? (cn > 2 ? "var(--color-ok)" : "var(--color-err)") : "var(--color-text-primary)" }}>{cn}</Td>
                  <Td><span className={`badge badge-${eventColor}`}>{seg.cnv_type || event}</span></Td>
                  <Td style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{seg.method || "—"}</Td>
                  <Td><TrustBadge score={seg.trust_score} /></Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EvidenceList({ items }) {
  if (!items.length) return <span style={{ color: "var(--color-text-muted)" }}>—</span>;
  return (
    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
      {items.map((item) => (
        <span key={item} className="badge badge-info" style={{ fontSize: 10 }}>{item}</span>
      ))}
    </div>
  );
}

function StageEmptyState({ title, text, detail, tone = "neutral" }) {
  const toneColor = tone === "bad" ? "var(--color-err)" : tone === "warn" ? "var(--color-warn)" : "var(--color-text-muted)";
  return (
    <SharedEmptyState
      title={title}
      description={text}
      action={detail ? <span style={{ color: toneColor, fontFamily: "var(--font-mono)", fontSize: 12 }}>{detail}</span> : null}
    />
  );
}

function stageContextFor(stage, run, steps, events) {
  const label = stage === "sv" ? "SV" : "CNV";
  if (!run) {
    return {
      title: `${label} has not run`,
      text: "No run is available for this sample yet.",
      detail: null,
      tone: "neutral",
    };
  }

  const aliases = stage === "sv" ? ["sv", "sv_calling"] : ["cnv", "cnv_calling"];
  const step = [...steps].reverse().find((item) => aliases.includes(item.step_name));
  const latestEvent = [...events].reverse().find((event) => aliases.some((name) => String(event.event_type || "").includes(name)));
  const status = step?.status || (run.status === "done" ? "not_observed" : run.status);
  const detail = step?.last_log || step?.error || latestEvent?.event_type || `run ${run.id.slice(0, 12)} · ${run.status}`;

  if (status === "done") {
    return {
      title: `${label} finished with zero calls`,
      text: "The stage completed and no records are currently imported for this sample.",
      detail,
      tone: "neutral",
    };
  }
  if (status === "skipped") {
    return {
      title: `${label} was skipped`,
      text: "This is an intentional or best-effort skip, not a zero-call biological result.",
      detail,
      tone: "warn",
    };
  }
  if (status === "blocked") {
    return {
      title: `${label} was blocked by an upstream dependency`,
      text: "Fix or rerun the required upstream stage before interpreting this module.",
      detail,
      tone: "warn",
    };
  }
  if (status === "failed") {
    return {
      title: `${label} stage failed`,
      text: "No records are shown because the stage did not finish successfully.",
      detail,
      tone: "bad",
    };
  }
  if (["running", "queued", "paused", "cancelling"].includes(status)) {
    return {
      title: `${label} is ${status}`,
      text: "Results will appear after the stage finishes and its artifacts are ingested.",
      detail,
      tone: "neutral",
    };
  }
  return {
    title: `${label} has not been observed`,
    text: "No stage status or imported records are available for this sample.",
    detail,
    tone: "neutral",
  };
}

function StatCard({ label, value, color }) {
  return (
    <div className="card" style={{ padding: 16 }}>
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ fontSize: 20, color: color ? `var(--color-${color})` : undefined, fontFamily: "var(--font-mono)" }}>{value}</div>
    </div>
  );
}

function TabButton({ active, onClick, label }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "6px 16px",
        background: active ? "var(--color-accent-bg)" : "transparent",
        border: "none",
        color: active ? "var(--color-accent)" : "var(--color-text-secondary)",
        fontSize: 13,
        fontWeight: active ? 600 : 400,
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );
}

function Th({ children }) {
  return <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600, fontSize: 11, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em", borderBottom: "1px solid var(--color-border-default)" }}>{children}</th>;
}

function Td({ children, mono, style: extra }) {
  return <td style={{ padding: "8px 12px", fontFamily: mono ? "var(--font-mono)" : undefined, fontSize: mono ? 12 : undefined, ...extra }}>{children}</td>;
}

function TrustBadge({ score }) {
  if (score == null) return <span style={{ color: "var(--color-text-muted)" }}>—</span>;
  const color = score >= 70 ? "ok" : score >= 40 ? "warn" : "err";
  return <span className={`badge badge-${color}`}>{score}</span>;
}

function formatSize(bp) {
  if (bp >= 1_000_000) return (bp / 1_000_000).toFixed(1) + " Mb";
  if (bp >= 1_000) return (bp / 1_000).toFixed(1) + " kb";
  return bp + " bp";
}
