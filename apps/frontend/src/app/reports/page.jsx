"use client";

import { API_BASE } from "@/lib/api";
import { useState, useEffect } from "react";
import { useAppSelection } from "@/components/AppSelectionProvider";
import { Button, ConfirmDialog, EmptyState, PageHeader, Panel } from "@/components/ui";


export default function ReportsPage() {
  const { selectedProjectId, selectedRunId, selectionReady } = useAppSelection();
  const [project, setProject] = useState(null);
  const [runs, setRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedReport, setExpandedReport] = useState(null);
  const [confirmRegenerate, setConfirmRegenerate] = useState(false);

  useEffect(() => {
    if (selectionReady) loadData();
  }, [selectionReady, selectedProjectId, selectedRunId]);
  useEffect(() => {
    if (selectedRun) loadReports(selectedRun);
    else setReports([]);
  }, [selectedRun]);

  const loadData = async () => {
    if (!selectionReady) return;
    setLoading(true);
    try {
      const projsRes = await fetch(`${API_BASE}/projects`);
      const projsData = await projsRes.json();
      const projects = projsData.items || [];
      const scopedProjects = selectedProjectId
        ? projects.filter((projectItem) => projectItem.id === selectedProjectId)
        : projects;
      setProject(selectedProjectId ? projects.find((projectItem) => projectItem.id === selectedProjectId) || null : null);
      const allRuns = [];
      for (const p of scopedProjects) {
        try {
          const rRes = await fetch(`${API_BASE}/projects/${p.id}/runs`);
          const rData = await rRes.json();
          for (const r of rData.items || rData || []) allRuns.push({ ...r, project_name: p.name });
        } catch {}
      }
      const sortedRuns = allRuns.slice().sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
      setRuns(sortedRuns);
      setSelectedRun(sortedRuns.find((run) => run.id === selectedRunId)?.id || sortedRuns[0]?.id || null);
    } catch (e) {
      console.error(e);
      setProject(null);
      setRuns([]);
      setSelectedRun(null);
    } finally { setLoading(false); }
  };

  const loadReports = async (runId) => {
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/reports`);
      if (res.ok) { const data = await res.json(); setReports(data.items || []); }
    } catch { setReports([]); }
  };

  const generateReports = async () => {
    if (!selectedRun) return;
    const alreadyGenerated = reports.filter(r => r.status === "generated").length;
    if (alreadyGenerated > 0 && !confirmRegenerate) {
      setConfirmRegenerate(true);
      return;
    }
    try {
      setConfirmRegenerate(false);
      await fetch(`${API_BASE}/runs/${selectedRun}/reports/generate-all`, { method: "POST" });
      await loadReports(selectedRun);
    } catch (e) { console.error(e); }
  };

  if (loading) return <div style={{ color: "var(--color-text-secondary)", padding: 40 }}>Loading reports…</div>;

  return (
    <div>
      <PageHeader
        eyebrow="Artifacts"
        title="Reports"
        description="Generated analysis reports with full summary details and exportable JSON payloads."
      />

      {/* Controls */}
      <Panel title="Report Context" description="Select a run, generate report artifacts, or export the current report list.">
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <ContextMetric label="Project" value={project?.name || selectedProjectId || "Select in Projects"} />
          <label style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Run:</label>
          <select value={selectedRun || ""} onChange={(e) => setSelectedRun(e.target.value)} className="form-control" style={{ minWidth: 280 }}>
            {runs.map((r) => <option key={r.id} value={r.id}>{r.id.slice(0, 16)}… ({r.project_name} · {r.mode})</option>)}
            {runs.length === 0 && <option value="">No runs available</option>}
          </select>
          <Button onClick={generateReports} disabled={!selectedRun}>{reports.length > 0 ? "Regenerate All" : "Generate All"}</Button>
          <Button variant="secondary" onClick={() => {
            const blob = new Blob([JSON.stringify(reports, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url; a.download = `reports-${selectedRun || "all"}.json`; a.click();
            URL.revokeObjectURL(url);
          }} disabled={!selectedRun}>Export JSON</Button>
          <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{reports.length} reports</span>
        </div>
      </Panel>

      {/* Report grid */}
      {reports.length === 0 ? (
        <EmptyState title="No reports" description={selectedRun ? "Generate reports for the selected run to create JSON, HTML, and bundle artifacts." : "No run is available for the selected project."} />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 16 }}>
          {reports.map((rpt) => (
            <ReportCard key={rpt.id} report={rpt} onClick={() => setExpandedReport(rpt)} />
          ))}
        </div>
      )}

      {/* Detail modal */}
      {expandedReport && (
        <ReportModal report={expandedReport} onClose={() => setExpandedReport(null)} />
      )}

      <ConfirmDialog
        open={confirmRegenerate}
        title="Regenerate reports?"
        description={`${reports.filter(r => r.status === "generated").length} generated report artifacts already exist for this run.`}
        details={[
          "Report records will be refreshed from the current run evidence.",
          "This does not restart pipeline stages or delete raw analysis outputs.",
        ]}
        confirmLabel="Regenerate all"
        tone="warning"
        onCancel={() => setConfirmRegenerate(false)}
        onConfirm={generateReports}
      />
    </div>
  );
}

/* ── Report Card ──────────────────────────────────────────────────── */

function ReportCard({ report, onClick }) {
  const summary = report.summary || {};
  const icon = reportIcon(report.report_type);

  return (
    <Panel className="report-card" onClick={onClick} style={{ cursor: "pointer" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 20 }}>{icon}</span>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>{formatType(report.report_type)}</div>
            <div style={{ fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>{report.id}</div>
          </div>
        </div>
        <span className={`badge ${report.status === "generated" ? "badge-ok" : "badge-warn"}`}>{report.status}</span>
      </div>

      <SummarySnippet type={report.report_type} summary={summary} />

      {summary.non_diagnostic && <div style={{ marginTop: 8 }}><span className="badge badge-warn" style={{ fontSize: 10 }}>non-diagnostic</span></div>}
    </Panel>
  );
}

function SummarySnippet({ type, summary }) {
  const s = summary;
  const snippets = {
    qc: () => s.status && <span>Status: {s.status} · Reads: {s.total_reads?.toLocaleString()}</span>,
    alignment: () => s.flagstat && <span>Mapped: {s.flagstat.mapped_reads_pct}% · Dups: {s.flagstat.duplicates_pct}%</span>,
    coverage: () => s.mosdepth && <span>Mean: {s.mosdepth.mean_coverage?.toFixed(1)}x · Callable: {((s.mosdepth.callable_fraction || 0) * 100).toFixed(0)}%</span>,
    variant: () => <span>{s.variant_count || 0} variants · {s.consensus_count || 0} consensus · {s.disagreement_count || 0} disagreement</span>,
    sv: () => <span>{s.sv_count || 0} SVs · {JSON.stringify(s.type_distribution || {})}</span>,
    cnv: () => <span>{s.segment_count || 0} segments · Gain: {s.gain_count || 0} Loss: {s.loss_count || 0}</span>,
    taxonomy: () => s.top_hits?.[0] && <span>Top: {s.top_hits[0].organism} ({s.top_hits[0].read_count} reads)</span>,
    trust: () => <span>Avg trust: {s.trust_score_avg?.toFixed(1)} · Labels: {JSON.stringify(s.label_distribution || {})}</span>,
    prs: () => s.items?.[0] && <span>{s.items[0].trait}: {s.items[0].score_value}</span>,
    mtdna: () => s.items?.[0] && <span>Haplogroup: {s.items[0].haplogroup} · Variants: {s.items[0].num_variants}</span>,
    giab_benchmark: () => <span>F1: {s.f1?.toFixed(4)} · P: {s.precision?.toFixed(4)} · R: {s.recall?.toFixed(4)}</span>,
    vendor_validation: () => <span>Status: {s.latest?.status || "unknown"} · Similarity: {s.latest?.similarity_score?.toFixed(3) || "-"}</span>,
    acceptance: () => <span>Status: {s.status || "unknown"} · Records: {s.count || 0} · VCF: {s.asset_counts?.vcf || 0}</span>,
    full_technical: () => <span>{s.sections?.length || 0} sections · {s.sample_id}</span>,
    annotation: () => <span>{s.annotated_count || 0} annotated variants</span>,
  };
  const fn = snippets[type];
  return <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{fn ? fn() : <span>Report generated</span>}</div>;
}

/* ── Detail Modal ─────────────────────────────────────────────────── */

function ReportModal({ report, onClose }) {
  const summary = report.summary || {};
  const keys = Object.keys(summary).filter((k) => k !== "non_diagnostic");

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" style={{ width: 720, maxHeight: "84vh", overflow: "auto" }} onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 24 }}>{reportIcon(report.report_type)}</span>
            <div>
              <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>{formatType(report.report_type)}</h2>
              <div style={{ fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>{report.id}</div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Button variant="secondary" size="sm" onClick={() => {
              const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url; a.download = `${report.report_type}-${report.id}.json`; a.click();
              URL.revokeObjectURL(url);
            }}>JSON</Button>
            <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
          </div>
        </div>

        {/* Status */}
        <div style={{ display: "flex", gap: 12, marginBottom: 20, fontSize: 13 }}>
          <span className={`badge ${report.status === "generated" ? "badge-ok" : "badge-warn"}`}>{report.status}</span>
          <span style={{ color: "var(--color-text-muted)" }}>Run: {report.run_id}</span>
          <span style={{ color: "var(--color-text-muted)" }}>{new Date(report.created_at).toLocaleString()}</span>
        </div>

        {/* Summary fields */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {keys.map((key) => (
            <SummaryField key={key} name={key} value={summary[key]} />
          ))}
        </div>

        {summary.non_diagnostic && (
          <div style={{ marginTop: 16, padding: 12, background: "var(--color-bg-base)", borderRadius: 6, borderLeft: "3px solid var(--color-warn)", fontSize: 12, color: "var(--color-text-secondary)" }}>
            ⚠ This report is research-only and non-diagnostic. Results require professional interpretation.
          </div>
        )}
      </div>
    </div>
  );
}

function SummaryField({ name, value }) {
  if (value == null || value === "") return null;

  if (typeof value === "object" && !Array.isArray(value)) {
    return (
      <div>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "uppercase", marginBottom: 6, letterSpacing: "0.05em" }}>
          {name.replace(/_/g, " ")}
        </div>
        <div style={{ padding: "10px 14px", background: "var(--color-bg-base)", borderRadius: 6, fontSize: 12, fontFamily: "var(--font-mono)" }}>
          {Object.entries(value).map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "2px 0", borderBottom: "1px solid var(--color-border-muted)" }}>
              <span style={{ color: "var(--color-text-secondary)" }}>{k}</span>
              <span>{typeof v === "object" ? JSON.stringify(v) : String(v)}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (Array.isArray(value)) {
    return (
      <div>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "uppercase", marginBottom: 6 }}>
          {name.replace(/_/g, " ")} ({value.length})
        </div>
        <div style={{ padding: "10px 14px", background: "var(--color-bg-base)", borderRadius: 6, fontSize: 12, fontFamily: "var(--font-mono)", maxHeight: 200, overflow: "auto" }}>
          {value.map((item, i) => (
            <div key={i} style={{ padding: "2px 0", borderBottom: "1px solid var(--color-border-muted)" }}>
              {typeof item === "object" ? JSON.stringify(item) : String(item)}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--color-border-muted)" }}>
      <span style={{ fontSize: 13, color: "var(--color-text-secondary)", fontWeight: 500 }}>{name.replace(/_/g, " ")}</span>
      <span style={{ fontSize: 13, fontFamily: "var(--font-mono)" }}>{String(value)}</span>
    </div>
  );
}

/* ── Helpers ──────────────────────────────────────────────────────── */

function reportIcon(type) {
  return { qc: "◈", alignment: "⌬", coverage: "▬", variant: "◇", sv: "⬡", cnv: "⬡", annotation: "✎", prs: "∑", mtdna: "◎", taxonomy: "❋", giab_benchmark: "⚑", trust: "◉", vendor_validation: "✓", acceptance: "▣", full_technical: "⎙" }[type] || "◌";
}

function formatType(type) { return type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()); }

function ContextMetric({ label, value }) {
  return (
    <div style={{ minWidth: 160 }}>
      <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>{label}</div>
      <div style={{ marginTop: 3, fontSize: 12, color: "var(--color-text-secondary)", fontFamily: "var(--font-mono)", overflowWrap: "anywhere" }}>{value}</div>
    </div>
  );
}
