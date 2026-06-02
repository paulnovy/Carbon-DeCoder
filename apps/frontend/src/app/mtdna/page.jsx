"use client";

import { API_BASE } from "@/lib/api";
import { useState, useEffect } from "react";
import { StageActionButtons } from "@/components/RunControls";
import { useAppSelection } from "@/components/AppSelectionProvider";
import { EmptyState, PageHeader, Panel } from "@/components/ui";


function trustColor(score) {
  if (score >= 80) return "var(--color-ok)";
  if (score >= 50) return "#e6a817";
  return "var(--color-err)";
}

export default function MtDNAPage() {
  const { selectedProjectId, selectedRunId, selectedSampleId, selectionReady } = useAppSelection();
  const [project, setProject] = useState(null);
  const [samples, setSamples] = useState([]);
  const [runs, setRuns] = useState([]);
  const [selectedSample, setSelectedSample] = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const [runSteps, setRunSteps] = useState([]);
  const [mtdnaData, setMtDNAData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (selectionReady) loadData();
  }, [selectionReady, selectedProjectId, selectedSampleId]);
  useEffect(() => {
    if (selectedSample) loadMtDNA(selectedSample);
    else setMtDNAData(null);
  }, [selectedSample]);
  useEffect(() => {
    if (!selectedSample) {
      setSelectedRun(null);
      setRunSteps([]);
      return;
    }
    const sampleRuns = runs
      .filter((run) => run.sample_id === selectedSample)
      .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    setSelectedRun(sampleRuns.find((run) => run.id === selectedRunId) || sampleRuns[0] || null);
  }, [selectedSample, selectedRunId, runs]);
  useEffect(() => {
    if (!selectedRun) {
      setRunSteps([]);
      return;
    }
    refreshRunSteps(selectedRun.id);
  }, [selectedRun?.id]);

  const loadData = async () => {
    if (!selectionReady) return;
    setLoading(true);
    try {
      const pRes = await fetch(`${API_BASE}/projects`);
      const pData = await pRes.json();
      const projs = pData.items || [];
      const scopedProjects = selectedProjectId
        ? projs.filter((projectItem) => projectItem.id === selectedProjectId)
        : projs;
      setProject(selectedProjectId ? projs.find((projectItem) => projectItem.id === selectedProjectId) || null : null);
      const all = [];
      const allRuns = [];
      for (const p of scopedProjects) {
        try {
          const sRes = await fetch(`${API_BASE}/projects/${p.id}/samples`);
          const sData = await sRes.json();
          for (const s of (sData.items || [])) all.push({ ...s, project_name: p.name, project_id: p.id });
        } catch {}
        try {
          const rRes = await fetch(`${API_BASE}/projects/${p.id}/runs`);
          const rData = await rRes.json();
          for (const r of (rData.items || [])) allRuns.push({ ...r, project_name: p.name });
        } catch {}
      }
      setSamples(all);
      setRuns(allRuns);
      const preferredSample = all.find((sample) => sample.id === selectedSampleId || sample.sample_id === selectedSampleId);
      setSelectedSample(preferredSample?.id || all[0]?.id || null);
    } catch (e) {
      console.error(e);
      setProject(null);
      setSamples([]);
      setRuns([]);
      setSelectedSample(null);
    }
    finally { setLoading(false); }
  };

  const refreshRunSteps = async (runId = selectedRun?.id) => {
    if (!runId) return;
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/steps`);
      const data = res.ok ? await res.json() : { items: [] };
      setRunSteps(data.items || data || []);
    } catch {
      setRunSteps([]);
    }
  };

  const loadMtDNA = async (id) => {
    try {
      const res = await fetch(`${API_BASE}/samples/${id}/mtdna`);
      setMtDNAData(await res.json());
    } catch { setMtDNAData(null); }
  };

  const items = mtdnaData?.items || [];
  const warnings = mtdnaData?.warnings || [];

  return (
    <div>
      <PageHeader
        eyebrow="Mitochondrial analysis"
        title="Mitochondrial DNA"
        description="Haplogroup assignments, heteroplasmy, and NUMTs warnings with explicit research-only guardrails."
      />

      {/* sample selector */}
      <Panel title="mtDNA Context" description="Select the sample and run scope used for mtDNA review.">
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <ContextMetric label="Project" value={project?.name || selectedProjectId || "Select in Projects"} />
          <label style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Sample:</label>
          <select
            value={selectedSample || ""}
            onChange={(e) => setSelectedSample(e.target.value)}
            className="form-control"
            style={{ width: 320, maxWidth: "100%" }}
          >
            {samples.map((s) => <option key={s.id} value={s.id}>{s.sample_id || s.id} ({s.project_name})</option>)}
            {samples.length === 0 && <option>No samples</option>}
          </select>
          {selectedRun && (
            <>
              <span style={{ fontSize: 12, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                {selectedRun.id.slice(0, 12)} · {selectedRun.status}
              </span>
              <StageActionButtons
                run={selectedRun}
                stage="mtdna"
                steps={runSteps}
                onRefresh={() => refreshRunSteps()}
                compact
              />
            </>
          )}
        </div>
      </Panel>

      {loading && <div style={{ color: "var(--color-text-muted)", padding: 20 }}>Loading…</div>}

      {!loading && items.length === 0 && (
        <EmptyState
          title="No mtDNA results yet"
          description={selectedProjectId ? "No mtDNA data is available for the selected project/run." : "Select a project and run in Projects to review mtDNA results."}
        />
      )}

      {!loading && warnings.length > 0 && (
        <div style={{ padding: "10px 12px", background: "#422006", border: "1px solid #92400e", borderRadius: 8, fontSize: 12, color: "#fcd34d", marginBottom: 16 }}>
          <strong>NUMTs review needed:</strong> {mtdnaData?.numts_warning_count || warnings.length} mtDNA result{(mtdnaData?.numts_warning_count || warnings.length) === 1 ? "" : "s"} flagged. Review nuclear mitochondrial insertion / contamination evidence before using mtDNA calls.
        </div>
      )}

      {/* mtDNA cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: 16 }}>
        {items.map((m) => (
          <Panel key={m.id}>
            {/* haplogroup header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <div>
                <span style={{ fontSize: 20, fontWeight: 700, color: "var(--color-accent)" }}>
                  {m.haplogroup || "Unknown"}
                </span>
                <span style={{ fontSize: 12, color: "var(--color-text-muted)", marginLeft: 8 }}>haplogroup</span>
              </div>
              <span style={{ fontSize: 11, background: "var(--color-bg-elevated)", color: "var(--color-text-muted)", padding: "2px 8px", borderRadius: 4 }}>
                {m.run_id ? m.run_id.slice(0, 12) : "—"}
              </span>
            </div>

            {/* metrics grid */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
              <MetricBox label="Heteroplasmy (mean VAF)" value={m.heteroplasmy_mean_vaf != null ? `${(m.heteroplasmy_mean_vaf * 100).toFixed(1)}%` : "—"} />
              <MetricBox label="Variants detected" value={m.num_variants ?? "—"} />
              <MetricBox label="Trust score" value={m.trust_score != null ? `${m.trust_score.toFixed(1)}%` : "—"} color={trustColor(m.trust_score)} />
              <MetricBox label="Trust label" value={m.trust_label || "—"} />
            </div>

            {/* NUMTs warning */}
            {m.numts_warning && (
              <div style={{ padding: "8px 12px", background: "#422006", border: "1px solid #92400e", borderRadius: 6, fontSize: 12, color: "#fcd34d", marginBottom: 10 }}>
                ⚠ <strong>NUMTs warning</strong> — nuclear mitochondrial insertions detected. Some variants may be artefactual.
              </div>
            )}
            {warnings.find((w) => w.id === m.id)?.reasons?.length > 0 && (
              <ul style={{ margin: "0 0 10px", paddingLeft: 18, color: "var(--color-text-muted)", fontSize: 12 }}>
                {warnings.find((w) => w.id === m.id).reasons.map((reason) => <li key={reason}>{reason}</li>)}
              </ul>
            )}

            {/* metadata footer */}
            <div style={{ paddingTop: 8, borderTop: "1px solid var(--color-border-muted)", fontSize: 11, color: "var(--color-text-muted)", display: "flex", justifyContent: "space-between" }}>
              <span>ref: {m.reference_id || "—"}</span>
              <span>sample: {m.sample_id || "—"}</span>
            </div>
          </Panel>
        ))}
      </div>
    </div>
  );
}

function MetricBox({ label, value, color }) {
  return (
    <div style={{ background: "var(--color-bg-elevated)", borderRadius: 6, padding: "8px 12px" }}>
      <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 600, color: color || "var(--color-text-primary)" }}>{value}</div>
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
