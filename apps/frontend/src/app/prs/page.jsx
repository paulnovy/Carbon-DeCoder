"use client";

import { API_BASE } from "@/lib/api";
import { useEffect, useState } from "react";
import { StageActionButtons } from "@/components/RunControls";
import { useAppSelection } from "@/components/AppSelectionProvider";
import { Button, PageHeader, Panel } from "@/components/ui";

async function fetchJson(url, options, fallback = null) {
  try {
    const r = await fetch(url, options);
    if (!r.ok) return fallback;
    return await r.json();
  } catch {
    return fallback;
  }
}

export default function PRSPage() {
  const { selectedProjectId, selectedRunId, selectedSampleId } = useAppSelection();
  const [project, setProject] = useState(null);
  const [samples, setSamples] = useState([]);
  const [runs, setRuns] = useState([]);
  const [runSteps, setRunSteps] = useState([]);
  const [readiness, setReadiness] = useState(null);
  const [scores, setScores] = useState(null);
  const [manifest, setManifest] = useState(null);
  const [manifestValidation, setManifestValidation] = useState(null);
  const [panel, setPanel] = useState(null);
  const [busy, setBusy] = useState(false);

  const selectedRun = runs.find((run) => run.id === selectedRunId) || null;
  const selectedSample = samples.find((s) => s.id === selectedSampleId || s.sample_id === selectedSampleId) || null;
  const sampleId = selectedSample?.sample_id || selectedSample?.id || selectedSampleId;

  useEffect(() => { init(); }, []);
  useEffect(() => { loadContext(); }, [selectedProjectId]);
  useEffect(() => {
    if (sampleId && selectedRunId) loadReadiness(sampleId, selectedRunId);
    else setReadiness(null);
  }, [sampleId, selectedRunId]);
  useEffect(() => {
    if (!selectedRunId) {
      setRunSteps([]);
      return;
    }
    loadRunSteps(selectedRunId);
  }, [selectedRunId]);

  async function init() {
    await Promise.all([loadScores(), loadManifest()]);
  }

  async function loadContext() {
    if (!selectedProjectId) {
      setProject(null);
      setSamples([]);
      setRuns([]);
      return;
    }
    const [projectData, sampleData, runData] = await Promise.all([
      fetchJson(`${API_BASE}/projects/${selectedProjectId}`, null, null),
      fetchJson(`${API_BASE}/projects/${selectedProjectId}/samples`, null, { items: [] }),
      fetchJson(`${API_BASE}/projects/${selectedProjectId}/runs`, null, { items: [] }),
    ]);
    setProject(projectData);
    setSamples(sampleData.items || sampleData || []);
    setRuns((runData.items || runData || []).slice().sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")));
  }

  async function loadRunSteps(runId = selectedRun?.id) {
    if (!runId) return;
    const data = await fetchJson(`${API_BASE}/runs/${runId}/steps`, null, { items: [] });
    setRunSteps(data.items || data || []);
  }

  async function loadReadiness(sid, runId = selectedRunId) {
    const params = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    const data = await fetchJson(`${API_BASE}/samples/${sid}/prs/readiness${params}`);
    setReadiness(data);
  }

  async function loadScores() {
    const data = await fetchJson(`${API_BASE}/prs/scores`, null, { items: [] });
    setScores(data);
  }

  async function loadManifest() {
    const [status, validation] = await Promise.all([
      fetchJson(`${API_BASE}/prs/catalog/manifest`, null, null),
      fetchJson(`${API_BASE}/prs/catalog/manifest/validate`, null, null),
    ]);
    setManifest(status);
    setManifestValidation(validation || status?.validation || null);
  }

  async function runPanel(panelMode = "curated") {
    if (!sampleId || !selectedRunId) return;
    setBusy(true);
    const data = await fetchJson(`${API_BASE}/prs/panel/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sample_id: sampleId, run_id: selectedRunId, limit: 300, min_match_rate: 0.5, panel: panelMode }),
    });
    setPanel(data);
    await loadScores();
    setBusy(false);
  }

  const scoreCount = scores?.items?.length || 0;
  const validation = manifestValidation || manifest?.validation || {};
  const manifestValid = Boolean(validation?.valid);
  const sampleReference = selectedSample?.reference_id || "";
  const manifestBuilds = validation?.genome_builds || {};
  const hasGrch38Manifest = Object.keys(manifestBuilds).some((build) => String(build).toUpperCase().includes("GRCH38"));
  const grch38Sample = String(sampleReference).toUpperCase().includes("GRCH38");
  const buildMismatch = manifestValid && grch38Sample && !hasGrch38Manifest;
  const panelDisabled = busy || !sampleId || !selectedRunId || scoreCount === 0 || !manifestValid || buildMismatch;

  return (
    <div>
      <PageHeader
        eyebrow="Interpretation resources"
        title="Polygenic Risk Scores"
        description="Sample PRS execution gate. PGS Catalog downloads and manifests are managed in Settings."
      />

      <Panel title="Sample PRS gate" description="PRS is evaluated against the selected sample, active run context, variant import, coverage callability, and manifest build.">
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
          <ContextMetric label="Project" value={project?.name || selectedProjectId || "Select in Projects"} />
          <ContextMetric label="Run" value={selectedRun?.id || selectedRunId || "Select in Projects"} />
          <ContextMetric label="Sample" value={selectedSample?.sample_id || selectedSampleId || "Select in Projects"} />
          <Button variant="primary" onClick={() => runPanel("curated")} disabled={panelDisabled}>Run approved PRS panel</Button>
          {selectedRun && (
            <>
              <span style={{ fontSize: 12, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                {selectedRun.id.slice(0, 12)} · {selectedRun.status}
              </span>
              <StageActionButtons
                run={selectedRun}
                stage="prs"
                steps={runSteps}
                onRefresh={() => loadRunSteps()}
                compact
              />
            </>
          )}
        </div>
        <Status label="Sample variants" value={`${readiness?.variant_count ?? 0} imported`} tone={(readiness?.variant_count || 0) > 0 ? "ok" : "warn"} />
        <Status label="Whole-genome readiness" value={readiness?.ready ? "variants + coverage OK" : "blocked / not interpretable"} tone={readiness?.ready ? "ok" : "warn"} />
        <Status label="PGS score files" value={`${scoreCount} downloaded`} tone={scoreCount ? "ok" : "warn"} />
        <Status label="Curated manifest" value={manifestValid ? `${validation.count} approved` : "missing / draft only"} tone={manifestValid ? "ok" : "warn"} />
        <Status label="Build gate" value={buildMismatch ? `${sampleReference || "sample"} vs manifest mismatch` : "compatible or not selected"} tone={buildMismatch ? "warn" : "ok"} />
        <Status label="Interpretation" value="research-only, non-diagnostic" tone="warn" />
        {!manifestValid && <Notice tone="warn">PRS calculation is blocked until an operator-curated manifest is configured. Downloaded PGS files are only raw resources.</Notice>}
        {buildMismatch && <Notice tone="warn">PRS calculation is blocked for this sample because the approved manifest is not GRCh38-compatible.</Notice>}
        {readiness?.coverage && (
          <p style={{ margin: "10px 0 0", color: "var(--color-text-muted)", fontSize: 12 }}>
            Coverage gate: mean {formatCoverage(readiness.coverage.mean_coverage)}, callable {formatPercent(readiness.coverage.callable_fraction)}; required {readiness.requirements?.min_mean_coverage ?? 20}x and {formatPercent(readiness.requirements?.min_callable_fraction ?? 0.8)} callable.
          </p>
        )}
        {readiness?.reasons?.length > 0 && (
          <p style={{ margin: "10px 0 0", color: "var(--color-text-muted)", fontSize: 12 }}>
            Readiness notes: {readiness.reasons.join("; ")}
          </p>
        )}
        {(readiness?.variant_count || 0) === 0 && (
          <Notice tone="warn">PRS needs an imported sample variant set from the variants stage. Catalog downloads and draft manifests are resource metadata, not sample results.</Notice>
        )}
      </Panel>

      {panel && (
        <Panel title="Latest PRS panel result">
          <Status label="Panel source" value={panel.panel_source || "—"} tone="ok" />
          <Status label="Scores attempted" value={panel.count ?? 0} tone="ok" />
          <Status label="Errors" value={panel.errors?.length || 0} tone={panel.errors?.length ? "warn" : "ok"} />
          <Status label="Output class" value={panel.non_diagnostic ? "non-diagnostic research output" : "unknown"} tone="warn" />
          {panel.readiness?.reasons?.length > 0 && (
            <Notice tone="warn">Readiness caveats: {panel.readiness.reasons.join("; ")}</Notice>
          )}
          {panel.errors?.length > 0 && (
            <div style={{ marginTop: 10, display: "grid", gap: 6 }}>
              {panel.errors.slice(0, 5).map((err) => <Notice key={`${err.pgs_id}-${err.error}`} tone="warn">{err.pgs_id}: {err.error}</Notice>)}
            </div>
          )}
          <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
            {(panel.items || []).slice(0, 20).map((item) => (
              <div key={item.pgs_id} style={{ display: "grid", gridTemplateColumns: "110px minmax(180px, 1fr) 120px 110px 95px 90px", gap: 10, fontSize: 12, borderTop: "1px solid var(--color-border-muted)", paddingTop: 8, overflowX: "auto" }}>
                <b>{item.pgs_id}</b>
                <span>{item.trait}</span>
                <span>{item.risk_band}</span>
                <span>{item.quality_label}</span>
                <span>{formatPercent(item.match_rate)} match</span>
                <span>{item.genome_build || "build ?"}</span>
                {item.caveats?.length > 0 && (
                  <span style={{ gridColumn: "1 / -1", color: "var(--color-text-muted)", overflowWrap: "anywhere" }}>
                    Caveats: {item.caveats.join(" ")}
                  </span>
                )}
              </div>
            ))}
          </div>
        </Panel>
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

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${Math.round(Number(value) * 100)}%`;
}

function formatCoverage(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "unknown";
  return `${Number(value).toFixed(1)}x`;
}

function Notice({ children, tone = "warn" }) {
  const color = tone === "ok" ? "var(--color-ok)" : "var(--color-warn)";
  return (
    <div style={{ border: `1px solid ${color}`, borderRadius: 8, padding: "8px 10px", color, background: "var(--color-bg-elevated)", fontSize: 12, overflowWrap: "anywhere" }}>
      {children}
    </div>
  );
}

function Status({ label, value, tone }) {
  const color = tone === "ok" ? "var(--color-ok)" : "var(--color-warn)";
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 16, borderTop: "1px solid var(--color-border-muted)", padding: "8px 0", fontSize: 13 }}>
      <span style={{ color: "var(--color-text-muted)" }}>{label}</span>
      <b style={{ color }}>{value}</b>
    </div>
  );
}
